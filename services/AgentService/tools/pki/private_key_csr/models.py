"""Models for private-key and CSR PKI tools."""

from pydantic import BaseModel, Field

from ..shared.models import ToolArguments


class InspectPrivateKeyArguments(ToolArguments):
    """Arguments accepted by the private-key inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    key_path: str = Field(min_length=1, description="Private-key path inside the source")


class VerifyPrivateKeyMatchesCertificateArguments(InspectPrivateKeyArguments):
    """Arguments accepted by the key/certificate match tool."""

    certificate_path: str = Field(min_length=1, description="Certificate path inside the source")


class InspectCSRArguments(ToolArguments):
    """Arguments accepted by the CSR inspection tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    csr_path: str = Field(min_length=1, description="CSR path inside the source")


class PrivateKeyInspectionResult(BaseModel):
    """Result of inspecting private-key metadata."""

    source: str
    key_path: str
    successful: bool
    algorithm: str | None
    bits: int | None
    details: str
    exit_code: int
    stderr: str


class PrivateKeyMatchResult(BaseModel):
    """Result of checking whether a private key matches a certificate."""

    source: str
    key_path: str
    certificate_path: str
    matches: bool
    key_public_hash: str | None
    certificate_public_hash: str | None
    exit_code: int
    stderr: str


class CSRInspectionResult(BaseModel):
    """Result of inspecting a CSR."""

    source: str
    csr_path: str
    successful: bool
    subject: str | None
    subject_alt_names: list[str]
    details: str
    exit_code: int
    stderr: str
