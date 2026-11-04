"""Models for ACME certificate lifecycle tools."""

from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from seedemu_tool_service.tools.pki.shared.domains import normalize_domain
from seedemu_tool_service.tools.pki.shared.models import ToolArguments


class RequestACMECertificateArguments(ToolArguments):
    """Request a certificate from an ACME CA available inside the emulator."""

    source: str = Field(description="Container running the ACME client and HTTP service")
    ca_service_source: str = Field(description="SEEDEmu CA Service container")
    ca_service_config_path: str = Field(default="/root/.step/config/ca.json")
    directory_url: str = Field(min_length=1, description="ACME directory URL")
    domains: list[str] = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3)
    authenticator: Literal["nginx", "webroot", "dns-rfc2136"] = "nginx"
    webroot_path: str = Field(default="/var/www/html", min_length=1)
    dns_credentials_path: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Path to a Certbot dns-rfc2136 credentials file with mode 0600 or 0400; "
            "the file contents are never returned."
        ),
    )
    dns_propagation_seconds: int = Field(default=30, ge=0, le=600)
    cert_name: str | None = Field(
        default=None, min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    force_renewal: bool = False

    @field_validator("directory_url")
    @classmethod
    def validate_directory_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("An HTTPS ACME directory without embedded credentials is required")
        return value

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            name = value.rstrip(".").lower()
            wildcard = name.startswith("*.")
            base = name[2:] if wildcard else name
            name = ("*." if wildcard else "") + normalize_domain(base)
            if name not in normalized:
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def validate_authenticator(self) -> "RequestACMECertificateArguments":
        has_wildcard = any(name.startswith("*.") for name in self.domains)
        needs_dns = has_wildcard or self.dns_credentials_path is not None
        if needs_dns and self.authenticator != "dns-rfc2136":
            raise ValueError("Wildcard names and DNS credentials require dns-rfc2136")
        if self.authenticator == "dns-rfc2136" and self.dns_credentials_path is None:
            raise ValueError("dns-rfc2136 requires dns_credentials_path")
        return self

    @field_validator("dns_credentials_path")
    @classmethod
    def scoped_credentials_path(cls, value: str | None) -> str | None:
        if value is not None:
            path = PurePosixPath(value)
            root = PurePosixPath("/etc/letsencrypt/credentials")
            if (
                not path.is_absolute()
                or not path.is_relative_to(root)
                or ".." in path.parts
                or path == root
            ):
                raise ValueError(
                    "DNS credentials must be stored below /etc/letsencrypt/credentials"
                )
        return value


class RenewACMECertificateArguments(ToolArguments):
    """Renew one Certbot-managed certificate."""

    source: str
    ca_service_source: str = Field(description="SEEDEmu CA Service container")
    ca_service_config_path: str = Field(default="/root/.step/config/ca.json")
    cert_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    force_renewal: bool = False


class DeployACMECertificateToNginxArguments(ToolArguments):
    """Deploy a Certbot-managed certificate to an isolated nginx TLS site."""

    source: str
    cert_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    server_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9.-]+$")


class RevokeACMECertificateArguments(ToolArguments):
    """Revoke one certificate through its issuing ACME CA."""

    source: str
    ca_service_source: str = Field(description="SEEDEmu CA Service container")
    ca_service_config_path: str = Field(default="/root/.step/config/ca.json")
    directory_url: str = Field(min_length=1)
    certificate_path: str = Field(min_length=1)
    reason: Literal[
        "unspecified",
        "keycompromise",
        "affiliationchanged",
        "superseded",
        "cessationofoperation",
    ] = "unspecified"
    delete_after_revoke: bool = False

    @field_validator("directory_url")
    @classmethod
    def validate_directory_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("An HTTPS ACME directory without embedded credentials is required")
        return value


class ACMECertificateResult(BaseModel):
    """Structured result of an ACME lifecycle operation."""

    action: Literal["request", "deploy", "renew", "revoke"]
    source: str
    successful: bool
    cert_name: str | None = None
    domains: list[str] = Field(default_factory=list)
    certificate_path: str | None = None
    chain_path: str | None = None
    fullchain_path: str | None = None
    private_key_path: str | None = None
    renewal_config_path: str | None = None
    created_paths: list[str] = Field(default_factory=list)
    modified_paths: list[str] = Field(default_factory=list)
    backup_paths: list[str] = Field(default_factory=list)
    exit_code: int
    output: str
    stderr: str
