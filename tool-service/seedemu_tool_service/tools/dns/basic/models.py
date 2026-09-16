"""Basic DNS models."""

from ipaddress import ip_address

from pydantic import BaseModel, Field, field_validator

from seedemu_tool_service.tools.dns.shared.models import DNSRecord, DNSRecordType, ToolArguments


class DNSLookupArguments(ToolArguments):
    """Arguments accepted by the DNS lookup tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    name: str = Field(min_length=1, description="Domain name or address to query")
    record_type: DNSRecordType = Field(default="A", description="DNS record type")
    include_details: bool = Field(
        default=False,
        description="Include parsed DNS records, flags, server, and timing metadata",
    )
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete dig output for diagnostics",
    )
    server: str | None = Field(
        default=None,
        description="Optional DNS server address; uses the source node resolver when omitted",
    )
    timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        description="DNS query timeout in seconds",
    )

class DNSReverseLookupArguments(ToolArguments):
    """Arguments accepted by the IP reverse-lookup tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    address: str = Field(description="Strictly validated IPv4 or IPv6 address")
    server: str | None = Field(
        default=None,
        description="Optional DNS server address; uses the source node resolver when omitted",
    )
    timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        description="DNS query timeout in seconds",
    )

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        """Reject non-IP input and normalize valid IPv4 and IPv6 addresses."""

        return str(ip_address(value))

class DNSReverseLookupResult(BaseModel):
    """Structured result of an IPv4 or IPv6 reverse DNS query."""

    ptr_names: list[str] = Field(default_factory=list)
    reverse_name: str
    response_status: str | None = None
    records: list[DNSRecord] = Field(default_factory=list)
    successful: bool

class DNSLookupDetails(BaseModel):
    """Optional structured diagnostics parsed from a DNS response."""

    flags: list[str] = Field(default_factory=list)
    answer_records: list[DNSRecord] = Field(default_factory=list)
    authority_records: list[DNSRecord] = Field(default_factory=list)
    additional_records: list[DNSRecord] = Field(default_factory=list)
    recursion_available: bool = False
    authenticated_data: bool = False
    query_time_ms: int | None = None
    responding_server: str | None = None

class DNSLookupResult(BaseModel):
    """Compact DNS lookup result with optional diagnostic evidence."""

    command_successful: bool = Field(
        description="Whether dig completed successfully, independent of the DNS response code"
    )
    response_status: str | None = Field(
        default=None,
        description="DNS response code, or timeout when the query timed out",
    )
    authoritative: bool = False
    truncated: bool = False
    canonical_name: str | None = None
    answers: list[str] = Field(
        default_factory=list,
        description="Values from answer records matching the requested record type",
    )
    exit_code: int
    stderr: str
    details: DNSLookupDetails | None = None
    raw_output: str | None = None
