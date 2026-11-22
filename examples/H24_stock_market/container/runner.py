#!/usr/bin/env python3
"""Prepare H24 accounts and run a user-triggered, LLM-driven stock trade."""

from __future__ import annotations

import json
import imaplib
import os
import re
import socketserver
import ssl
import threading
import time
import uuid
from http.cookiejar import CookieJar
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import (HTTPSHandler, HTTPCookieProcessor, HTTPRedirectHandler,
                            ProxyHandler, Request, build_opener, urlopen)


API_URL = os.environ["STOCK_API_URL"].rstrip("/")
ADMIN_TOKEN = os.environ["STOCK_ADMIN_TOKEN"]
SYMBOL = "AMZ"
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
BANK_API_URL = os.environ.get("BANK_API_URL", "").rstrip("/")
BANK_IMAP_HOST = os.environ.get("BANK_IMAP_HOST", "")
BANK_EMAIL_DOMAIN = os.environ.get("BANK_EMAIL_DOMAIN", "h24.test")
BANK_CUSTOMER_PASSWORD = os.environ.get("BANK_CUSTOMER_PASSWORD", "")
BANK_MAILBOX_PASSWORD = os.environ.get("BANK_MAILBOX_PASSWORD", "")
AGENT_WORKER_URLS = json.loads(os.environ.get("AGENT_WORKER_URLS", "{}"))
AGENT_CONTROL_TOKENS = json.loads(os.environ.get("AGENT_CONTROL_TOKENS", "{}"))
TLS = ssl.create_default_context(cafile="/app/server.crt")
TLS.check_hostname = False
HTTP = build_opener(ProxyHandler({}), HTTPSHandler(context=TLS))

AGENTS: dict[str, dict] = {}
PARTICIPANTS: list[dict] = []
STATE_LOCK = threading.RLock()
STATE = {
    "ready": False,
    "phase": "starting",
    "message": "Preparing the Stock Service and agent accounts.",
    "started": False,
    "completed": False,
    "error": None,
    "events": [],
}


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(body)
        self.status = status


class VerificationInbox:
    def __init__(self):
        self._condition = threading.Condition()
        self._codes: dict[str, str] = {}

    def receive(self, raw: bytes) -> None:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        recipients = [address.lower() for _, address in getaddresses(message.get_all("To", []))]
        body = message.get_body(preferencelist=("plain",))
        text = body.get_content() if body else message.as_string()
        match = re.search(r"verification code is ([0-9]{6})", text, re.IGNORECASE)
        if not match:
            return
        with self._condition:
            for address in recipients:
                self._codes[address] = match.group(1)
            self._condition.notify_all()

    def wait_code(self, email: str, timeout: float = 45) -> str:
        deadline = time.monotonic() + timeout
        with self._condition:
            while email.lower() not in self._codes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Stock verification email did not arrive for {email}")
                self._condition.wait(remaining)
            return self._codes.pop(email.lower())


INBOX = VerificationInbox()


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 h24-demo-runner ESMTP\r\n")
        data_mode = False
        message_lines: list[bytes] = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            if data_mode:
                if line in (b".\r\n", b".\n"):
                    INBOX.receive(b"".join(message_lines))
                    message_lines.clear()
                    data_mode = False
                    self.wfile.write(b"250 message accepted\r\n")
                else:
                    message_lines.append(line[1:] if line.startswith(b"..") else line)
                continue
            command = line.decode("ascii", errors="replace").strip().upper()
            if command.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-h24-demo-runner\r\n250 SIZE 1048576\r\n")
            elif command.startswith(("MAIL FROM", "RCPT TO", "RSET", "NOOP")):
                self.wfile.write(b"250 ok\r\n")
            elif command == "DATA":
                data_mode = True
                self.wfile.write(b"354 end with <CRLF>.<CRLF>\r\n")
            elif command == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"502 command not supported\r\n")


class SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def publish(phase: str, message: str) -> None:
    with STATE_LOCK:
        STATE["phase"] = phase
        STATE["message"] = message
        STATE["events"].append({"time": time.strftime("%H:%M:%S"), "phase": phase, "message": message})
        STATE["events"] = STATE["events"][-30:]
    print(message, flush=True)


