"""Models for certificate trust verification PKI tools."""

from pydantic import BaseModel, Field

from ..shared.models import ToolArguments


class VerifyCertificateChainArguments(ToolArguments):
    """Arguments accepted by the certificate-chain verification tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    certificate_path: str = Field(min_length=1, description="Certificate path inside the source")
    ca_file_path: str | None = Field(
        default=None,
        description="Optional CA bundle file path inside the source container",
    )
    ca_directory_path: str | None = Field(
        default=None,
        description="Optional hashed CA certificate directory inside the source container",
    )
    untrusted_chain_path: str | None = Field(
        default=None,
        description="Optional intermediate certificate chain path inside the source container",
    )


class VerifyRemoteTLSChainArguments(ToolArguments):
    """Arguments accepted by the remote TLS chain verification tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(
        default=None,
        description="Optional Server Name Indication value for virtual-hosted TLS services",
    )
    ca_file_path: str | None = Field(
        default=None,
        description="Optional CA bundle file path inside the source container",
    )
    ca_directory_path: str | None = Field(
        default=None,
        description="Optional hashed CA certificate directory inside the source container",
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for the TLS connection attempt",
    )


class VerifyCertificateAgainstCAArguments(ToolArguments):
    """Arguments accepted by the focused CA verification tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    certificate_path: str = Field(min_length=1, description="Certificate path inside the source")
    ca_file_path: str = Field(min_length=1, description="CA certificate path inside the source")


class VerifyCertificateWithIntermediatesArguments(VerifyCertificateAgainstCAArguments):
    """Arguments accepted by the intermediate-chain verification tool."""

    intermediate_chain_path: str = Field(
        min_length=1,
        description="Intermediate chain path inside the source container",
    )


class ExplainVerificationFailureArguments(ToolArguments):
    """Arguments accepted by the verification failure explanation tool."""

    output: str = Field(default="", description="OpenSSL stdout to classify")
    stderr: str = Field(default="", description="OpenSSL stderr to classify")


class CertificateChainVerificationResult(BaseModel):
    """Result of verifying a certificate chain against trusted CA material."""

    source: str
    certificate_path: str
    ca_file_path: str | None
    ca_directory_path: str | None
    untrusted_chain_path: str | None
    trusted: bool
    output: str
    exit_code: int
    stderr: str


class RemoteTLSChainVerificationResult(BaseModel):
    """Result of verifying a remote TLS service chain."""

    source: str
    target: str
    port: int
    server_name: str | None
    ca_file_path: str | None
    ca_directory_path: str | None
    trusted: bool
    output: str
    exit_code: int
    stderr: str


class VerificationFailureExplanationResult(BaseModel):
    """Normalized explanation for an OpenSSL verification failure."""

    category: str
    output: str
    stderr: str
