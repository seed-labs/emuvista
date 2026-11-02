"""Arguments for observing an existing SEEDemu ACME client."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from seedemu_tool_service.tools.pki.shared.models import ToolArguments


class InspectEnvironmentArguments(ToolArguments):
    source: str
    ca_bundle_path: str = "/etc/ssl/certs/ca-certificates.crt"


class ListManagedCertificatesArguments(ToolArguments):
    source: str
    config_directory: str = "/etc/letsencrypt"
    limit: int = Field(default=100, ge=1, le=500)


class InspectRenewalStatusArguments(ToolArguments):
    source: str
    cert_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    config_directory: str = "/etc/letsencrypt"
    log_path: str = "/var/log/letsencrypt/letsencrypt.log"


class InspectACMEReadinessArguments(InspectEnvironmentArguments):
    ca_service_source: str
    ca_service_config_path: str = "/root/.step/config/ca.json"
    directory_url: str
    domains: list[str] = Field(min_length=1, max_length=100)
    webroot_path: str = "/var/www/html"
    authenticator: Literal["nginx", "webroot", "dns-rfc2136"] = "nginx"
    dns_credentials_path: str | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=10)

    @field_validator("directory_url")
    @classmethod
    def https_directory(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("An HTTPS ACME directory without embedded credentials is required")
        return value

    @field_validator("domains")
    @classmethod
    def dns_names(cls, values: list[str]) -> list[str]:
        from seedemu_tool_service.auth.models import normalize_domain

        normalized = []
        for value in values:
            name = value.rstrip(".").lower()
            wildcard = name.startswith("*.")
            base = name[2:] if wildcard else name
            normalized.append(("*." if wildcard else "") + normalize_domain(base))
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_authenticator(self) -> "InspectACMEReadinessArguments":
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
