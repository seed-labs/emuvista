"""Diagnostics DNS implementations."""

import re

from seedemu_tool_service.tools.dns.basic.tools import BasicTools
from seedemu_tool_service.tools.dns.diagnostics.models import (
    DNSCompareDifference,
    DNSCompareResult,
    DNSCompareServerResult,
    DNSDelegationAddressResult,
    DNSDelegationChildResult,
    DNSDelegationResult,
    DNSTraceResult,
    DNSTraceStep,
)
from seedemu_tool_service.tools.dns.shared.models import DNSRecord, DNSRecordType

_TRACE_RECEIVED_PATTERN = re.compile(
    r";; Received\s+\d+\s+bytes\s+from\s+(.+?)\s+in\s+(\d+)\s+ms"
)


class DiagnosticTools(BasicTools):
    """Diagnostics DNS operations."""

    def compare(
        self,
        source: str,
        name: str,
        servers: list[str | None],
        record_type: DNSRecordType = "A",
        timeout_seconds: int = 3,
    ) -> DNSCompareResult:
        """Compare the same DNS query across resolvers from one source node."""

        server_results: list[DNSCompareServerResult] = []
        answer_sets: list[set[str]] = []
        statuses: list[str | None] = []

        for server in servers:
            lookup_result = self.lookup(
                source=source,
                name=name,
                record_type=record_type,
                include_details=True,
                server=server,
                timeout_seconds=timeout_seconds,
            )
            details = lookup_result.details
            answer_records = (
                [
                    record
                    for record in details.answer_records
                    if record.record_type == record_type
                ]
                if details is not None
                else []
            )
            timed_out = lookup_result.response_status == "timeout"
            server_results.append(
                DNSCompareServerResult(
                    server=server,
                    command_successful=lookup_result.command_successful,
                    response_status=lookup_result.response_status,
                    answers=lookup_result.answers,
                    answer_records=answer_records,
                    ttls=[record.ttl for record in answer_records],
                    latency_ms=details.query_time_ms if details is not None else None,
                    timed_out=timed_out,
                )
            )
            answer_sets.append(set(lookup_result.answers))
            statuses.append(lookup_result.response_status)

        all_answers = set().union(*answer_sets)
        common_answers = set.intersection(*answer_sets)
        differences = [
            DNSCompareDifference(
                answer=answer,
                present_on=[
                    server
                    for server, answers in zip(servers, answer_sets, strict=True)
                    if answer in answers
                ],
                missing_from=[
                    server
                    for server, answers in zip(servers, answer_sets, strict=True)
                    if answer not in answers
                ],
            )
            for answer in sorted(all_answers)
            if any(answer not in answers for answers in answer_sets)
        ]
        ttls = [ttl for result in server_results for ttl in result.ttls]

        return DNSCompareResult(
            source=source,
            name=name,
            record_type=record_type,
            results=server_results,
            answers_consistent=(
                len(set(statuses)) == 1
                and all(answers == answer_sets[0] for answers in answer_sets[1:])
            ),
            common_answers=sorted(common_answers),
            differences=differences,
            min_ttl=min(ttls) if ttls else None,
            max_ttl=max(ttls) if ttls else None,
            timed_out_servers=[result.server for result in server_results if result.timed_out],
        )

    def trace(
        self,
        source: str,
        name: str,
        record_type: DNSRecordType = "A",
        server: str | None = None,
        timeout_seconds: int = 3,
    ) -> DNSTraceResult:
        """Follow DNS delegations from an emulated source node using dig +trace."""

        command = ["dig", "+trace", f"+time={timeout_seconds}", "+tries=1"]
        if server is not None:
            command.append(f"@{server}")
        command.extend([name, record_type])

        result = self._backend.execute(source, command)
        steps = self._parse_trace_steps(result.stdout)
        final_answers = (
            [
                record
                for record in steps[-1].records
                if record.record_type == record_type
            ]
            if steps
            else []
        )

        return DNSTraceResult(
            source=source,
            name=name,
            record_type=record_type,
            server=server,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
            steps=steps,
            final_answers=final_answers,
            raw_output=result.stdout,
        )

    def check_delegation(
        self,
        source: str,
        zone: str,
        parent_server: str,
        child_servers: list[str],
        timeout_seconds: int = 3,
    ) -> DNSDelegationResult:
        """Compare a parent referral with each child authoritative server."""

        normalized_zone = f"{zone.rstrip('.').lower()}."
        parent_result = self.lookup(
            source=source,
            name=normalized_zone,
            record_type="NS",
            include_details=True,
            server=parent_server,
            timeout_seconds=timeout_seconds,
        )
        parent_details = parent_result.details
        parent_records = (
            parent_details.answer_records + parent_details.authority_records
            if parent_details is not None
            else []
        )
        parent_ns_names = sorted(
            {
                f"{record.value.rstrip('.').lower()}."
                for record in parent_records
                if record.record_type == "NS"
                and f"{record.name.rstrip('.').lower()}." == normalized_zone
            }
        )
        glue_records = (
            [
                record
                for record in parent_details.additional_records
                if record.record_type in {"A", "AAAA"}
                and f"{record.name.rstrip('.').lower()}." in parent_ns_names
            ]
            if parent_details is not None
            else []
        )
        glue_names = {
            f"{record.name.rstrip('.').lower()}." for record in glue_records
        }
        in_bailiwick_names = {
            name
            for name in parent_ns_names
            if name == normalized_zone or name.endswith(f".{normalized_zone}")
        }
        missing_glue_names = sorted(in_bailiwick_names - glue_names)
        parent_glue_rrsets: dict[tuple[str, str], set[str]] = {}
        for record in glue_records:
            key = (f"{record.name.rstrip('.').lower()}.", record.record_type)
            parent_glue_rrsets.setdefault(key, set()).add(record.value)

        issues: list[str] = []
        if not parent_result.command_successful:
            issues.append("parent query failed")
        if parent_result.response_status != "NOERROR":
            issues.append(
                f"parent returned {parent_result.response_status or 'no DNS status'}"
            )
        if not parent_ns_names:
            issues.append("parent returned no delegation NS records")
        if missing_glue_names:
            issues.append("in-bailiwick name servers are missing glue records")

        child_results: list[DNSDelegationChildResult] = []
        parent_ns_set = set(parent_ns_names)
        for child_server in child_servers:
            child_lookup = self.lookup(
                source=source,
                name=normalized_zone,
                record_type="NS",
                include_details=True,
                server=child_server,
                timeout_seconds=timeout_seconds,
            )
            child_details = child_lookup.details
            child_ns_names = sorted(
                {
                    f"{record.value.rstrip('.').lower()}."
                    for record in (
                        child_details.answer_records if child_details is not None else []
                    )
                    if record.record_type == "NS"
                    and f"{record.name.rstrip('.').lower()}." == normalized_zone
                }
            )
            child_issues: list[str] = []
            if not child_lookup.command_successful:
                child_issues.append("query failed")
            if child_lookup.response_status != "NOERROR":
                child_issues.append(
                    f"returned {child_lookup.response_status or 'no DNS status'}"
                )
            if not child_lookup.authoritative:
                child_issues.append("response is not authoritative")
            if set(child_ns_names) != parent_ns_set:
                child_issues.append("NS records differ from the parent referral")
            if not child_ns_names:
                child_issues.append("returned no apex NS records")

            address_results: list[DNSDelegationAddressResult] = []
            for (name, address_type), parent_addresses in sorted(
                parent_glue_rrsets.items()
            ):
                address_lookup = self.lookup(
                    source=source,
                    name=name,
                    record_type=address_type,
                    include_details=True,
                    server=child_server,
                    timeout_seconds=timeout_seconds,
                )
                child_addresses = sorted(set(address_lookup.answers))
                matches_parent = (
                    address_lookup.command_successful
                    and address_lookup.response_status == "NOERROR"
                    and address_lookup.authoritative
                    and set(child_addresses) == parent_addresses
                )
                address_results.append(
                    DNSDelegationAddressResult(
                        name=name,
                        record_type=address_type,
                        parent_addresses=sorted(parent_addresses),
                        child_addresses=child_addresses,
                        command_successful=address_lookup.command_successful,
                        response_status=address_lookup.response_status,
                        authoritative=address_lookup.authoritative,
                        matches_parent=matches_parent,
                    )
                )
                if not matches_parent:
                    child_issues.append(
                        f"{name} {address_type} differs from parent glue"
                    )

            child_results.append(
                DNSDelegationChildResult(
                    server=child_server,
                    command_successful=child_lookup.command_successful,
                    response_status=child_lookup.response_status,
                    authoritative=child_lookup.authoritative,
                    ns_names=child_ns_names,
                    ns_matches_parent=set(child_ns_names) == parent_ns_set,
                    address_results=address_results,
                    issues=child_issues,
                )
            )
            issues.extend(
                f"child server {child_server}: {issue}" for issue in child_issues
            )

        return DNSDelegationResult(
            source=source,
            zone=normalized_zone,
            parent_server=parent_server,
            parent_command_successful=parent_result.command_successful,
            parent_response_status=parent_result.response_status,
            parent_ns_names=parent_ns_names,
            glue_records=glue_records,
            missing_glue_names=missing_glue_names,
            child_results=child_results,
            consistent=not issues,
            issues=issues,
        )

    @staticmethod
    def _parse_trace_steps(output: str) -> list[DNSTraceStep]:
        """Split dig +trace output into ordered DNS responses."""

        steps: list[DNSTraceStep] = []
        records: list[DNSRecord] = []

        for line in output.splitlines():
            received_match = _TRACE_RECEIVED_PATTERN.fullmatch(line.strip())
            if received_match:
                steps.append(
                    DNSTraceStep(
                        records=records,
                        responding_server=received_match.group(1),
                        response_time_ms=int(received_match.group(2)),
                    )
                )
                records = []
                continue

            if not line.strip() or line.startswith(";"):
                continue
            fields = line.split(None, 4)
            if len(fields) != 5:
                continue
            try:
                ttl = int(fields[1])
            except ValueError:
                continue
            records.append(
                DNSRecord(
                    name=fields[0],
                    ttl=ttl,
                    record_class=fields[2],
                    record_type=fields[3],
                    value=fields[4],
                )
            )

        # Preserve useful records even when dig terminates before printing a
        # final "Received" line.
        if records:
            steps.append(DNSTraceStep(records=records))

        return steps
