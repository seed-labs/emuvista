"""Explicit test-only access for legacy tool implementation tests.

These tests exercise command construction, not service authorization. Security tests
must import the production ToolRegistry and use real AccessContext instances.
"""

from types import SimpleNamespace

from seedemu_tool_service.registry import ToolRegistry as ProductionRegistry


class ImplementationTestAccess:
    identity = SimpleNamespace(agent_id="unit-test", world_id="unit-test")

    def can_call(self, tool):
        return True

    def authorize(self, tool, arguments, arguments_model):
        return arguments


TEST_ACCESS = ImplementationTestAccess()


class ToolRegistry(ProductionRegistry):
    def list_tools(self, *, access=TEST_ACCESS):
        return super().list_tools(access=access)

    async def invoke(self, name, arguments, *, access=TEST_ACCESS):
        return await super().invoke(name, arguments, access=access)
