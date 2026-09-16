"""Diagnostics DNS tools."""

from seedemu_tool_service.tools.dns.diagnostics.registration import register_diagnostics_tools
from seedemu_tool_service.tools.dns.diagnostics.tools import DiagnosticTools

__all__ = ["register_diagnostics_tools", "DiagnosticTools"]
