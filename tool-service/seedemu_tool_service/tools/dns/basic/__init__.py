"""Basic DNS tools."""

from seedemu_tool_service.tools.dns.basic.registration import register_basic_tools
from seedemu_tool_service.tools.dns.basic.tools import BasicTools

__all__ = ["register_basic_tools", "BasicTools"]
