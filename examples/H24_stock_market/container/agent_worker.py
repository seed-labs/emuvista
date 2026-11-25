#!/usr/bin/env python3
"""One H24 stock agent running with its own credentials on its own SEED node."""

from __future__ import annotations

import json
import os
import ssl
import time
import uuid
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import (HTTPSHandler, ProxyHandler, Request, build_opener,
                            urlopen)


NAME = os.environ["AGENT_NAME"]
STOCK_API_URL = os.environ["STOCK_API_URL"].rstrip("/")
CONTROL_TOKEN = os.environ["AGENT_CONTROL_TOKEN"]
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
SYMBOL = "AMZ"
DEMO_STOCK_CASH = Decimal(os.environ["H24_DEMO_STOCK_CASH"])
TLS = ssl.create_default_context(cafile="/app/server.crt")
TLS.check_hostname = False
STOCK_HTTP = build_opener(ProxyHandler({}), HTTPSHandler(context=TLS))
AGENT: dict | None = None

ASSIGNMENTS = {
    "Alice": ("SELL", "Choose a limit price for selling your one AMZ share. Use the real quote and your "
                      "acquisition price as context for choosing your own price."),
    "Bob": ("SELL", "Choose your own limit price for selling your one AMZ share. Pick a price different "
                    "from the existing virtual ask so this demonstration can compare price priority."),
    "Carol": ("BUY", "Inspect both virtual asks and choose a limit at or above both ask prices. "
                      "Buy exactly one share. The exchange should fill against the cheaper ask."),
}


def request_stock(path: str, *, method="GET", body=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None if body is None else json.dumps(body).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    outgoing = Request(STOCK_API_URL + path, data=payload, headers=headers, method=method)
    try:
        with STOCK_HTTP.open(outgoing, timeout=20) as response:
            result = response.read(1024 * 1024)
    except HTTPError as error:
        raise RuntimeError(f"Stock Service returned HTTP {error.code}: {error.read(4096).decode(errors='replace')}") from None
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError("Stock Service is temporarily unavailable") from error
    return json.loads(result) if result else {}


def stable_order_id() -> str:
    label = {"Alice": "alice-ask", "Bob": "bob-ask", "Carol": "carol-bid"}[NAME]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "h24-stock-market:order:" + label))


def observe(purchase: dict | None) -> dict:
    assert AGENT is not None
    return {
        "positions": request_stock("/api/v1/positions", token=AGENT["api_key"]),
        "cash": request_stock("/api/v1/cash", token=AGENT["api_key"]),
        "visible_market": request_stock("/api/v1/market/" + SYMBOL),
        "acquisition": purchase,
        "assignment": {"side": ASSIGNMENTS[NAME][0], "quantity": 1},
    }