def request(path: str, *, method="GET", body=None, token=None, admin=False):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if admin:
        headers["X-Stock-Admin-Token"] = ADMIN_TOKEN
    payload = None if body is None else json.dumps(body).encode()
    outgoing = Request(API_URL + path, data=payload, headers=headers, method=method)
    try:
        with HTTP.open(outgoing, timeout=15) as response:
            content = response.read(1024 * 1024)
    except HTTPError as error:
        raise ApiError(error.code, error.read(8192).decode(errors="replace")) from None
    except (OSError, URLError, TimeoutError) as error:
        raise ConnectionError("Stock Service request failed") from error
    return json.loads(content) if content else {}


def agent_control(name: str, path: str, *, method="GET", body=None):
    url = AGENT_WORKER_URLS.get(name)
    token = AGENT_CONTROL_TOKENS.get(name)
    if not url or not token:
        raise RuntimeError(f"No private control channel is configured for {name}")
    headers = {"Accept": "application/json", "X-Agent-Control-Token": token}
    payload = None if body is None else json.dumps(body).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    outgoing = Request(url.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        with HTTP.open(outgoing, timeout=120) as response:
            content = response.read(1024 * 1024)
    except HTTPError as error:
        raise ApiError(error.code, error.read(8192).decode(errors="replace")) from None
    except (OSError, URLError, TimeoutError) as error:
        raise ConnectionError(f"{name}'s agent VM is not reachable") from error
    return json.loads(content) if content else {}


def provision_agent_vms(agents: dict[str, dict]) -> None:
    """Deliver each account key to only its matching agent VM."""
    for name, account in agents.items():
        deadline = time.monotonic() + 180
        while True:
            try:
                health = agent_control(name, "/health")
                if health.get("agent") != name:
                    raise RuntimeError(f"Unexpected agent VM responded for {name}")
                agent_control(name, "/configure", method="POST", body={
                    "account_id": account["account_id"], "api_key": account["api_key"],
                })
                account.pop("api_key", None)
                publish("agent-vm", f"{name}'s agent VM is ready with its own Stock account key.")
                break
            except (ApiError, ConnectionError, json.JSONDecodeError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{name}'s agent VM did not become ready")
                time.sleep(2)


def wait_for_service() -> None:
    publish("connecting", "Waiting for Stock Service and QuantReplay FIX session…")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            if request("/health").get("status") == "ok":
                if request("/api/v1/system/status").get("trading_enabled"):
                    publish("preparing", "Stock Service is connected to QuantReplay.")
                    return
        except (ApiError, ConnectionError, json.JSONDecodeError):
            pass
        time.sleep(5)
    raise TimeoutError("Stock Service did not connect to QuantReplay within ten minutes")


def wait_for_bank() -> None:
    publish("bank-connecting", "Waiting for Bank Service and customer-card API…")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            bank_request("/cards")
        except ApiError as error:
            if error.status in (401, 403):
                return
        except ConnectionError:
            pass
        time.sleep(5)
    raise TimeoutError("Bank Service did not become ready within ten minutes")


def make_account(display_name: str, localpart: str, password: str) -> dict:
    email = localpart + "@" + BANK_EMAIL_DOMAIN
    try:
        result = request("/api/v1/accounts/login", method="POST",
                         body={"email": email, "password": password})
        publish("preparing", f"{display_name}'s Stock account is ready.")
        return result
    except ApiError as error:
        if error.status == 401:
            try:
                request("/api/v1/accounts/register", method="POST", body={
                    "email": email, "password": password, "display_name": display_name,
                })
            except ApiError as register_error:
                if register_error.status != 409:
                    raise
        elif error.status != 403:
            raise

    for attempt in range(2):
        try:
            code = INBOX.wait_code(email)
        except TimeoutError:
            try:
                request("/api/v1/accounts/resend-verification", method="POST", body={"email": email})
            except ApiError as resend_error:
                if resend_error.status == 429 and attempt == 0:
                    time.sleep(60)
                    request("/api/v1/accounts/resend-verification", method="POST", body={"email": email})
                elif resend_error.status not in (202, 429):
                    raise
            code = INBOX.wait_code(email)
        request("/api/v1/accounts/verify-email", method="POST", body={"email": email, "code": code})
        return request("/api/v1/accounts/login", method="POST",
                       body={"email": email, "password": password})
    raise RuntimeError(f"Could not verify the Stock account for {display_name}")


def bank_request(path: str, *, method="GET", body=None, opener=None, headers=None):
    if not BANK_API_URL:
        raise RuntimeError("H24 Bank API is not configured")
    outgoing_headers = {"Accept": "application/json", **(headers or {})}
    payload = None if body is None else json.dumps(body).encode()
    if payload is not None:
        outgoing_headers["Content-Type"] = "application/json"
    outgoing = Request(BANK_API_URL + path, data=payload, headers=outgoing_headers, method=method)
    try:
        with (opener or HTTP).open(outgoing, timeout=20) as response:
            content = response.read(1024 * 1024)
    except HTTPError as error:
        raise ApiError(error.code, error.read(8192).decode(errors="replace")) from None
    except (OSError, URLError, TimeoutError) as error:
        raise ConnectionError("Bank Service request failed") from error
    return json.loads(content) if content else {}


def last_mail_uids(email_address: str) -> dict[str, int]:
    mail = imaplib.IMAP4(BANK_IMAP_HOST, 143)
    try:
        mail.login(email_address, BANK_MAILBOX_PASSWORD)
        latest: dict[str, int] = {}
        for folder in ("INBOX", "Junk"):
            status, _ = mail.select(folder)
            if status != "OK":
                latest[folder] = 0
                continue
            status, data = mail.uid("search", None, "ALL")
            latest[folder] = (max(int(uid) for uid in data[0].split())
                              if status == "OK" and data and data[0] else 0)
        return latest
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def wait_bank_code(email_address: str, after_uids: dict[str, int], timeout: float = 120) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mail = imaplib.IMAP4(BANK_IMAP_HOST, 143)
        try:
            mail.login(email_address, BANK_MAILBOX_PASSWORD)
            for folder in ("INBOX", "Junk"):
                status, _ = mail.select(folder)
                if status != "OK":
                    continue
                status, data = mail.uid("search", None, "ALL")
                if status == "OK" and data and data[0]:
                    # Avoid IMAP's reversed-range behavior for `UID n:*` when
                    # n is newer than the mailbox's current highest UID. In
                    # that case `*` can resolve to an older message, causing
                    # us to read a stale OTP before the new email arrives.
                    new_uids = [uid for uid in data[0].split()
                                if int(uid) > after_uids.get(folder, 0)]
                    for uid in reversed(new_uids):
                        fetch_status, fetched = mail.uid("fetch", uid, "(RFC822)")
                        if fetch_status != "OK":
                            continue
                        raw = next((item[1] for item in fetched if isinstance(item, tuple)), b"")
                        message = BytesParser(policy=policy.default).parsebytes(raw)
                        sender = getaddresses(message.get_all("From", []))
                        if not any(address.lower() == "bank@" + BANK_EMAIL_DOMAIN
                                   for _, address in sender):
                            continue
                        part = message.get_body(preferencelist=("plain",))
                        body = part.get_content() if part else message.as_string()
                        if "use it to sign in" not in body.lower():
                            continue
                        match = re.search(r"verification code is:\s*([A-Za-z0-9]+)", body, re.IGNORECASE)
                        if match:
                            return match.group(1)
        finally:
            try:
                mail.logout()
            except Exception:
                pass
        time.sleep(2)
    raise TimeoutError(f"Bank login verification email did not arrive for {email_address}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def redirect_location(opener, url: str, *, headers=None, body=None):
    request_headers = {"Accept": "text/html", **(headers or {})}
    outgoing = Request(url, data=body, headers=request_headers,
                       method="POST" if body is not None else "GET")
    try:
        with opener.open(outgoing, timeout=30):
            raise RuntimeError("Bank authorization did not redirect")
    except HTTPError as error:
        location = error.headers.get("Location")
        code = error.code
        error.close()
        if code not in (302, 303) or not location:
            raise RuntimeError(f"Bank authorization returned HTTP {code}") from None
        return location


def link_bank_card(name: str, stock_account: dict) -> dict:
    linked = request("/api/v1/bank-links", token=stock_account["api_key"])
    existing = next((item for item in linked if item.get("bank") == "h24-bank" and item.get("available")), None)
    if existing:
        return existing
    email_address = name.lower() + "@" + BANK_EMAIL_DOMAIN
    fingerprint_headers = {"X-Device-Fingerprint": "h24-" + name.lower()}
    cookies = CookieJar()
    bank_session = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    for attempt in range(3):
        new_uids = last_mail_uids(email_address)
        challenge = bank_request("/authentication/login", method="POST", opener=bank_session,
                                 headers=fingerprint_headers,
                                 body={"email": email_address, "password": BANK_CUSTOMER_PASSWORD})
        code = wait_bank_code(email_address, new_uids)
        try:
            bank_request("/authentication/2fa", method="POST", opener=bank_session,
                         headers=fingerprint_headers,
                         body={"challengeToken": challenge["challengeToken"], "token": code})
            break
        except ApiError as error:
            if attempt == 2 or error.status != 401:
                raise
            print(f"{name}'s Bank OTP was rejected; requesting a fresh sign-in challenge.", flush=True)
            cookies.clear()
            bank_session = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    cards = bank_request("/cards", opener=bank_session, headers=fingerprint_headers)
    card = next((item for item in cards if item.get("name") == name + " Debit"), None)
    if card is None or card.get("status") != "active":
        raise RuntimeError(f"{name}'s active bank debit card was not found")
    card_id = str(card.get("cardId", card.get("id")))
    begin = request("/api/v1/bank-links", method="POST", token=stock_account["api_key"], body={
        "bank": "h24-bank", "card_id": card_id, "card_number": str(card["number"]),
    })

    # Finish the bank's card-scoped OAuth consent using the customer's authenticated session.
    no_redirect = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies), NoRedirect())
    authorization_url = begin["authorization_url"]
    parsed_authorization = urlsplit(authorization_url)
    bank_origin = urlsplit(BANK_API_URL)
    if (parsed_authorization.scheme != bank_origin.scheme or parsed_authorization.netloc != bank_origin.netloc
            or parsed_authorization.path != "/api/v1/oauth2/authorize"):
        raise RuntimeError("Bank authorization URL did not match the configured Bank Service")
    location = urljoin(BANK_API_URL + "/", redirect_location(
        no_redirect, authorization_url, headers=fingerprint_headers))
    consent = urlsplit(location)
    if consent.scheme != bank_origin.scheme or consent.netloc != bank_origin.netloc or consent.path != "/consent":
        raise RuntimeError("Bank did not present the expected card consent page")
    parameters = parse_qs(consent.query)
    consent_state = parameters.get("state", [""])[0]
    preview = bank_request("/cards/authorization?" + urlencode({"state": consent_state}),
                           opener=no_redirect, headers=fingerprint_headers)
    if preview.get("cardId") != card_id:
        raise RuntimeError("Bank consent did not match the selected card")
    csrf_cookie = next((unquote(cookie.value) for cookie in cookies if cookie.name.endswith("XSRF-TOKEN")), None)
    if not csrf_cookie:
        raise RuntimeError("Bank authorization session did not provide a CSRF token")
    fields = [("client_id", parameters.get("client_id", [""])[0]),
              ("state", consent_state), ("_csrf", csrf_cookie)]
    fields.extend(("scope", scope) for scope in ("openbanking:cards.read", "openbanking:payments"))
    callback_url = urljoin(BANK_API_URL + "/", redirect_location(
        no_redirect, BANK_API_URL + "/oauth2/authorize",
        headers={**fingerprint_headers, "Content-Type": "application/x-www-form-urlencoded"},
        body=urlencode(fields).encode(),
    ))
    callback = urlsplit(callback_url)
    original_state = parse_qs(urlsplit(authorization_url).query).get("state", [""])[0]
    callback_params = parse_qs(callback.query)
    if (callback.scheme != "http" or callback.netloc != "10.250.0.31:8447"
            or callback.path != "/bank-callback" or callback_params.get("state", [""])[0] != original_state
            or callback_params.get("code", [""])[0] == ""):
        raise RuntimeError("Bank consent callback did not match the Stock Service request")
    result = request("/api/v1/bank-links/complete", method="POST", token=stock_account["api_key"],
                     body={"state": original_state, "code": callback_params["code"][0]})
    return result


def stable_id(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "h24-stock-market:" + label))


