"""Models for certificate installation PKI tools."""

from pydantic import BaseModel, Field

from ..shared.models import ToolArguments


class PathPairArguments(ToolArguments):
    """Arguments for copying one certificate material file."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    source_path: str = Field(min_length=1, description="Existing source path")
    destination_path: str = Field(
        min_length=1,
        description="Application-specific destination outside Certbot-managed /etc/letsencrypt",
    )
    overwrite: bool = Field(
        default=False,
        description="Allow overwriting a non-symlink application destination",
    )


class BackupCertificateMaterialArguments(ToolArguments):
    """Arguments accepted by the certificate material backup tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    paths: list[str] = Field(min_length=1, description="Paths to back up")
    backup_directory_path: str = Field(
        min_length=1,
        description="Backup directory outside Certbot-managed /etc/letsencrypt",
    )


class RestoreCertificateMaterialArguments(ToolArguments):
    """Arguments accepted by the certificate material restore tool."""

    source: str = Field(description="Node identifier resolved by the execution backend")
    backup_path: str = Field(min_length=1, description="Backup path")
    restore_path: str = Field(
        min_length=1,
        description="Application-specific restore path outside Certbot-managed /etc/letsencrypt",
    )
    overwrite: bool = Field(
        default=False,
        description="Allow overwriting a non-symlink application destination",
    )


class CertificateMaterialOperationResult(BaseModel):
    """Result of installing, backing up, or restoring certificate material."""

    source: str
    successful: bool
    created_paths: list[str] = Field(default_factory=list)
    modified_paths: list[str] = Field(default_factory=list)
    backup_paths: list[str] = Field(default_factory=list)
    exit_code: int
    stderr: str
