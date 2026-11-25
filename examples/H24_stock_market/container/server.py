#!/usr/bin/env python3
"""Serve the H24 dashboard and proxy public market reads to Stock Service."""

from __future__ import annotations

import mimetypes
import os
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from urllib.parse import parse_qs, urlsplit


STATIC = Path("/app/static")
API_URL = os.environ["STOCK_API_URL"].rstrip("/")
DEMO_CONTROL_URL = os.environ["DEMO_CONTROL_URL"].rstrip("/")
TLS = ssl.create_default_context(cafile="/app/server.crt")
TLS.check_hostname = False  # trust the exact certificate bundled with this H24 deployment
UPSTREAM = build_opener(ProxyHandler({}), HTTPSHandler(context=TLS))
ASSETS = {"app.js", "styles.css"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        route = parsed.path
        if route == "/":
            query = parse_qs(parsed.query)
            if query.get("live") != ["1"] or "symbol" not in query:
                self.send_response(302)
                self.send_header("Location", "/?live=1&symbol=AMZ")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_file(STATIC / "index.html")
        elif route.startswith("/api/v1/market/"):
            symbol = route.removeprefix("/api/v1/market/")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,16}", symbol):
                self.send_error(400)
                return
            self.proxy_market(symbol)
        elif route == "/api/v1/demo/status":
            self.proxy_demo("GET", route)
        elif route.startswith("/assets/") and route.removeprefix("/assets/") in ASSETS:
            self.send_file(STATIC / route.removeprefix("/assets/"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if urlsplit(self.path).path == "/api/v1/demo/start":
            self.proxy_demo("POST", "/api/v1/demo/start")
        else:
            self.send_error(404)

    def proxy_demo(self, method: str, route: str) -> None:
        outgoing = Request(DEMO_CONTROL_URL + route, data=b"{}" if method == "POST" else None,
                           headers={"Accept": "application/json", "Content-Type": "application/json"},
                           method=method)
        try:
            with UPSTREAM.open(outgoing, timeout=10) as response:
                body = response.read(1024 * 1024)
                code = response.status
        except HTTPError as error:
            body = error.read(8192)
            code = error.code
        except (OSError, URLError, TimeoutError):
            body = b'{"detail":"H24 demo controller is not ready"}'
            code = 503
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def proxy_market(self, symbol: str) -> None:
        request = Request(API_URL + "/api/v1/market/" + symbol,
                          headers={"Accept": "application/json", "Cache-Control": "no-cache"})
        try:
            with UPSTREAM.open(request, timeout=10) as response:
                body = response.read(1024 * 1024)
                self.send_response(response.status)
        except HTTPError as error:
            body = error.read(8192)
            self.send_response(error.code)
        except (OSError, URLError, TimeoutError):
            body = b'{"detail":"Stock Service is not available yet"}'
            self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        body = path.read_bytes()
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith(("text/", "application/javascript")) and "charset=" not in kind:
            kind += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


ThreadingHTTPServer(("0.0.0.0", 8765), Handler).serve_forever()
