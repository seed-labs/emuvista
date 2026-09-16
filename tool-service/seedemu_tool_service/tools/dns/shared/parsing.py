"""Shared DNS implementations."""

import re

from seedemu_tool_service.tools.dns.shared.models import DNSRecord

_HEADER_PATTERN = re.compile(r"status:\s*([A-Z]+)")
_TIMEOUT_PATTERN = re.compile(
    r"timed?\s*out|no servers could be reached|communications error",
    re.IGNORECASE,
)


class DNSParsingMixin:
    """Shared DNS operations."""

    @staticmethod
    def _parse_record_sections(output: str) -> dict[str, list[DNSRecord]]:
        """Parse resource records from the answer, authority, and additional sections."""

        sections: dict[str, list[DNSRecord]] = {
            "ANSWER": [],
            "AUTHORITY": [],
            "ADDITIONAL": [],
        }
        current_section: str | None = None

        for line in output.splitlines():
            section_match = re.fullmatch(r";; (ANSWER|AUTHORITY|ADDITIONAL) SECTION:", line)
            if section_match:
                current_section = section_match.group(1)
                continue
            if not line.strip():
                current_section = None
                continue
            if current_section is None or line.startswith(";"):
                continue

            fields = line.split(None, 4)
            if len(fields) != 5:
                continue
            try:
                ttl = int(fields[1])
            except ValueError:
                continue

            sections[current_section].append(
                DNSRecord(
                    name=fields[0],
                    ttl=ttl,
                    record_class=fields[2],
                    record_type=fields[3],
                    value=fields[4],
                )
            )

        return sections


    @staticmethod
    def _canonical_name(name: str, records: list[DNSRecord]) -> str | None:
        """Follow an answer-section CNAME chain and return its final target."""

        aliases = {
            record.name.rstrip(".").lower(): record.value.rstrip(".")
            for record in records
            if record.record_type == "CNAME"
        }
        current = name.rstrip(".")
        visited: set[str] = set()
        while current.lower() in aliases and current.lower() not in visited:
            visited.add(current.lower())
            current = aliases[current.lower()]
        return current if visited else None

    @staticmethod
    def _response_status(stdout: str, stderr: str) -> str | None:
        """Extract a DNS response code, including dig's timeout-only output."""

        header_match = _HEADER_PATTERN.search(stdout)
        if header_match:
            return header_match.group(1)
        if _TIMEOUT_PATTERN.search(f"{stdout}\n{stderr}"):
            return "timeout"
        return None
