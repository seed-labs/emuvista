"""In-memory tool registry."""

import inspect
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import anyio
from pydantic import BaseModel

from seedemu_tool_service.auth.authorization import AccessContext, AccessDenied
from seedemu_tool_service.models.tool import ToolDefinition

logger = logging.getLogger("seedemu.auth.audit")

ToolHandler = Callable[..., Any]


class ToolNotFoundError(LookupError):
    """Raised when a requested tool is not registered."""


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """A tool's agent-visible definition and executable handler."""

    definition: ToolDefinition
    handler: ToolHandler
    arguments_model: type[BaseModel]


class ToolRegistry:
    """Store, discover, and invoke agent-facing tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        arguments_model: type[BaseModel],
    ) -> None:
        """Register a handler and its explicit Pydantic argument model."""

        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if not callable(handler):
            raise TypeError("Tool handler must be callable")

        definition = definition.model_copy(
            update={"input_schema": arguments_model.model_json_schema()}
        )
        self._tools[definition.name] = RegisteredTool(definition, handler, arguments_model)

    def list_tools(self, *, access: AccessContext) -> list[ToolDefinition]:
        """Return registered tools sorted by name."""

        return [
            self._tools[name].definition for name in sorted(self._tools) if access.can_call(name)
        ]

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        access: AccessContext,
    ) -> Any:
        """Authorize validated arguments before invoking any tool handler."""
        invocation_id = uuid.uuid4().hex
        try:
            try:
                registered_tool = self._tools[name]
            except KeyError as error:
                raise ToolNotFoundError(f"Tool not found: {name}") from error
            if not access.can_call(name):
                raise AccessDenied("Tool is not authorized")
            if set(arguments) - set(registered_tool.arguments_model.model_fields):
                raise ValueError("Unexpected tool arguments")
            validated = registered_tool.arguments_model.model_validate(arguments).model_dump()
            authorized = access.authorize(name, validated, registered_tool.arguments_model)
        except AccessDenied:
            self._audit(access, name, invocation_id, "denied")
            raise
        except Exception:
            self._audit(access, name, invocation_id, "invalid")
            raise

        self._audit(access, name, invocation_id, "allowed", authorized)
        try:
            if inspect.iscoroutinefunction(registered_tool.handler):
                result = await registered_tool.handler(**authorized)
            else:
                call = partial(registered_tool.handler, **authorized)
                result = await anyio.to_thread.run_sync(call)
        except Exception:
            self._audit(access, name, invocation_id, "execution_error")
            raise
        outcome = "completed"
        if getattr(result, "successful", None) is False or getattr(result, "exit_code", 0) != 0:
            outcome = "tool_failure"
        self._audit(access, name, invocation_id, outcome, authorized)
        return result

    @staticmethod
    def _audit(
        access: AccessContext,
        tool: str,
        invocation_id: str,
        outcome: str,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        # Never log tokens, raw arguments, certificates or tool output.
        logger.info(
            "tool_access",
            extra={
                "agent_id": access.identity.agent_id,
                "world_id": access.identity.world_id,
                "tool": tool,
                "invocation_id": invocation_id,
                "outcome": outcome,
                "resources": {
                    k: v for k, v in (arguments or {}).items() if k in {"source", "zone", "name"}
                },
            },
        )
