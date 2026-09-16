"""Compatibility aggregate for DNS-domain tool implementations."""

from seedemu_tool_service.tools.dns.basic.tools import BasicTools
from seedemu_tool_service.tools.dns.diagnostics.tools import DiagnosticTools
from seedemu_tool_service.tools.dns.domain_registration.tools import (
    DomainRegistrationTools,
    RegistrarMetadataError,
)


class DNSTools(DiagnosticTools, DomainRegistrationTools):
    """Backward-compatible aggregate of all DNS tool categories."""

    __init__ = DomainRegistrationTools.__init__


__all__ = [
    "BasicTools",
    "DiagnosticTools",
    "DomainRegistrationTools",
    "DNSTools",
    "RegistrarMetadataError",
]
