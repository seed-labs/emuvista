"""Models for trust-store PKI tools."""

import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

from seedemu_tool_service.tools.pki.shared.models import ToolArguments


class InspectTrustStoreArguments(ToolArguments):
    """Arguments accepted by the trust-store inspection tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    trust_store_path: str = Field(min_length=1, description="Trust-store path")


class CheckCAInstalledArguments(InspectTrustStoreArguments):
    """Arguments accepted by the CA-installed check tool."""

    ca_certificate_path: str = Field(min_length=1, description="CA certificate path")


class RemoveCACertificateArguments(ToolArguments):
    """Arguments accepted by the CA removal tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    ca_certificate_path: str = Field(min_length=1, description="Installed CA certificate path")
    expected_fingerprint_sha256: str = Field(
        description="Expected SHA-256 fingerprint of the CA certificate being removed"
    )

    @field_validator("ca_certificate_path")
    @classmethod
    def approved_ca_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.parent != PurePosixPath("/usr/local/share/ca-certificates")
            or not path.name.endswith(".crt")
        ):
            raise ValueError(
                "Only .crt files in /usr/local/share/ca-certificates may be removed"
            )
        return str(path)

    @field_validator("expected_fingerprint_sha256")
    @classmethod
    def valid_fingerprint(cls, value: str) -> str:
        normalized = re.sub(r"[:\s]", "", value).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("expected_fingerprint_sha256 must be a SHA-256 fingerprint")
        return normalized


class UpdateTrustStoreArguments(ToolArguments):
    """Arguments accepted by the trust-store update tool."""

    source: str = Field(description="Name or ID of the emulated source container")


class TrustStoreInspectionResult(BaseModel):
    """Result of inspecting a trust-store path."""

    source: str
    trust_store_path: str
    successful: bool
    entries: list[str]
    exit_code: int
    stderr: str


class CAInstalledResult(BaseModel):
    """Result of checking whether a CA is trusted."""

    source: str
    ca_certificate_path: str
    installed: bool
    output: str
    exit_code: int
    stderr: str


class TrustStoreMutationResult(BaseModel):
    """Result of modifying trust-store state."""

    source: str
    successful: bool
    modified_paths: list[str] = Field(default_factory=list)
    removed_paths: list[str] = Field(default_factory=list)
    output: str
    exit_code: int
    stderr: str
