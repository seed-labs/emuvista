"""Domain Registration DNS models."""

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from seedemu_tool_service.tools.dns.shared.models import DNSRecordType, ToolArguments

DNSConfigureOperation = Literal["replace", "delete"]
RddsProtocol = Literal["whois", "rdap"]
RddsAuthority = Literal["registrar", "registry"]


class RegistrarFindArguments(ToolArguments):
    """Arguments for locating Registrar frontends exposed to the Agent."""

    filter: dict[str, str] = Field(
        default_factory=dict,
        description="Reserved for future Registrar filtering; must currently be empty",
    )

    @field_validator("filter")
    @classmethod
    def reject_unsupported_filters(cls, value: dict[str, str]) -> dict[str, str]:
        """Reserve the filter shape without silently ignoring caller intent."""

        if value:
            raise ValueError("filter is reserved and must currently be empty")
        return value


class RegistrarLocation(BaseModel):
    """A public Registrar frontend and its opaque credential reference."""

    registrar_url: str = Field(description="Registrar frontend origin reachable in the emulator")
    credential_ref: str | None = Field(
        default=None,
        description="Opaque reference to credentials assigned to the current principal",
    )


class RegistrarFindResult(BaseModel):
    """Registrar frontends explicitly exposed by the emulator."""

    registrars: list[RegistrarLocation] = Field(default_factory=list)
    next_step: str = Field(
        default=(
            "Select one registrar_url, then use domain.registrar_request with GET / "
            "to read its HTML and follow only same-origin links or scripts."
        )
    )


RegistrarRequestMethod = Literal["GET", "POST"]