def seed_assets(agents: dict[str, dict]) -> None:
    for seller in ("Alice", "Bob"):
        request("/api/v1/admin/allocations", method="POST", admin=True, body={
            "allocation_id": stable_id("shares:" + seller.lower()),
            "account_id": agents[seller]["account_id"], "symbol": SYMBOL, "quantity": 1,
        })


def account_request(agent: dict, path: str):
    return request(path, token=agent["api_key"])


def ask_agent_vm(name: str) -> dict:
    publish("thinking", f"{name}'s VM is checking its own account and deciding its assigned order.")
    result = agent_control(name, "/act", method="POST", body={})
    order = result.get("order")
    if not isinstance(order, dict):
        raise RuntimeError(f"{name}'s VM did not return an order result")
    publish("action", f"{name}'s VM submitted its assigned {result.get('side', '').lower()} order.")
    return order


def run_actions() -> None:
    try:
        publish("alice", "Alice's turn: check her AMZ holding and decide whether to post the $11.00 ask.")
        alice = ask_agent_vm("Alice")
        if alice["status"] not in {"NEW", "PARTIALLY_FILLED", "FILLED"}:
            raise RuntimeError("Alice's assigned sell order was not accepted")

        publish("bob", "Bob's turn: after Alice's ask is confirmed, check his holding and consider the $10.00 ask.")
        bob = ask_agent_vm("Bob")
        if bob["status"] not in {"NEW", "PARTIALLY_FILLED", "FILLED"}:
            raise RuntimeError("Bob's assigned sell order was not accepted")

        publish("carol", "Carol's turn: review both asks and her cash, then decide whether to bid up to $11.00.")
        carol = ask_agent_vm("Carol")
        if carol["status"] != "FILLED" or Decimal(carol["average_fill_price"]) != Decimal("10.00"):
            raise RuntimeError("Carol's order did not fill against Bob at the expected $10.00 price")

        alice_state = agent_control("Alice", "/state")
        bob_state = agent_control("Bob", "/state")
        carol_state = agent_control("Carol", "/state")
        alice_final = next(row for row in alice_state["orders"]
                           if row["client_order_id"] == stable_id("order:alice-ask"))
        bob_final = next(row for row in bob_state["orders"]
                         if row["client_order_id"] == stable_id("order:bob-ask"))
        market = request("/api/v1/market/" + SYMBOL)
        positions = {item["account_id"]: item for item in market["positions"]}
        if (alice_final["status"] != "NEW" or bob_final["status"] != "FILLED"
                or positions[AGENTS["Alice"]["account_id"]]["quantity"] != 1
                or positions[AGENTS["Alice"]["account_id"]]["reserved"] != 1
                or positions[AGENTS["Bob"]["account_id"]]["quantity"] != 0
                or positions[AGENTS["Bob"]["account_id"]]["reserved"] != 0
                or positions[AGENTS["Carol"]["account_id"]]["quantity"] != 1
                or positions[AGENTS["Carol"]["account_id"]]["reserved"] != 0
                or Decimal(bob_state["cash"]["balance"]) != Decimal("10.00")
                or Decimal(carol_state["cash"]["balance"]) != Decimal("40.00")):
            raise RuntimeError("Final order, share, or cash state did not match the expected trade")
        refresh_participant_balances()
        publish("complete", "Trade complete: Carol bought Bob's cheaper share for $10.00; Alice's $11.00 ask remains open.")
        with STATE_LOCK:
            STATE["completed"] = True
    except Exception as error:
        with STATE_LOCK:
            STATE["phase"] = "failed"
            STATE["error"] = str(error)
            STATE["message"] = "The agent sequence stopped. Review the event log before retrying."
            STATE["events"].append({"time": time.strftime("%H:%M:%S"), "phase": "failed",
                                    "message": STATE["message"]})
        print("H24 LLM action sequence failed:", error, flush=True)


