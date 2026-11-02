"""Models for private-key and CSR PKI tools."""

from pydantic import BaseModel, Field

from seedemu_tool_service.tools.pki.shared.models import ToolArguments


class InspectPrivateKeyArguments(ToolArguments):
    """Arguments accepted by the private-key inspection tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    key_path: str = Field(min_length=1, description="Private-key path inside the source")


class VerifyPrivateKeyMatchesCertificateArguments(InspectPrivateKeyArguments):
    """Arguments accepted by the key/certificate match tool."""

    certificate_path: str = Field(min_length=1, description="Certificate path inside the source")


class GeneratePrivateKeyArguments(ToolArguments):
    """Arguments accepted by the private-key generation tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    output_path: str = Field(min_length=1, description="Private-key output path")
    algorithm: str = Field(default="RSA", pattern="^(RSA|EC)$")
    bits: int = Field(default=2048, ge=2048, le=8192)
    curve: str = Field(default="prime256v1", description="EC curve name")
    overwrite: bool = Field(default=False, description="Allow overwriting output_path")


class GenerateCSRArguments(ToolArguments):
    """Arguments accepted by the CSR generation tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    key_path: str = Field(min_length=1, description="Private-key path")
    output_path: str = Field(min_length=1, description="CSR output path")
    subject: str = Field(min_length=1, description="CSR subject string")
    subject_alt_names: list[str] = Field(default_factory=list)
    overwrite: bool = Field(default=False, description="Allow overwriting output_path")


class InspectCSRArguments(ToolArguments):
    """Arguments accepted by the CSR inspection tool."""

    source: str = Field(description="Name or ID of the emulated source container")
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


class PrivateKeyGenerationResult(BaseModel):
    """Result of generating a private key."""

    source: str
    output_path: str
    algorithm: str
    bits: int | None
    curve: str | None
    created_paths: list[str]
    overwritten_paths: list[str]
    successful: bool
    exit_code: int
    stderr: str


class CSRGenerationResult(BaseModel):
    """Result of generating a CSR."""

    source: str
    key_path: str
    output_path: str
    created_paths: list[str]
    overwritten_paths: list[str]
    successful: bool
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
