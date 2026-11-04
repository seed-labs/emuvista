"""Tool dispatch, per-container execution and structured results."""

import json
import re
import sqlite3
from pathlib import Path
from threading import RLock

from pydantic import ValidationError
from seedemu_tool_service.backends import RuntimeBackendError
from .tools.support.session import get_session_manager
from .tools.support.tool_models import (
    ChatLoginArguments, ChatLoginResult, ChatSendArguments, ChatSendResult,
    ChatReceiveArguments, ChatReceiveResult,
)


class ToolExecutionError(Exception):
    """A launcher failure; dispatched means the container may have acted."""

    def __init__(self, message: str, *, dispatched: bool = False) -> None:
        super().__init__(message)
        self.dispatched = dispatched


class _ContainerTools:
    """One internal container session, retained by ChatSessionManager."""

    def __init__(self, manager, container: str) -> None:
        self._manager = manager
        self._backend = manager.backend
        self._source = container
        self._timeout_seconds = manager.timeout_seconds
        self._binding = None
        self._receipt = None
        self._server = None
        self._lock = RLock()

    def login(self, username: str, password: str) -> ChatLoginResult:
        """Validate credentials, run login, and retain the account binding."""
        with self._lock:
            # A failed account switch must not fall back to the previous user.
            self._binding = "login-required"
            self._receipt = None
            self._server = None
            try:
                arguments = ChatLoginArguments(username=username, password=password)
            except ValidationError:
                return ChatLoginResult(successful=False, message="参数不正确，请检查填写的内容。")

            try:
                reply = self._execute("login", arguments.model_dump())
            except ToolExecutionError as error:
                return ChatLoginResult(successful=False, message=str(error))

            binding = reply.pop("_binding", None)
            try:
                result = ChatLoginResult.model_validate(reply)
            except ValidationError:
                return ChatLoginResult(successful=False, message="未能确认登录结果，请稍后检查。")
            if result.successful:
                self._binding = binding or self._binding
            return result

    def send_message(self, target: str, content: str) -> ChatSendResult:
        """Resolve the recipient and send; never retry an uncertain send."""
        with self._lock:
            try:
                arguments = ChatSendArguments(target=target, content=content)
            except ValidationError:
                return ChatSendResult(successful=False, message="参数不正确，请检查填写的内容。", status="failed")
            try:
                payload = arguments.model_dump()
                payload["target"] = self._resolve_target(arguments.target)
                reply = self._execute("send_message", payload)
            except ToolExecutionError as error:
                if error.dispatched:
                    return ChatSendResult(
                        successful=False, status="unknown",
                        message="尚未确认发送结果，请检查聊天记录后再决定是否重试。",
                    )
                return ChatSendResult(successful=False, message=str(error), status="failed")

            binding = reply.pop("_binding", None)
            try:
                result = ChatSendResult.model_validate(reply)
            except ValidationError:
                return ChatSendResult(
                    successful=False, status="unknown",
                    message="尚未确认发送结果，请检查聊天记录后再决定是否重试。",
                )
            if result.successful:
                self._binding = binding or self._binding
            return result

    def receive_messages(self, target: str | None = None, limit: int = 50) -> ChatReceiveResult:
        """Receive a batch, keeping its receipt for the next receive call."""
        with self._lock:
            try:
                arguments = ChatReceiveArguments(target=target, limit=limit)
            except ValidationError:
                return ChatReceiveResult(successful=False, message="参数不正确，请检查填写的内容。")
            try:
                payload = arguments.model_dump()
                if arguments.target is not None:
                    payload["target"] = self._resolve_target(arguments.target)
                payload["_ack"] = self._receipt
                reply = self._execute("receive_messages", payload)
            except ToolExecutionError as error:
                return ChatReceiveResult(successful=False, message=str(error))

            binding = reply.pop("_binding", None)
            receipt = reply.pop("_receipt", None)
            try:
                result = ChatReceiveResult.model_validate(reply)
            except ValidationError:
                return ChatReceiveResult(successful=False, message="未能确认收件结果，请稍后检查。")
            if result.successful:
                self._binding = binding or self._binding
                for message in result.messages:
                    message.sender = self._manager.display_name(self._server, message.sender)
                    message.target = self._manager.display_name(self._server, message.target)
                self._receipt = receipt
            return result

    def _resolve_target(self, target: str) -> str:
        target = target.strip()
        if re.fullmatch(r"(?:usr|grp)[A-Za-z0-9_-]+", target):
            return target
        if self._server is None:
            # Recover identity from the container after a host process restart.
            try:
                context = self._execute("_context", {})
            except ToolExecutionError as error:
                # No send has been attempted during contact resolution.
                raise ToolExecutionError(str(error)) from error
            if not context.get("successful"):
                raise ToolExecutionError(context.get("message", "请先登录聊天服务。"))
        try:
            return self._manager.resolve_contact(self._server, target)
        except ValueError as error:
            raise ToolExecutionError(str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise ToolExecutionError("聊天联系人目录暂时不可用。") from error

    @staticmethod
    def _load_script(operation: str) -> str:
        directory = Path(__file__).parent / "tools" / "support"
        try:
            runtime = (directory / "runtime.py").read_text(encoding="utf-8")
            methods = "\n".join(
                (directory.parent / "script" / (name + ".py")).read_text(encoding="utf-8")
                for name in ("login", "send_message", "receive_messages")
            )
        except OSError as error:
            raise ToolExecutionError("聊天工具暂时不可用。") from error
        # The persistent worker needs all three methods, whichever starts it.
        bundle = runtime + "\n" + methods
        return bundle + "\n_RUNTIME_SOURCE = " + repr(bundle) + "\ntool_main(" + repr(operation) + ")\n"

    def _execute(self, operation: str, payload: dict) -> dict:
        """Run a script through backend and decode JSON, without tool branching."""
        script = self._load_script(operation)
        payload = dict(payload, _timeout=self._timeout_seconds, _binding=self._binding)
        try:
            command_result = self._backend.execute(self._source, [
                "timeout", str(self._timeout_seconds + 25), "python3", "-c", script,
                json.dumps(payload, ensure_ascii=False),
            ])
        except RuntimeBackendError as error:
            raise ToolExecutionError(
                "聊天环境暂时不可用，请稍后重试。", dispatched=True,
            ) from error
        if command_result.exit_code != 0:
            raise ToolExecutionError("操作未完成，请稍后重试。", dispatched=True)
        try:
            reply = json.loads(command_result.stdout)
            if not isinstance(reply, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, TypeError) as error:
            raise ToolExecutionError("未能确认操作结果，请稍后检查。", dispatched=True) from error
        identity = reply.pop("_identity", None)
        if reply.get("successful"):
            try:
                self._server = self._manager.remember_identity(identity)
            except (ValueError, OSError, sqlite3.Error) as error:
                raise ToolExecutionError("无法保存聊天账号信息，请检查服务状态目录或客户端版本。", dispatched=True) from error
        return reply


# The public dispatcher only selects a tool; each tool keeps its own workflow.
_TOOL_MODELS = {
    "login": ChatLoginArguments,
    "send_message": ChatSendArguments,
    "receive_messages": ChatReceiveArguments,
}


def execute_tool(tool_name: str, container: str, arguments: dict | None = None) -> dict:
    """NetworkBlock entrypoint: tool name + container + business arguments."""
    model = _TOOL_MODELS.get(tool_name) if isinstance(tool_name, str) else None
    if model is None:
        return {"successful": False, "message": "不支持的聊天工具。"}
    if not isinstance(container, str) or not container.strip():
        return _request_failure(tool_name, "请提供有效的客户端容器名称或 ID。")
    if arguments is not None and not isinstance(arguments, dict):
        return _request_failure(tool_name, "工具参数必须是对象。")
    try:
        values = model.model_validate(arguments if arguments is not None else {})
    except ValidationError:
        return _request_failure(tool_name, "参数不正确，请检查填写的内容。")
    try:
        manager = get_session_manager()
        session = manager.session(container.strip())
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return _request_failure(tool_name, "聊天服务配置或状态目录不可用。")
    # Only names in _TOOL_MODELS can reach this getattr.
    result = getattr(session, tool_name)(**values.model_dump())
    return result.model_dump(mode="json")


def _request_failure(tool_name, message):
    result = {"successful": False, "message": message}
    if tool_name == "send_message":
        return ChatSendResult(**result, status="failed").model_dump(mode="json")
    if tool_name == "receive_messages":
        return ChatReceiveResult(**result).model_dump(mode="json")
    return ChatLoginResult(**result).model_dump(mode="json")


__all__ = ["execute_tool"]