def state_snapshot() -> dict:
    with STATE_LOCK:
        return {
            **STATE,
            "participants": PARTICIPANTS,
            "model_configured": bool(LLM_API_KEY and LLM_MODEL),
            "can_start": bool(STATE["ready"] and LLM_API_KEY and LLM_MODEL
                              and not STATE["completed"]
                              and (not STATE["started"] or STATE["phase"] == "failed")),
        }


def refresh_participant_balances() -> None:
    for participant in PARTICIPANTS:
        state = agent_control(participant["name"], "/state")
        participant["bank_balance"] = state["bank_balance"]
        participant["shares"] = sum(item["quantity"] for item in state["positions"]
                                     if item["symbol"] == SYMBOL)
        participant["stock_cash"] = float(state["cash"]["balance"])
        participant["stock_cash_available"] = float(state["cash"]["available"])


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/v1/demo/status":
            self.send_error(404)
            return
        self.send_json(200, state_snapshot())

    def do_POST(self):
        if self.path != "/api/v1/demo/start":
            self.send_error(404)
            return
        with STATE_LOCK:
            snapshot = state_snapshot()
            if not snapshot["ready"]:
                self.send_json(503, {"error": "Stock Service is not ready", "status": snapshot})
                return
            if not snapshot["model_configured"]:
                self.send_json(503, {"error": "Configure LLM_API_KEY and LLM_MODEL first", "status": snapshot})
                return
            if snapshot["started"] and snapshot["phase"] != "failed":
                self.send_json(202, snapshot)
                return
            STATE["started"] = True
            STATE["error"] = None
            STATE["phase"] = "starting"
            worker = threading.Thread(target=run_actions, daemon=True)
            worker.start()
        self.send_json(202, state_snapshot())

    def send_json(self, code: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


def prepare() -> None:
    global AGENTS, PARTICIPANTS
    wait_for_service()
    wait_for_bank()
    password = "H24AgentDemo2026!"
    AGENTS = {
        "Alice": make_account("Alice", "alice", password),
        "Bob": make_account("Bob", "bob", password),
        "Carol": make_account("Carol", "carol", password),
    }
    bank_links = {}
    for name, account in AGENTS.items():
        publish("bank-link", f"Binding {name}'s Stock account to the matching bank debit card.")
        bank_links[name] = link_bank_card(name, account)
    publish("funding", "Depositing $50.00 from Carol's linked bank card into her Stock cash account.")
    # Scope the idempotency key to this Stock account. The H24 reset can
    # recreate Stock accounts while Bank persists, so a global fixed key
    # could return a payment addressed to the previous Stock account.
    deposit_id = stable_id("bank-deposit:carol:" + AGENTS["Carol"]["account_id"])
    deposit = request("/api/v1/cash/deposits", method="POST", token=AGENTS["Carol"]["api_key"], body={
        "id": deposit_id, "bank_link_id": bank_links["Carol"]["id"], "amount": "50.00",
    })
    if deposit.get("status") != "COMPLETED":
        raise RuntimeError("Carol's bank deposit did not complete")
    seed_assets(AGENTS)
    PARTICIPANTS = []
    for name, account in AGENTS.items():
        positions = account_request(account, "/api/v1/positions")
        quantity = sum(item["quantity"] for item in positions if item["symbol"] == SYMBOL)
        linked = next((item for item in account_request(account, "/api/v1/bank-links")
                       if item.get("bank") == "h24-bank"), {})
        cash = account_request(account, "/api/v1/cash")
        PARTICIPANTS.append({"account_id": account["account_id"], "name": name, "shares": quantity,
                             "bank_balance": (linked.get("balance_minor") or 0) / 100,
                             "stock_cash": float(cash["balance"]),
                             "stock_cash_available": float(cash["available"])})
    provision_agent_vms(AGENTS)
    publish("ready", "Ready. No agent orders have been submitted. Click Start agent actions when you want to begin.")
    with STATE_LOCK:
        STATE["ready"] = True
        if not LLM_API_KEY or not LLM_MODEL:
            STATE["message"] = "Ready, but LLM_API_KEY and LLM_MODEL must be configured before starting."


def main() -> None:
    smtp = SMTPServer(("0.0.0.0", 2525), SMTPHandler)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: _prepare_with_error_state(), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8766), ControlHandler).serve_forever()


def _prepare_with_error_state() -> None:
    try:
        prepare()
    except Exception as error:
        with STATE_LOCK:
            STATE["phase"] = "failed"
            STATE["error"] = str(error)
            STATE["message"] = "H24 setup failed before agents were ready."
        print("H24 setup failed:", error, flush=True)


if __name__ == "__main__":
    main()
