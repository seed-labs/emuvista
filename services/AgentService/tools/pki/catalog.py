"""In-process PKI bindings and validation, independent of a server or framework."""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    domain: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: Callable
    arguments_model: type[BaseModel]


class Catalog:
    def __init__(self):
        self._tools = {}

    def register(self, definition, handler, arguments_model):
        if definition.name in self._tools:
            raise ValueError('Tool already registered: '+definition.name)
        definition = definition.model_copy(update={
            'input_schema': arguments_model.model_json_schema(),
        })
        self._tools[definition.name] = RegisteredTool(definition, handler, arguments_model)

    def list_tools(self):
        return [tool.definition for _, tool in sorted(self._tools.items())]

    def call(self, name, arguments):
        tool = self._tools[name]
        validated = tool.arguments_model.model_validate(arguments).model_dump()
        return tool.handler(**validated)

    async def invoke(self, name, arguments):
        return await asyncio.to_thread(self.call, name, arguments)


def agent_manifest(catalog):
    """Project schemas into AgentService's subset; handlers retain full validation.

    Optional nullable arguments should be omitted to use their model defaults.
    The source is always injected by the agent handler, never chosen by the LLM.
    """
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items',
                 'description', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'}

    def project(schema):
        if 'anyOf' in schema:
            schema = next(item for item in schema['anyOf'] if item.get('type') != 'null')
        result = {key: value for key, value in schema.items() if key in supported}
        if 'properties' in result:
            result['properties'] = {key: project(value) for key, value in result['properties'].items()}
        if 'items' in result:
            result['items'] = project(result['items'])
        return result

    definitions = []
    for definition in catalog.list_tools():
        schema = project(definition.input_schema)
        schema['properties'].pop('source', None)
        schema['required'] = [key for key in schema.get('required', []) if key != 'source']
        definitions.append({
            'name': definition.name, 'description': definition.description,
            'handler': 'handlers:'+definition.name.split('.')[1], 'input_schema': schema,
        })
    return definitions
