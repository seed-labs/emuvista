"""Agent web backend for the colocated browser."""

import asyncio
import json
import os
import tempfile
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import domain_agent as domain
from browser_runtime.control import connection_config, request_sync
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from local_tools.browser.tools import BrowserSession
from pydantic import BaseModel, Field, ValidationError, field_validator

app = FastAPI(title="SeedEmu Agent Chat")
PROFILES_FILE = Path("/opt/agent-config/model_profiles.json") if Path("/opt/agent-config").is_dir() else Path(__file__).with_name("model_profiles.json")


# Validate the model URL and key from the frontend; configuration can change each turn.
class APIConfig(BaseModel):
    api_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(default="", max_length=8192, repr=False)

    @field_validator("api_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请填写 HTTP(S) API 基础地址")
        return value


class ModelProfile(APIConfig):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=80)
    model: str = Field(default="", max_length=256)
    max_context_chars: int = Field(default=40960, ge=8192, le=2000000)


class ProfileStore(BaseModel):
    profiles: list[ModelProfile] = Field(default_factory=list, max_length=100)
    activeProfile: str | None = None


class ChatTurn(APIConfig):
    max_context_chars: int = Field(default=40960, ge=8192, le=2000000)

    message: str = Field(min_length=1, max_length=32000)
    model: str = Field(min_length=1, max_length=256)


@app.get("/")
async def index():
    return FileResponse(Path(__file__).with_name("agent_web.html"))


@app.get("/agent_web.js")
async def javascript():
    return FileResponse(Path(__file__).with_name("agent_web.js"))


class ModelConnectionCheck(APIConfig):
    model: str = Field(min_length=1, max_length=256)


@app.post("/api/test-model")
async def test_model(config: ModelConnectionCheck, x_agent_local: str = Header(default="")):
    """Call the current model once without creating an agent, running tools, or writing chat history."""
    if x_agent_local != "1":
        raise HTTPException(403, "仅供本地页面使用")
    try:
        status, body, elapsed = await asyncio.to_thread(
            domain.request_json, domain.api_url(config.api_url, "chat/completions"), 30,
            {"model": config.model, "messages": [{"role": "user", "content": "Reply with OK."}]},
            api_key=config.api_key,
        )
    except (OSError, ValueError):
        return {"ok": False, "message": "连接失败或超时，请检查 URL、网络及服务状态。"}
    result = {"ok": False, "status": status, "elapsed_ms": round(elapsed)}
    if not 200 <= status < 300:
        # Return only a status and fixed explanation to avoid exposing model keys in upstream error bodies.
        reasons = {401: "API Key 无效或未授权", 403: "无访问权限", 404: "接口路径或模型不存在",
                   429: "请求限流或额度不足"}
        result["message"] = reasons.get(status, "模型服务拒绝请求或发生错误")
    elif not isinstance(body, dict) or not body.get("choices") or not isinstance(body["choices"][0], dict) or not isinstance(body["choices"][0].get("message"), dict):
        result["message"] = "服务已响应，但返回格式不符合聊天接口协议"
    else:
        result.update(ok=True, message="模型连接成功")
    return result


