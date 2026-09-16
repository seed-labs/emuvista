"""Domain Registration DNS tools."""

from seedemu_tool_service.tools.dns.domain_registration.registration import (
    register_domain_registration_tools,
)
from seedemu_tool_service.tools.dns.domain_registration.tools import DomainRegistrationTools

__all__ = ["register_domain_registration_tools", "DomainRegistrationTools"]
