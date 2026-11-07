"""Execution contract shared by PKI tools; agents execute only in their own node."""

import subprocess
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel


class RuntimeCommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class RuntimeStatus(BaseModel):
    backend: str
    available: bool


class RuntimeBackend(Protocol):
    def execute(self, source: str, command: Sequence[str]) -> RuntimeCommandResult:
        """Execute an argument vector at a source resolved by this backend."""
        ...


class LocalBackend:
    """Run as the current agent user, without Docker access or privilege escalation."""

    def __init__(self, identity: str):
        self.identity = identity

    def execute(self, source: str, command: Sequence[str]) -> RuntimeCommandResult:
        if source not in {'local', self.identity}:
            raise PermissionError('PKI tools can execute only in the current agent node')
        try:
            result = subprocess.run(
                list(command), stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=120,
            )
        except FileNotFoundError:
            return RuntimeCommandResult(exit_code=127, stdout='', stderr='Required program is not installed')
        except subprocess.TimeoutExpired:
            return RuntimeCommandResult(exit_code=124, stdout='', stderr='PKI command timed out')
        return RuntimeCommandResult(
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
        )
