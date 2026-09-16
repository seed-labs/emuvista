"""Basic DNS implementations."""

import re
from ipaddress import ip_address

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.dns.basic.models import (
    DNSLookupDetails,
    DNSLookupResult,
    DNSReverseLookupResult,
)
from seedemu_tool_service.tools.dns.shared.models import DNSRecordType
from seedemu_tool_service.tools.dns.shared.parsing import DNSParsingMixin

_FLAGS_PATTERN = re.compile(r";; flags:\s*([^;]+);")
_QUERY_TIME_PATTERN = re.compile(r";; Query time:\s*(\d+)\s*msec")
_SERVER_PATTERN = re.compile(r";; SERVER:\s*([^\s]+)")



class BasicTools(DNSParsingMixin):
    """Basic DNS operations."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def lookup(
        self,
        source: str,
        name: str,
        record_type: DNSRecordType = "A",
        include_details: bool = False,
        include_raw_output: bool = False,
        server: str | None = None,
        timeout_seconds: int = 3,
    ) -> DNSLookupResult:
        """Resolve DNS records from an emulated source node using dig."""

        command = ["dig", f"+time={timeout_seconds}", "+tries=1"]
        if server is not None:
            command.append(f"@{server}")
        command.extend([name, record_type])

        result = self._backend.execute(source, command)
        flags_match = _FLAGS_PATTERN.search(result.stdout)
        flags = flags_match.group(1).split() if flags_match else []
        sections = self._parse_record_sections(result.stdout)
        answer_records = sections["ANSWER"]
        response_status = self._response_status(result.stdout, result.stderr)
        query_time_match = _QUERY_TIME_PATTERN.search(result.stdout)
        server_match = _SERVER_PATTERN.search(result.stdout)
        return DNSLookupResult(
            command_successful=result.exit_code == 0,
            response_status=response_status,
            authoritative="aa" in flags,
            truncated="tc" in flags,
            canonical_name=self._canonical_name(name, answer_records),
            answers=[
                record.value
                for record in answer_records
                if record.record_type == record_type
            ],
            exit_code=result.exit_code,
            stderr=result.stderr,
            details=DNSLookupDetails(
                flags=flags,
                answer_records=answer_records,
                authority_records=sections["AUTHORITY"],
                additional_records=sections["ADDITIONAL"],
                recursion_available="ra" in flags,
                authenticated_data="ad" in flags,
                query_time_ms=(
                    int(query_time_match.group(1)) if query_time_match else None
                ),
                responding_server=server_match.group(1) if server_match else None,
            )
            if include_details
            else None,
            raw_output=result.stdout if include_raw_output else None,
        )

    def reverse_lookup(
        self,
        source: str,
        address: str,
        server: str | None = None,
        timeout_seconds: int = 3,
    ) -> DNSReverseLookupResult:
        """Resolve PTR records for a strictly validated IPv4 or IPv6 address."""

        parsed_address = ip_address(address)
        command = ["dig", f"+time={timeout_seconds}", "+tries=1"]
        if server is not None:
            command.append(f"@{server}")
        command.extend(["-x", str(parsed_address)])

        result = self._backend.execute(source, command)
        response_status = self._response_status(result.stdout, result.stderr)
        records = self._parse_record_sections(result.stdout)["ANSWER"]
        return DNSReverseLookupResult(
            ptr_names=[
                record.value for record in records if record.record_type == "PTR"
            ],
            reverse_name=parsed_address.reverse_pointer,
            response_status=response_status,
            records=records,
            successful=result.exit_code == 0 and response_status == "NOERROR",
        )