def llm_order(observation: dict) -> dict:
    if not LLM_API_KEY or not LLM_MODEL:
        raise RuntimeError("Configure LLM_API_KEY and LLM_MODEL in the H24 .env file")
    side, assignment = ASSIGNMENTS[NAME]
    asks = [Decimal(str(order["price"])) for order in observation["visible_market"]["orders"]
            if order["side"] == "SELL"]
    minimum = max(asks) if side == "BUY" and asks else Decimal("0.01")
    maximum = Decimal(observation["cash"]["available"]) if side == "BUY" else DEMO_STOCK_CASH
    if minimum > maximum or side == "BUY" and len(asks) != 2:
        raise RuntimeError("The two virtual asks must be within Carol's available cash")
    if side == "SELL":
        assignment += f" For this exercise, the buyer can spend up to ${maximum} per share."
    messages = [
        {"role": "system", "content": (
            f"You are {NAME}, an independent agent in a controlled stock-market simulation. "
            "Follow your assigned task only. Use place_order to act. Do not claim an action "
            "succeeded without its tool result. Do not place any other order or reveal credentials.\n" + assignment
        )},
        {"role": "user", "content": "Here is your current verified account and market observation:\n" +
         json.dumps(observation, ensure_ascii=False, separators=(",", ":")) +
         "\nDecide whether to place your assigned order now. If conditions are met, call place_order."},
    ]
    tool = {"type": "function", "function": {
        "name": "place_order", "description": "Place this agent's assigned AMZ limit order through Stock Service.",
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string", "enum": [SYMBOL]},
            "side": {"type": "string", "enum": [side]},
            "quantity": {"type": "integer", "enum": [1]},
            "limit_price": {"type": "number", "minimum": float(minimum), "maximum": float(maximum)},
        }, "required": ["symbol", "side", "quantity", "limit_price"], "additionalProperties": False},
    }}
    outgoing = Request(LLM_BASE_URL + "/chat/completions", data=json.dumps({
        "model": LLM_MODEL, "messages": messages, "tools": [tool], "tool_choice": "auto", "temperature": 0,
    }).encode(), headers={"Authorization": "Bearer " + LLM_API_KEY,
                         "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urlopen(outgoing, timeout=90) as response:
            result = json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as error:
        detail = error.read(4096).decode(errors="replace")
        raise RuntimeError(f"LLM request failed with HTTP {error.code}: {detail}") from None
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"LLM request failed: {error}") from error
    try:
        message = result["choices"][0]["message"]
        call = (message.get("tool_calls") or [])[0]
        if call.get("function", {}).get("name") != "place_order":
            raise RuntimeError("Model requested an unsupported action")
        args = json.loads(call["function"].get("arguments") or "{}")
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be an object")
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError(f"{NAME}'s model did not return a valid place_order call") from None
    try:
        price = Decimal(str(args["limit_price"]))
        if (not price.is_finite() or not minimum <= price <= maximum
                or price != price.quantize(Decimal("0.01"))):
            raise ValueError("Invalid limit price")
    except (InvalidOperation, TypeError, ValueError, KeyError):
        raise RuntimeError(f"{NAME}'s model must choose a limit within the budget, in cents") from None
    if args.get("symbol") != SYMBOL or args.get("side") != side or args.get("quantity") != 1:
        raise RuntimeError(f"{NAME}'s order did not match the assigned symbol, side, and quantity")
    if side == "SELL" and price in asks:
        raise RuntimeError(f"{NAME}'s model must choose a different limit from the existing ask")
    return {**args, "limit_price": str(price)}


def order_by_id(client_order_id: str):
    assert AGENT is not None
    rows = request_stock("/api/v1/orders", token=AGENT["api_key"])
    return next((row for row in rows if row["client_order_id"] == client_order_id), None)


def wait_for_order(client_order_id: str, *, fill=False, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = order_by_id(client_order_id)
        if row:
            if fill and row["status"] in {"FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELED"}:
                return row
            if not fill and row["status"] not in {"PENDING", "CANCEL_PENDING"}:
                return row
        time.sleep(1)
    raise TimeoutError("Order did not reach the expected venue state")


def act() -> dict:
    assert AGENT is not None
    side, _ = ASSIGNMENTS[NAME]
    client_order_id = stable_order_id()
    row = order_by_id(client_order_id)
    purchase = None
    if side == "SELL":
        purchase = request_stock("/api/v1/system-purchases", method="POST", token=AGENT["api_key"], body={
            "client_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"h24-stock-market:purchase:{NAME}")),
            "symbol": SYMBOL, "quantity": 1, "max_unit_price": str(DEMO_STOCK_CASH),
        })
    if row is None:
        args = llm_order(observe(purchase))
        request_stock("/api/v1/orders", method="POST", token=AGENT["api_key"], body={
            "client_order_id": client_order_id, "symbol": args["symbol"], "side": args["side"],
            "quantity": args["quantity"], "limit_price": args["limit_price"],
        })
    row = wait_for_order(client_order_id, fill=(NAME == "Carol"))
    return {"agent": NAME, "purchase": purchase, "order": row}


def state() -> dict:
    assert AGENT is not None
    positions = request_stock("/api/v1/positions", token=AGENT["api_key"])
    cash = request_stock("/api/v1/cash", token=AGENT["api_key"])
    links = request_stock("/api/v1/bank-links", token=AGENT["api_key"])
    orders = request_stock("/api/v1/orders", token=AGENT["api_key"])
    link = next((item for item in links if item.get("bank") == "h24-bank"), {})
    return {"positions": positions, "cash": cash, "orders": orders,
            "bank_balance": (link.get("balance_minor") or 0) / 100}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "agent": NAME, "configured": AGENT is not None})
        elif self.path == "/state" and self.authorized():
            try:
                self.send_json(200, state())
            except Exception as error:
                self.send_json(502, {"error": str(error)})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.authorized():
            self.send_json(401, {"error": "Unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/configure":
                if (not isinstance(payload.get("account_id"), str)
                        or not isinstance(payload.get("api_key"), str)
                        or not payload["api_key"]):
                    self.send_json(400, {"error": "Invalid account configuration"})
                    return
                global AGENT
                AGENT = {"account_id": payload["account_id"], "api_key": payload["api_key"]}
                self.send_json(200, {"agent": NAME, "configured": True})
            elif self.path == "/act":
                if AGENT is None:
                    self.send_json(503, {"error": "Agent credentials are not configured"})
                    return
                self.send_json(200, act())
            else:
                self.send_error(404)
        except Exception as error:
            self.send_json(502, {"error": str(error)})

    def authorized(self) -> bool:
        return self.headers.get("X-Agent-Control-Token", "") == CONTROL_TOKEN

    def send_json(self, status: int, body: dict):
        content = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8767), Handler).serve_forever()
