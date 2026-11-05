"""Models for remote TLS PKI tools."""

from typing import Literal

from pydantic import BaseModel, Field

from seedemu_tool_service.tools.pki.shared.models import CertificateFields, ToolArguments


class InspectRemoteTLSCertificateArguments(ToolArguments):
    """Arguments accepted by the remote TLS certificate inspection tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(
        default=None,
        description="Optional Server Name Indication value for virtual-hosted TLS services",
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for the TLS connection attempt",
    )


class InspectRemoteTLSChainArguments(InspectRemoteTLSCertificateArguments):
    """Arguments accepted by the remote TLS chain inspection tool."""


class InspectTLSHandshakeArguments(InspectRemoteTLSCertificateArguments):
    """Arguments accepted by the TLS handshake inspection tool."""


class CheckTLSHostnameArguments(ToolArguments):
    """Arguments accepted by the TLS hostname verification tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    expected_hostname: str = Field(
        min_length=1,
        description="Hostname expected to be covered by the remote TLS certificate",
    )
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(
        default=None,
        description=(
            "Optional Server Name Indication value. Defaults to expected_hostname "
            "when omitted."
        ),
    )
    ca_file_path: str | None = Field(
        default=None,
        description="Optional CA bundle used to verify the remote certificate",
    )
    ca_directory_path: str | None = Field(
        default=None,
        description="Optional hashed CA directory used to verify the remote certificate",
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for the TLS connection attempt",
    )


class CheckTLSProtocolsArguments(ToolArguments):
    """Arguments accepted by the TLS protocol-version check tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(
        default=None,
        description="Optional Server Name Indication value for virtual-hosted TLS services",
    )
    protocols: list[Literal["tls1", "tls1_1", "tls1_2", "tls1_3"]] = Field(
        default_factory=lambda: ["tls1_2", "tls1_3"],
        description="OpenSSL protocol switches to test, without the leading dash",
        max_length=4,
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for each TLS connection attempt",
    )


class CheckTLSCipherArguments(ToolArguments):
    """Arguments accepted by the TLS cipher check tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(min_length=1, description="TLS service host or address to connect to")
    cipher: str = Field(min_length=1, description="Cipher string to test with OpenSSL")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    server_name: str | None = Field(
        default=None,
        description="Optional Server Name Indication value for virtual-hosted TLS services",
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Maximum time allowed for the TLS connection attempt",
    )


class TLSHandshakeFields(BaseModel):
    """Parsed TLS handshake details."""

    protocol: str | None = None
    cipher: str | None = None
    verify_return_code: str | None = None


class TLSProtocolCheck(BaseModel):
    """Result for one tested TLS protocol version."""

    protocol: str
    accepted: bool
    exit_code: int
    stderr: str


class RemoteTLSCertificateInspectionResult(BaseModel):
    """Result of inspecting the certificate presented by a TLS service."""

    source: str
    target: str
    port: int
    server_name: str | None
    successful: bool
    certificate: CertificateFields
    details: str
    exit_code: int
    stderr: str


class RemoteTLSChainInspectionResult(BaseModel):
    """Result of inspecting certificates presented by a TLS service."""

    source: str
    target: str
    port: int
    server_name: str | None
    successful: bool
    certificates_pem: list[str]
    certificate_count: int
    details: str
    exit_code: int
    stderr: str


class TLSHandshakeInspectionResult(BaseModel):
    """Result of inspecting TLS handshake details."""

    source: str
    target: str
    port: int
    server_name: str | None
    successful: bool
    handshake: TLSHandshakeFields
    details: str
    exit_code: int
    stderr: str


class TLSHostnameCheckResult(BaseModel):
    """Result of checking whether a TLS certificate matches a hostname."""

    source: str
    target: str
    port: int
    expected_hostname: str
    server_name: str
    matched: bool | None
    trusted: bool
    verification_error_category: str | None
    details: str
    exit_code: int
    stderr: str


class TLSProtocolsCheckResult(BaseModel):
    """Result of checking TLS protocol versions."""

    source: str
    target: str
    port: int
    server_name: str | None
    results: list[TLSProtocolCheck]


class TLSCipherCheckResult(BaseModel):
    """Result of checking whether a TLS cipher can be negotiated."""

    source: str
    target: str
    port: int
    server_name: str | None
    cipher: str
    accepted: bool
    negotiated_cipher: str | None
    details: str
    exit_code: int
    stderr: str
