"""Models for certificate expiration PKI tools."""

from pydantic import BaseModel, Field

from ..shared.models import ToolArguments


class CheckCertificateExpirationArguments(ToolArguments):
    """Arguments accepted by the certificate-expiration check tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")
    warning_seconds: int = Field(
        default=0,
        ge=0,
        le=31_536_000,
        description="Warn if the certificate expires within this many seconds",
    )


class CheckRemoteCertificateExpirationArguments(ToolArguments):
    """Arguments accepted by the remote certificate-expiration check tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(default=None, description="Optional SNI value")
    warning_seconds: int = Field(
        default=0,
        ge=0,
        le=31_536_000,
        description="Warn if the certificate expires within this many seconds",
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for the TLS connection attempt",
    )


class ListExpiringCertificatesArguments(ToolArguments):
    """Arguments accepted by the directory expiration scan tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    directory_path: str = Field(min_length=1, description="Directory to scan inside the source")
    warning_seconds: int = Field(
        default=2_592_000,
        ge=0,
        le=31_536_000,
        description="Report certificates expiring within this many seconds",
    )
    max_depth: int = Field(default=1, ge=1, le=5, description="Maximum find depth")


class CompareCertificateVersionsArguments(ToolArguments):
    """Arguments accepted by the certificate version comparison tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    first_path: str = Field(min_length=1, description="First certificate path")
    second_path: str = Field(min_length=1, description="Second certificate path")


class CertificateExpirationResult(BaseModel):
    """Result of checking a certificate's expiration window."""

    source: str
    path: str
    successful: bool
    expired: bool | None
    expires_within_warning_window: bool | None
    not_after: str | None
    details: str
    exit_code: int
    stderr: str


class ExpiringCertificateEntry(BaseModel):
    """A certificate path and its expiration status."""

    path: str
    expires_within_warning_window: bool
    not_after: str | None
    exit_code: int
    stderr: str


class ExpiringCertificatesResult(BaseModel):
    """Result of scanning a directory for expiring certificates."""

    source: str
    directory_path: str
    warning_seconds: int
    scanned_paths: list[str]
    expiring_certificates: list[ExpiringCertificateEntry]
    exit_code: int
    stderr: str


class CertificateVersionComparisonResult(BaseModel):
    """Result of comparing two certificate files."""

    source: str
    first_path: str
    second_path: str
    first_fingerprint_sha256: str | None
    second_fingerprint_sha256: str | None
    same_certificate: bool | None
    first_not_after: str | None
    second_not_after: str | None
    details: str
    exit_code: int
    stderr: str
