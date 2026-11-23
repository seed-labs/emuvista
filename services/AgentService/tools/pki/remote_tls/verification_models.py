"""Arguments for client-perspective deployment and HTTPS mutual-TLS checks."""

from pydantic import Field, field_validator

from ..shared.models import ToolArguments


class VerifyTLSDeploymentArguments(ToolArguments):
    source: str
    target: str = Field(min_length=1)
    expected_hostname: str = Field(min_length=1)
    expected_fingerprint_sha256: str
    ca_file_path: str = "/etc/ssl/certs/ca-certificates.crt"
    port: int = Field(default=443, ge=1, le=65535)
    timeout_seconds: int = Field(default=5, ge=1, le=15)

    @field_validator("expected_fingerprint_sha256")
    @classmethod
    def fingerprint(cls, value: str) -> str:
        import re

        normalized = value.replace(":", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("Expected a SHA-256 certificate fingerprint")
        return normalized


class TestMTLSConnectionArguments(ToolArguments):
    source: str
    target: str = Field(min_length=1)
    expected_hostname: str = Field(min_length=1, pattern=r"^[A-Za-z0-9.-]+$")
    client_certificate_path: str = Field(min_length=1)
    client_private_key_path: str = Field(min_length=1)
    ca_file_path: str = "/etc/ssl/certs/ca-certificates.crt"
    port: int = Field(default=443, ge=1, le=65535)
    timeout_seconds: int = Field(default=5, ge=1, le=15)
