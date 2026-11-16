"""Serve chat sessions and model configuration without a browser automation runtime."""

import os
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from socialmedia_agent import ToolServiceClient, run_turn

# Load local model settings without replacing explicit process environment values.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

app = FastAPI(title="H17 Social Media Agent")
sessions = {}
sessions_lock = threading.Lock()


def new_client():
    # Docker's default hostname is the container ID prefix accepted by the backend.
    # Do not set a custom hostname on the agent container without setting AGENT_SOURCE.
    return ToolServiceClient(
        os.getenv("TOOL_SERVICE_URL", "http://10.151.0.81:8000/api/v1"),
        {
            "source": os.getenv("AGENT_SOURCE", socket.gethostname()),
        },
    )


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    message: str = Field(min_length=1, max_length=16000)
    max_rounds: int = Field(default=12, ge=1, le=30)


class ModelSettings(BaseModel):
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(default="", max_length=8192, repr=False)
    model: str = Field(min_length=1, max_length=256)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in value)
        ):
            raise ValueError("Expected an HTTP(S) model API base URL")
        return value.rstrip("/")


def model_settings():
    try:
        return ModelSettings(
            base_url=os.getenv("EMUVISTA_LLM_BASE_URL", "").strip(),
            api_key=os.getenv("EMUVISTA_LLM_API_KEY", "").strip(),
            model=os.getenv("EMUVISTA_LLM_MODEL", "").strip(),
        )
    except ValueError as error:
        # Do not return validation details that could contain configuration values.
        raise HTTPException(503, "Check EMUVISTA_LLM_BASE_URL and EMUVISTA_LLM_MODEL in H17/.env") from error


@app.get("/")
def index():
    return FileResponse(Path(__file__).with_name("agent_web.html"))


@app.get("/api/config")
def config():
    client = new_client()
    return {
        "tool_service_url": client.base_url,
        "source": client.bound_arguments["source"],
        "model": model_settings().model,
    }


@app.post("/api/sessions")
def create_session():
    import uuid

    with sessions_lock:
        if len(sessions) >= 32:
            raise HTTPException(
                429, "Close an existing session before creating another"
            )
        session_id = uuid.uuid4().hex
        sessions[session_id] = {"history": [], "lock": threading.Lock()}
    return {"session_id": session_id}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    with sessions_lock:
        session = sessions.get(session_id)
        if session is not None:
            if not session["lock"].acquire(blocking=False):
                raise HTTPException(409, "Wait for the active turn to finish")
            try:
                sessions.pop(session_id)
            finally:
                session["lock"].release()
    return {"deleted": True}


@app.post("/api/chat")
def chat(turn: ChatTurn):
    settings = model_settings()
    with sessions_lock:
        session = sessions.get(turn.session_id)
        if session is None:
            raise HTTPException(404, "Session expired; start a new conversation")
        if not session["lock"].acquire(blocking=False):
            raise HTTPException(409, "This session already has an active turn")
    try:
        return run_turn(
            new_client(),
            session["history"],
            turn.message,
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            max_rounds=turn.max_rounds,
        )
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error
    except Exception as error:
        # Avoid logging raw headers, model credentials or an upstream traceback.
        raise HTTPException(
            502,
            "Request failed; inspect the tool-service and model connection.",
        ) from error
    finally:
        session["lock"].release()
