"""Models for certificate inspection PKI tools."""

from pydantic import BaseModel, Field

from ..shared.models import CertificateFields, ToolArguments


class InspectCertificateFileArguments(ToolArguments):
    """Arguments accepted by the certificate-file inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")


class InspectCertificateNamesArguments(ToolArguments):
    """Arguments accepted by the certificate-name inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")


class InspectCertificateExtensionsArguments(ToolArguments):
    """Arguments accepted by the certificate-extension inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")


class InspectCertificatePublicKeyArguments(ToolArguments):
    """Arguments accepted by the certificate public-key inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")


class GetCertificateFingerprintArguments(ToolArguments):
    """Arguments accepted by the certificate fingerprint tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    path: str = Field(min_length=1, description="Certificate path inside the source container")
    digest: str = Field(
        default="sha256",
        pattern="^(sha1|sha256|sha512)$",
        description="Fingerprint digest algorithm",
    )


class CertificateNames(BaseModel):
    """Parsed certificate identity names."""

    subject: str | None = None
    common_name: str | None = None
    subject_alt_names: list[str] = Field(default_factory=list)


class CertificateExtensions(BaseModel):
    """Parsed certificate extension values."""

    subject_alt_names: list[str] = Field(default_factory=list)
    key_usage: str | None = None
    extended_key_usage: str | None = None
    basic_constraints: str | None = None


class CertificatePublicKey(BaseModel):
    """Parsed certificate public-key properties."""

    algorithm: str | None = None
    bits: int | None = None


class CertificateInspectionResult(BaseModel):
    """Result of inspecting an X.509 certificate file."""

    source: str
    path: str
    successful: bool
    certificate: CertificateFields
    details: str
    exit_code: int
    stderr: str


class CertificateNamesResult(BaseModel):
    """Result of inspecting certificate names."""

    source: str
    path: str
    successful: bool
    names: CertificateNames
    details: str
    exit_code: int
    stderr: str


class CertificateExtensionsResult(BaseModel):
    """Result of inspecting certificate extensions."""

    source: str
    path: str
    successful: bool
    extensions: CertificateExtensions
    details: str
    exit_code: int
    stderr: str


class CertificatePublicKeyResult(BaseModel):
    """Result of inspecting certificate public-key properties."""

    source: str
    path: str
    successful: bool
    public_key: CertificatePublicKey
    details: str
    exit_code: int
    stderr: str


class CertificateFingerprintResult(BaseModel):
    """Result of getting a certificate fingerprint."""

    source: str
    path: str
    digest: str
    successful: bool
    fingerprint: str | None
    details: str
    exit_code: int
    stderr: str
