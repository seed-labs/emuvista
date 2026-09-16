"""Diagnostics DNS models."""

from pydantic import BaseModel, Field, field_validator, model_validator

from seedemu_tool_service.tools.dns.shared.models import DNSRecord, DNSRecordType, ToolArguments


class DNSCompareArguments(ToolArguments):
    """Arguments accepted by the multi-resolver comparison tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    name: str = Field(min_length=1, description="Domain name or address to query")
    record_type: DNSRecordType = Field(default="A", description="DNS record type")
    servers: list[str | None] = Field(
        min_length=2,
        description=(
            "DNS servers to compare; use null for the source node's default resolver"
        ),
    )
    timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Timeout for each DNS server query in seconds",
    )

    @field_validator("servers")
    @classmethod
    def validate_servers(cls, servers: list[str | None]) -> list[str | None]:
        """Reject empty and duplicate server selectors."""

        normalized = [server.strip() if server is not None else None for server in servers]
        if any(server == "" for server in normalized):
            raise ValueError("server addresses must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("servers must be unique")
        return normalized

class DNSCompareServerResult(BaseModel):
    """One server's response included in a DNS comparison."""

    server: str | None = Field(
        description="Queried DNS server, or null for the source node's default resolver"
    )
    command_successful: bool
    response_status: str | None = None
    answers: list[str] = Field(default_factory=list)
    answer_records: list[DNSRecord] = Field(default_factory=list)
    ttls: list[int] = Field(default_factory=list)
    latency_ms: int | None = None
    timed_out: bool = False

class DNSCompareDifference(BaseModel):
    """Presence of one answer value across the queried DNS servers."""

    answer: str
    present_on: list[str | None] = Field(default_factory=list)
    missing_from: list[str | None] = Field(default_factory=list)

class DNSCompareResult(BaseModel):
    """Structured comparison of the same query across DNS servers."""

    source: str
    name: str
    record_type: DNSRecordType
    results: list[DNSCompareServerResult]
    answers_consistent: bool
    common_answers: list[str] = Field(default_factory=list)
    differences: list[DNSCompareDifference] = Field(default_factory=list)
    min_ttl: int | None = None
    max_ttl: int | None = None
    timed_out_servers: list[str | None] = Field(default_factory=list)

class DNSTraceArguments(ToolArguments):
    """Arguments accepted by the DNS delegation trace tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    name: str = Field(min_length=1, description="Domain name to trace")
    record_type: DNSRecordType = Field(
        default="A",
        description="DNS record type requested at the end of the trace",
    )
    server: str | None = Field(
        default=None,
        description=(
            "Optional server used to start the trace; subsequent queries follow "
            "DNS delegations"
        ),
    )
    timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Timeout for each DNS query in seconds",
    )

class DNSTraceStep(BaseModel):
    """One response received while following the DNS delegation chain."""

    records: list[DNSRecord] = Field(default_factory=list)
    responding_server: str | None = None
    response_time_ms: int | None = None

class DNSTraceResult(BaseModel):
    """Structured result produced by a dig +trace invocation."""

    source: str
    name: str
    record_type: DNSRecordType
    server: str | None
    successful: bool
    exit_code: int
    stderr: str
    steps: list[DNSTraceStep] = Field(default_factory=list)
    final_answers: list[DNSRecord] = Field(default_factory=list)
    raw_output: str

class DNSDelegationArguments(ToolArguments):
    """Arguments accepted by the DNS delegation consistency tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    zone: str = Field(min_length=1, description="Delegated child zone to check")
    parent_server: str = Field(
        min_length=1,
        description="Authoritative parent DNS server address or name",
    )
    child_servers: list[str] = Field(
        min_length=1,
        description="Authoritative child DNS server addresses or names to query",
    )
    timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Timeout for each DNS server query in seconds",
    )

    @model_validator(mode="after")
    def validate_delegation(self) -> "DNSDelegationArguments":
        """Reject empty, duplicate, or whitespace-containing DNS selectors."""

        scalar_fields = {
            "source": self.source,
            "zone": self.zone,
            "parent_server": self.parent_server,
        }
        for field_name, field_value in scalar_fields.items():
            if not field_value.strip() or any(
                character.isspace() for character in field_value
            ):
                raise ValueError(f"{field_name} must be one non-empty token")

        normalized_servers = [server.strip() for server in self.child_servers]
        if any(
            not server or any(character.isspace() for character in server)
            for server in normalized_servers
        ):
            raise ValueError("child server selectors must be non-empty tokens")
        if len(set(normalized_servers)) != len(normalized_servers):
            raise ValueError("child_servers must be unique")
        self.child_servers = normalized_servers
        return self

class DNSDelegationChildResult(BaseModel):
    """One child authoritative server's view of a delegated zone."""

    server: str
    command_successful: bool
    response_status: str | None = None
    authoritative: bool = False
    ns_names: list[str] = Field(default_factory=list)
    ns_matches_parent: bool = False
    address_results: list["DNSDelegationAddressResult"] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

class DNSDelegationAddressResult(BaseModel):
    """One authoritative child view of a parent glue address RRset."""

    name: str
    record_type: str
    parent_addresses: list[str] = Field(default_factory=list)
    child_addresses: list[str] = Field(default_factory=list)
    command_successful: bool
    response_status: str | None = None
    authoritative: bool = False
    matches_parent: bool = False

class DNSDelegationResult(BaseModel):
    """Comparison of a parent referral with child authoritative responses."""

    source: str
    zone: str
    parent_server: str
    parent_command_successful: bool
    parent_response_status: str | None = None
    parent_ns_names: list[str] = Field(default_factory=list)
    glue_records: list[DNSRecord] = Field(default_factory=list)
    missing_glue_names: list[str] = Field(default_factory=list)
    child_results: list[DNSDelegationChildResult] = Field(default_factory=list)
    consistent: bool
    issues: list[str] = Field(default_factory=list)
