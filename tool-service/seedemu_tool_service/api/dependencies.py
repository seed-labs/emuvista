"""Dependencies shared by API routes."""

from functools import lru_cache

from seedemu_tool_service.backends import DockerRuntimeBackend, RuntimeBackend
from seedemu_tool_service.registry.registry import ToolRegistry
from seedemu_tool_service.tools.benchmark import register_benchmark_tools
from seedemu_tool_service.tools.bgp import register_bgp_tools
from seedemu_tool_service.tools.cloud import register_cloud_tools
from seedemu_tool_service.tools.dns import register_dns_tools
from seedemu_tool_service.tools.network import register_network_tools
from seedemu_tool_service.tools.pki import register_pki_tools


@lru_cache
def get_runtime_backend() -> RuntimeBackend:
    """Return the configured runtime backend."""

    return DockerRuntimeBackend()


def create_tool_registry() -> ToolRegistry:
    """Build the registry and load each tool domain."""

    registry = ToolRegistry()
    backend = get_runtime_backend()
    register_benchmark_tools(registry, backend)
    register_bgp_tools(registry, backend)
    register_cloud_tools(registry, backend)
    register_dns_tools(registry, backend)
    register_network_tools(registry, backend)
    register_pki_tools(registry, backend)
    return registry


_tool_registry = create_tool_registry()


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide tool registry."""

    return _tool_registry
