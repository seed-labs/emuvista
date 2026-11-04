"""Unit tests for the persistent Qwen domain Agent conversation."""

import copy
import json

import anyio
from pydantic import BaseModel, ConfigDict

from qwen_domain_agent import SYSTEM_PROMPT, QwenDomainAgent, _visible_content
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry


class EchoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


def _registry() -> ToolRegistry:
    async def echo(value: str) -> dict[str, str]:
        return {"value": value}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="domain.echo",
            domain="domain",
            description="Echo a value",
            input_schema=EchoArguments.model_json_schema(),
        ),
        echo,
        EchoArguments,
    )
    return registry


def test_chat_preserves_prior_turns() -> None:
    payloads = []
    responses = iter([
        {"choices": [{"message": {"role": "assistant", "content": "first"}}]},
        {"choices": [{"message": {"role": "assistant", "content": "second"}}]},
    ])

    async def request(url, timeout, payload):
        payloads.append(copy.deepcopy(payload))
        return 200, next(responses), 1.0

    agent = QwenDomainAgent(registry=_registry(), request=request)

    assert anyio.run(agent.chat, "one") == "first"
    assert anyio.run(agent.chat, "two") == "second"
    assert [message["role"] for message in payloads[1]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert payloads[1]["messages"][1]["content"] == "one"


def test_chat_preserves_tool_call_and_result() -> None:
    payloads = []
    responses = iter([
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "domain__echo",
                            "arguments": '{"value": "kept"}',
                        },
                    }],
                }
            }]
        },
        {"choices": [{"message": {"role": "assistant", "content": "done"}}]},
    ])

    async def request(url, timeout, payload):
        payloads.append(copy.deepcopy(payload))
        return 200, next(responses), 1.0

    agent = QwenDomainAgent(registry=_registry(), request=request)

    assert anyio.run(agent.chat, "use the tool") == "done"
    second_messages = payloads[1]["messages"]
    assert second_messages[-2]["tool_calls"][0]["id"] == "call-1"
    assert second_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"value": "kept"}',
    }


def test_reset_discards_history_but_keeps_system_prompt() -> None:
    async def request(url, timeout, payload):
        return 200, {
            "choices": [{"message": {"role": "assistant", "content": "done"}}]
        }, 1.0

    agent = QwenDomainAgent(registry=_registry(), request=request)
    anyio.run(agent.chat, "before reset")

    agent.reset()

    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"


def test_visible_content_hides_textual_tool_call_markup() -> None:
    content = (
        "准备查询。\n"
        '<tool_call>{"name":"domain__echo","arguments":{"value":"x"}}</tool_call>'
    )

    assert _visible_content(content) == "准备查询。"


def test_system_prompt_provides_default_source() -> None:
    assert "as150h-host_1-10.150.0.72" in SYSTEM_PROMPT
    assert "whenever the user does not provide a different source" in SYSTEM_PROMPT


def test_context_compression_omits_old_turns_and_keeps_state() -> None:
    agent = QwenDomainAgent(registry=_registry(), max_context_chars=1_700)
    agent.messages.extend([
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "x" * 1_000},
        {"role": "user", "content": "current request"},
    ])
    agent._remember_state({
        "source": "as150h-host_1-10.150.0.72",
        "session_id": "a" * 32,
    })

    context = agent._context_messages()

    assert [message["role"] for message in context] == ["system", "system", "user"]
    assert context[-1]["content"] == "current request"
    assert "old request" not in json.dumps(context)
    assert "as150h-host_1-10.150.0.72" in context[1]["content"]
    assert "a" * 32 in context[1]["content"]


def test_context_compression_keeps_current_tool_exchange_complete() -> None:
    agent = QwenDomainAgent(registry=_registry(), max_context_chars=1_700)
    agent.messages.extend([
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "x" * 1_000},
        {"role": "user", "content": "current request"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-current",
                "type": "function",
                "function": {"name": "domain__echo", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call-current", "content": "{}"},
    ])

    context = agent._context_messages()

    assert [message["role"] for message in context[-3:]] == ["user", "assistant", "tool"]
    assert context[-2]["tool_calls"][0]["id"] == "call-current"
    assert context[-1]["tool_call_id"] == "call-current"
