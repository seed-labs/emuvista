"""Shared argument and result models for PKI-domain tools."""

from pydantic import BaseModel, ConfigDict


class ToolArguments(BaseModel):
    """Base model for strict PKI tool argument validation."""

    model_config = ConfigDict(extra="forbid")


class CertificateFields(BaseModel):
    """Common parsed X.509 certificate fields."""

    subject: str | None = None
    issuer: str | None = None
    serial: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    fingerprint_sha256: str | None = None