@app.post("/api/models")
async def models(config: APIConfig):
    try:
        status, body, _ = await asyncio.to_thread(
            domain.request_json,
            domain.api_url(config.api_url, "models"),
            15,
            api_key=config.api_key,
        )
        if not 200 <= status < 300:
            raise ValueError(f"模型服务返回 HTTP {status}")
        ids = [
            item["id"]
            for item in body["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return {"models": ids, "default": domain.DEFAULT_MODEL}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(502, "无法获取模型列表，请检查后端模型 API 配置") from error


@app.post("/api/profiles")
async def read_profiles(x_agent_local: str = Header(default="")):
    if x_agent_local != "1":
        raise HTTPException(403, "仅供本地页面使用")
    try:
        data = ProfileStore.model_validate_json(PROFILES_FILE.read_text()).model_dump()
    except FileNotFoundError:
        data = {"profiles": [], "activeProfile": None, "missing": True}
    except (OSError, ValueError) as error:
        raise HTTPException(500, "本机配置列表读取失败") from error
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.put("/api/profiles")
# Write a temporary file and replace atomically to avoid corrupting model profiles if saving is interrupted.
async def write_profiles(data: ProfileStore, x_agent_local: str = Header(default="")):
    if x_agent_local != "1":
        raise HTTPException(403, "仅供本地页面使用")
    temporary = None
    try:
        # Atomic replacement; mkstemp creates a file readable only by its owner.
        fd, temporary = tempfile.mkstemp(dir=PROFILES_FILE.parent, prefix=".profiles-")
        with os.fdopen(fd, "w") as stream:
            stream.write(data.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        # Preserve host ownership so later builds can read the profiles.
        if os.geteuid() == 0:
            owner = PROFILES_FILE.stat() if PROFILES_FILE.exists() else PROFILES_FILE.parent.stat()
            os.chown(temporary, owner.st_uid, owner.st_gid)
        os.replace(temporary, PROFILES_FILE)
    except OSError as error:
        raise HTTPException(500, "本机配置保存失败") from error
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return {"saved": True}


browser_sessions = {}


def same_origin(ws):
    return ws.headers.get("origin", "") in {
        f"http://{ws.headers.get('host')}",
        f"https://{ws.headers.get('host')}",
    }


@app.get("/browser/viewer")
async def browser_viewer():
    return FileResponse(Path(__file__).with_name("browser_viewer.html"))


@app.get("/browser/novnc/{asset:path}")
async def novnc_asset(asset: str):
    if ".." in asset.split("/") or not asset.endswith((".js", ".css", ".svg", ".png")):
        raise HTTPException(404)
    try:
        status, body, headers = await asyncio.to_thread(request_sync, "GET", "/novnc/" + asset)
    except (OSError, RuntimeError):
        raise HTTPException(503, "本容器浏览器服务不可达，请重启 browser-agent 容器") from None
    return Response(
        body, status_code=status, media_type=headers.get("content-type", "application/javascript")
    )


@app.websocket("/browser/vnc")
# Bridge the web WebSocket to the remote VNC connection to stream the desktop.
async def browser_vnc(ws: WebSocket):
    session = browser_sessions.get(ws.query_params.get("token"))
    if not same_origin(ws) or not session or not session.connected:
        await ws.close(code=1008)
        return
    config = connection_config()
    port = config["view_port"]
    try:
        reader, writer = await asyncio.open_connection(config["vnc_host"], port)
    except OSError:
        await ws.close(code=1013)
        return
    await ws.accept()
    session.viewers.add(ws)
    if not session.connected:
        writer.close()
        session.viewers.discard(ws)
        await ws.close(code=1000)
        return

    async def upstream():
        while True:
            writer.write(await ws.receive_bytes())
            await writer.drain()

    async def downstream():
        while data := await reader.read(65536):
            await ws.send_bytes(data)

    tasks = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        session.viewers.discard(ws)
        writer.close()
        await writer.wait_closed()
        with suppress(Exception):
            await ws.close()


@app.websocket("/ws")
# Each chat connection owns an agent and browser session; release all resources on disconnect.
async def conversation(ws: WebSocket):
    if not same_origin(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    browser = BrowserSession()
    browser_sessions[browser.owner] = browser
    task = None
    agent = None

    async def progress(text: str):
        await ws.send_json({"type": "progress", "text": text})

    async def tool_event(event):
        await ws.send_json(event)
        if browser.connected:
            await ws.send_json(browser.status())

    async def chat(turn):
        nonlocal agent
        try:
            if agent is None:
                agent = domain.QwenDomainAgent(
                    model=turn.model,
                    browser=browser,
                    on_event=progress,
                    on_tool_event=tool_event,
                )
            agent.api_base_url = turn.api_url
            agent.request = partial(domain.request_json, api_key=turn.api_key)
            agent.max_context_chars = turn.max_context_chars
            agent.model = turn.model
            answer = await agent.chat(turn.message)
            await ws.send_json({"type": "answer", "text": answer})
        except (ValidationError, ValueError):
            await ws.send_json(
                {"type": "error", "text": "输入无效，请检查指令、模型、上下文预算。"}
            )
        except Exception:
            await ws.send_json(
                {
                    "type": "error",
                    "text": "本轮执行失败，可能已有部分操作完成。"
                    "请先观察页面确认状态，勿重复购买或付款。",
                }
            )

    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type") if isinstance(data, dict) else None
            if kind in {"browser_connect", "browser_close"}:
                try:
                    if kind == "browser_connect":
                        result = await browser.connect()
                    else:
                        if task and not task.done():
                            raise ValueError("任务执行中不能关闭浏览器；请等待本轮结束")
                        await browser.close()
                        result = browser.status()
                    await ws.send_json(result)
                except Exception as error:
                    await ws.send_json({"type": "browser_error", "text": str(error)[:800]})
                continue
            if task and not task.done():
                await ws.send_json(
                    {"type": "notice", "text": "本轮仍在执行，请等待本轮结束。"}
                )
                continue
            if kind == "reset":
                was_connected = browser.connected
                await browser.close()
                agent = None
                if was_connected:
                    await ws.send_json(browser.status())
                await ws.send_json({"type": "reset"})
                continue
            try:
                turn = ChatTurn.model_validate(data)
                if not turn.message.strip() or not turn.model.strip():
                    raise ValueError("指令和模型不能为空")
            except (ValidationError, ValueError):
                await ws.send_json(
                    {"type": "error", "text": "输入无效，请检查指令、模型、上下文预算。"}
                )
                continue
            task = asyncio.create_task(chat(turn))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        browser_sessions.pop(browser.owner, None)
        with suppress(Exception):
            await browser.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8089, ws_max_size=8 * 1024 * 1024, access_log=False)
