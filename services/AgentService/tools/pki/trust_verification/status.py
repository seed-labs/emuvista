"""Explicit CRL verification; never infer revocation from an ACME command result."""

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..execution import RuntimeBackend
from ..shared.models import ToolArguments


class CheckCertificateStatusArguments(ToolArguments):
    source: str
    certificate_path: str = Field(min_length=1)
    ca_file_path: str = Field(min_length=1)
    crl_path: str = Field(min_length=1)
    intermediate_chain_path: str | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class CertificateStatusResult(BaseModel):
    source: str
    successful: bool
    status: Literal["not_revoked", "revoked", "unknown"]
    status_source: Literal["provided_crl"] = "provided_crl"
    scope: Literal["leaf_certificate"] = "leaf_certificate"
    crl_path: str
    exit_code: int
    verification_errors: list[int] = Field(default_factory=list)


class CertificateStatusTools:
    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def check_certificate_status(
        self,
        source: str,
        certificate_path: str,
        ca_file_path: str,
        crl_path: str,
        intermediate_chain_path: str | None,
        timeout_seconds: int,
    ) -> CertificateStatusResult:
        command = [
            "timeout",
            str(timeout_seconds),
            "openssl",
            "verify",
            "-CAfile",
            ca_file_path,
            "-CRLfile",
            crl_path,
            "-crl_check",
        ]
        if intermediate_chain_path:
            command.extend(["-untrusted", intermediate_chain_path])
        command.append(certificate_path)
        result = self._backend.execute(source, command)
        errors = [
            int(value)
            for value in re.findall(
                r"error (\d+) at \d+ depth", result.stdout + "\n" + result.stderr
            )
        ]
        status = "unknown"
        if result.exit_code == 0:
            status = "not_revoked"
        elif result.exit_code != 124 and errors and set(errors) == {23}:
            status = "revoked"
        return CertificateStatusResult(
            source=source,
            successful=status != "unknown",
            status=status,
            crl_path=crl_path,
            exit_code=result.exit_code,
            verification_errors=errors,
        )