class RegistrarRequestArguments(ToolArguments):
    """Arguments for one restricted request to a discovered Registrar frontend."""

    source: str = Field(description="Name or ID of the emulated source container")
    registrar_url: str = Field(description="Exact registrar_url returned by registrar_find")
    method: RegistrarRequestMethod = Field(default="GET")
    path: str = Field(
        default="/",
        description="Same-origin absolute path, optionally including a query string",
    )
    content_type: Literal["application/json", "application/x-www-form-urlencoded"] | None = Field(
        default=None, description="POST body media type"
    )
    body: str | None = Field(default=None, max_length=65536)
    authentication: Literal["auto", "required", "none"] = Field(
        default="auto",
        description="auto uses source credentials; required fails if absent; none skips login",
    )
    close_session: bool = Field(
        default=False, description="Delete session cookies after this request"
    )
    session_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Reuse a returned session ID; omit to create a new Cookie session",
    )

    @model_validator(mode="after")
    def validate_request(self) -> "RegistrarRequestArguments":
        """Reject ambiguous routing and request combinations."""

        if not self.source.strip() or any(character.isspace() for character in self.source):
            raise ValueError("source must be one non-empty token")
        parsed_registrar = urlparse(self.registrar_url)
        if (
            parsed_registrar.scheme not in {"http", "https"}
            or not parsed_registrar.netloc
            or parsed_registrar.username is not None
            or parsed_registrar.password is not None
            or parsed_registrar.path not in {"", "/"}
            or parsed_registrar.query
            or parsed_registrar.fragment
        ):
            raise ValueError("registrar_url must be an HTTP(S) origin without credentials")
        parsed_path = urlparse(self.path)
        if (
            not self.path.startswith("/")
            or self.path.startswith("//")
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise ValueError("path must be a same-origin absolute path without a fragment")
        if self.method == "GET" and (self.body is not None or self.content_type is not None):
            raise ValueError("GET requests cannot include a body or content_type")
        if self.method == "POST" and (self.body is None or self.content_type is None):
            raise ValueError("POST requests require body and content_type")
        self.registrar_url = self.registrar_url.rstrip("/")
        return self


class RegistrarRequestResult(BaseModel):
    """Response evidence used by an Agent to understand a Registrar frontend."""

    registrar_url: str
    requested_path: str
    method: RegistrarRequestMethod
    session_id: str
    authenticated: bool = False
    transport_successful: bool
    http_status: int | None = None
    successful: bool
    content_type: str | None = None
    location: str | None = Field(
        default=None,
        description="Unfollowed redirect target; call again only when it is same-origin",
    )
    body: str = Field(description="Bounded HTML, JavaScript, JSON, or text response body")
    truncated: bool = False
    exit_code: int
    stderr: str


class RddsLookupArguments(ToolArguments):
    """Arguments for a WHOIS or RDAP lookup through an exposed RDDS service."""

    source: str = Field(description="Name or ID of the emulated source container")
    protocol: RddsProtocol = Field(description="Use WHOIS text or RDAP JSON")
    authority: RddsAuthority = Field(
        description="Query the Registrar business view or Registry ledger view"
    )
    domain: str = Field(description="Domain name to query, for example example.com")

    @model_validator(mode="after")
    def validate_lookup(self) -> "RddsLookupArguments":
        if not self.source.strip() or any(character.isspace() for character in self.source):
            raise ValueError("source must be one non-empty token")
        domain = self.domain.lower().rstrip(".")
        pattern = (
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        )
        if not re.fullmatch(pattern, domain):
            raise ValueError("domain must be a valid fully-qualified domain name")
        self.domain = domain
        return self


class RddsLookupResult(BaseModel):
    """Bounded response from one explicitly exposed RDDS endpoint."""

    source: str
    protocol: RddsProtocol
    authority: RddsAuthority
    domain: str
    endpoint: str
    transport_successful: bool
    successful: bool
    found: bool | None = None
    http_status: int | None = None
    content_type: str | None = None
    body: str
    rdap: dict | None = None
    truncated: bool = False
    exit_code: int
    stderr: str


class DNSRecordChange(BaseModel):
    """One complete RRset replacement or deletion."""

    name: str = Field(min_length=1, description="Fully-qualified owner name inside the zone")
    record_type: DNSRecordType = Field(default="A", description="DNS record type")
    operation: DNSConfigureOperation = Field(
        default="replace",
        description="Replace the complete RRset with one value, or delete the complete RRset",
    )
    ttl: int = Field(default=300, ge=0, le=2_147_483_647, description="Record TTL in seconds")
    value: str | None = Field(
        default=None,
        description="Record value; required for replace and omitted for delete",
    )

    @model_validator(mode="after")
    def validate_change(self) -> "DNSRecordChange":
        if any(character.isspace() for character in self.name):
            raise ValueError("name must not contain whitespace")
        if self.operation == "replace":
            if self.value is None or not self.value.strip():
                raise ValueError("value is required for replace operations")
            if "\n" in self.value or "\r" in self.value:
                raise ValueError("value must not contain line breaks")
        elif self.value is not None:
            raise ValueError("value must be omitted for delete operations")

        return self


class DNSConfigureArguments(ToolArguments):
    """Create and maintain an authorized source-owned authoritative zone."""

    source: str = Field(description="Authorized emulated source container")
    dns_service_id: str = Field(description="Exact source-owned DNS service ID")
    zone: str = Field(min_length=1, description="Authorized zone, for example example.com")
    changes: list[DNSRecordChange] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_configuration(self) -> "DNSConfigureArguments":
        for field_name, value in {
            "source": self.source, "dns_service_id": self.dns_service_id, "zone": self.zone
        }.items():
            if not value.strip() or any(character.isspace() for character in value):
                raise ValueError(f"{field_name} must be one non-empty token")
        zone = self.zone.rstrip(".").lower()
        for change in self.changes:
            name = change.name.rstrip(".").lower()
            if name != zone and not name.endswith("." + zone):
                raise ValueError("every record name must be inside zone")
        self.zone = zone
        return self


class DNSAuthoritativeFindArguments(ToolArguments):
    """Arguments for discovering authoritative DNS services owned by one source."""

    source: str = Field(description="Authorized emulated source container")

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if not value.strip() or any(character.isspace() for character in value):
            raise ValueError("source must be one non-empty token")
        return value


class DNSServiceLocation(BaseModel):
    service_id: str
    primary: str
    secondary: str
    credential_ref: str


class DNSAuthoritativeFindResult(BaseModel):
    """Authoritative DNS services explicitly assigned to a source."""

    source: str
    services: list[DNSServiceLocation] = Field(default_factory=list)


class DNSConfigureResult(BaseModel):
    """Provisioning, update, and authoritative convergence evidence."""

    source: str
    dns_service_id: str
    zone: str
    primary: str
    secondary: str
    successful: bool
    exit_code: int
    stderr: str
    primary_soa: str | None = None
    secondary_soa: str | None = None
    primary_ns: list[str] = Field(default_factory=list)
    secondary_ns: list[str] = Field(default_factory=list)
    primary_authoritative: bool = False
    secondary_authoritative: bool = False
