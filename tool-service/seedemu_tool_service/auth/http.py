"""Authenticate HTTP entry points before REST or MCP dispatch."""

from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from seedemu_tool_service.auth.authentication import (
    AuthenticationError,
    PolicyUnavailable,
    TokenAuthenticator,
)
from seedemu_tool_service.auth.authorization import AccessContext


class FixedTokenMiddleware:
    def __init__(self, app: ASGIApp, authenticator: TokenAuthenticator) -> None:
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        protected = any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in ("/mcp", "/api/v1/tools", "/api/v1/runtime")
        )
        if scope["type"] == "http" and protected:
            try:
                headers = Headers(scope=scope)
                if len(headers.getlist("authorization")) != 1:
                    raise AuthenticationError("One bearer token required")
                access = self.authenticator.from_header(headers.get("authorization"))
                scope.setdefault("state", {})["access"] = access
            except AuthenticationError:
                response = JSONResponse(
                    {"detail": "Valid bearer token required"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
            except PolicyUnavailable:
                await JSONResponse(
                    {"detail": "Access policy unavailable"},
                    status_code=503,
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def get_access_context(request: Request) -> AccessContext:
    return request.state.access
