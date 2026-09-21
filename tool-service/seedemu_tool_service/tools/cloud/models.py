"""Validated argument and result contracts for cloud-storage tools."""

import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _safe_identifier(value: str, field: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{field} must be one non-empty token")
    if any(character in value for character in "/\\\x00"):
        raise ValueError(f"{field} contains unsupported characters")
    return value


def _validate_path(value: str) -> str:
    if not value.startswith("/") or "\x00" in value or len(value) > 512:
        raise ValueError("path must be an absolute, bounded file path")
    parts = value.split("/")
    if any(part in {".", ".."} for part in parts):
        raise ValueError("path must not contain dot segments")
    return value


class CloudStorageFindArguments(ToolArguments):
    source: str = Field(description="Authorized emulated client container")

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        return _safe_identifier(value, "source")


class CloudServiceLocation(BaseModel):
    service_id: str
    provider: Literal["nextcloud"]
    webdav_url: str
    ocs_url: str
    credential_ref: str


class CloudStorageFindResult(BaseModel):
    source: str
    services: list[CloudServiceLocation] = Field(default_factory=list)
    next_step: str = (
        "Select service_id, then invoke cloud.file_upload, cloud.file_share, or "
        "cloud.file_download from an authorized source."
    )


class CloudOperationArguments(ToolArguments):
    source: str
    service_id: str

    @field_validator("source", "service_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _safe_identifier(value, info.field_name)


class FileUploadArguments(CloudOperationArguments):
    path: str
    content_base64: str = Field(max_length=349528)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_path(value)

    @field_validator("content_base64")
    @classmethod
    def validate_content(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("content_base64 must be valid base64") from error
        if len(decoded) > 256 * 1024:
            raise ValueError("decoded content must not exceed 256 KiB")
        return value


class FileDownloadArguments(CloudOperationArguments):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_path(value)


class FileShareArguments(CloudOperationArguments):
    path: str
    recipient: str = Field(pattern=r"^[A-Za-z0-9_.@-]{1,128}$")
    permission: Literal["read"] = "read"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_path(value)


class CloudOperationResult(BaseModel):
    source: str
    service_id: str
    path: str
    successful: bool
    exit_code: int
    http_status: int | None = None
    stderr: str = ""


class FileUploadResult(CloudOperationResult):
    bytes_uploaded: int
    sha256: str


class FileDownloadResult(CloudOperationResult):
    content_base64: str = ""
    bytes_downloaded: int = 0
    sha256: str | None = None


class FileShareResult(CloudOperationResult):
    recipient: str
    share_id: str | None = None
    ocs_status: str | None = None
