"""Agent-facing chat arguments and results; runtime state stays internal."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatLoginArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1, pattern=r"^[^:\r\n]+$",
        description="登录账号",
    )
    password: str = Field(
        min_length=1, repr=False, json_schema_extra={"writeOnly": True},
        description="登录密码",
    )


class ChatLoginResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful: bool = Field(description="是否登录成功")
    message: str = Field(min_length=1, description="登录结果说明或失败原因")


class ChatSendArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, description="账号名、联系人名称、实际用户 ID 或已有群 ID")
    content: str = Field(min_length=1, max_length=4000, description="发送的文本内容")


class ChatReceiveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str | None = Field(
        default=None, min_length=1,
        description="可选的账号名、联系人名称、用户 ID 或群 ID；不填则收取已有会话的消息",
    )
    limit: int = Field(default=50, ge=1, le=100, description="本次最多收取多少条消息")


class ChatSendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful: bool
    message: str
    status: Literal["sent", "failed", "unknown"] = Field(
        description="sent 表示服务端接受；unknown 表示尚不能确认，避免立即重复发送",
    )
    message_id: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    sender: str
    target: str
    content: str
    timestamp: str | None = None


class ChatReceiveResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful: bool
    message: str
    messages: list[ChatMessage] = Field(default_factory=list)
