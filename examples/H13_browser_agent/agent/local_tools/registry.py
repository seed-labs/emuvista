"""Local function definitions, validation and dispatch; no tool-service dependency."""

import asyncio
import inspect
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from pydantic import BaseModel


@dataclass
class ToolDefinition:
    name: str
    domain: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


# Register tools locally; validate arguments with Pydantic before calling handlers.
class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, definition, handler, arguments_model):
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if not issubclass(arguments_model, BaseModel):
            raise TypeError("Tool arguments must use a Pydantic model")
        definition.input_schema = arguments_model.model_json_schema()
        self._tools[definition.name] = (definition, handler, arguments_model)

    def list_tools(self):
        return [self._tools[name][0] for name in sorted(self._tools)]

    async def invoke(self, name, arguments):
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        _, handler, model = self._tools[name]
        validated = model.model_validate(arguments).model_dump()
        if inspect.iscoroutinefunction(handler):
            return await handler(**validated)
        # Run synchronous tools in worker threads to avoid blocking asynchronous chat and browser connections.
        return await asyncio.to_thread(partial(handler, **validated))
