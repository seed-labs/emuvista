"""Stock account and portfolio HTTP API."""

from __future__ import annotations

import hmac
import json
import re
import smtplib
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, BeforeValidator, EmailStr, Field, TypeAdapter

from .db import connection, initialize_schema
from .fix_gateway import QuantReplayFixGateway
from . import banking
from .mail import EmailNotConfigured, send_verification_code
from .security import (
    hash_api_secret,
    hash_code,
    hash_password,
    issue_api_key,
    new_verification_code,
    normalize_email,
    verify_password,
)
from .settings import settings


def _validate_email_address(value: object) -> str:
    # Allow the stock example's current and legacy mail domains when a demo
    # explicitly opts in. Other addresses use normal EmailStr validation.
    if (settings.allow_test_email_domain and isinstance(value, str)
            and re.fullmatch(r"[^\s<>@]+@h(?:23|24)\.test", value, re.IGNORECASE)):
        return value.strip().lower()
    return TypeAdapter(EmailStr).validate_python(value)


EmailAddress = Annotated[str, BeforeValidator(_validate_email_address)]


fix_gateway: QuantReplayFixGateway | None = None
fix_report_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global fix_gateway, fix_report_task
    initialize_schema()
    if settings.quantreplay_host:
        fix_gateway = QuantReplayFixGateway(
            host=settings.quantreplay_host,
            port=settings.quantreplay_fix_port,
            sender_comp_id=settings.fix_sender_comp_id,
            target_comp_id=settings.fix_target_comp_id,
        )
        await fix_gateway.start()
        fix_report_task = asyncio.create_task(_consume_fix_reports(fix_gateway))
    try:
        yield
    finally:
        if fix_gateway:
            if fix_report_task:
                fix_report_task.cancel()
                try:
                    await fix_report_task
                except asyncio.CancelledError:
                    pass
                fix_report_task = None
            await fix_gateway.stop()
            fix_gateway = None


app = FastAPI(title="Stock Service", version="0.1.0", lifespan=lifespan)
WEB_DIR = Path(__file__).with_name("web")
DEMO_SCENARIO_PATH = Path(__file__).with_name("demo_scenario.json")


@app.get("/", include_in_schema=False)
def stock_dashboard() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/assets/{asset_name}", include_in_schema=False)
def dashboard_asset(asset_name: str) -> FileResponse:
    if asset_name not in {"styles.css", "app.js"}:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(WEB_DIR / asset_name)


@app.get("/api/v1/demo/scenario", include_in_schema=False)
def get_demo_scenario() -> dict:
    return json.loads(DEMO_SCENARIO_PATH.read_text(encoding="utf-8"))


class Registration(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(default="", max_length=64)


class VerifyEmail(BaseModel):
    email: EmailAddress
    code: str = Field(pattern=r"^[0-9]{6}$")


class ResendVerification(BaseModel):
    email: EmailAddress


class Login(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=1, max_length=256)


class KeyResponse(BaseModel):
    account_id: uuid.UUID
    api_key: str
    warning: str = "This API key is shown once. Store it securely."


class AccountResponse(BaseModel):
    account_id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    bank_linked: bool


class PositionResponse(BaseModel):
    symbol: str
    quantity: int
    reserved: int
    available: int


class CashResponse(BaseModel):
    balance: Decimal
    reserved: Decimal
    available: Decimal
    currency: str


class OrderRequest(BaseModel):
    client_order_id: uuid.UUID
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=2**53 - 1)
    limit_price: Decimal = Field(gt=0, max_digits=20, decimal_places=2)


class OrderResponse(BaseModel):
    id: uuid.UUID
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    limit_price: Decimal
    average_fill_price: Decimal | None
    status: str
    created_at: datetime


class CashAllocation(BaseModel):
    allocation_id: uuid.UUID
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    external_reference: str = Field(min_length=1, max_length=200)


class BankLinkStart(BaseModel):
    bank: str = Field(min_length=1, max_length=80)
    card_id: str = Field(min_length=1, max_length=80)
    card_number: str = Field(pattern=r"^[0-9]{16,19}$")


class BankLinkFinish(BaseModel):
    state: str = Field(min_length=32, max_length=100)
    code: str = Field(min_length=1, max_length=2000)


class CashDepositRequest(BaseModel):
    id: uuid.UUID
    bank_link_id: uuid.UUID
    amount: Decimal = Field(gt=0, le=1_000_000, max_digits=20, decimal_places=2)


class Allocation(BaseModel):
    allocation_id: uuid.UUID
    account_id: uuid.UUID
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    quantity: int = Field(gt=0, le=2**53 - 1)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def authenticated_account(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    token = authorization[7:].strip()
    match = re.fullmatch(r"stk_([0-9a-f]{16})\.([A-Za-z0-9_-]{32,})", token)
    if not match:
        raise _unauthorized()
    key_id, secret = match.groups()
    with connection() as conn:
        row = conn.execute(
            """SELECT a.id, a.email, a.display_name FROM stock_api_keys k
               JOIN stock_accounts a ON a.id = k.account_id
               WHERE k.id = %s AND k.secret_hash = %s AND k.revoked_at IS NULL
                 AND a.email_verified_at IS NOT NULL""",
            (key_id, hash_api_secret(secret)),
        ).fetchone()
        if row is None:
            raise _unauthorized()
        conn.execute("UPDATE stock_api_keys SET last_used_at = now() WHERE id = %s", (key_id,))
        return row


@app.get("/health")
def health() -> dict[str, str]:
    with connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/v1/system/status")
def system_status() -> dict[str, object]:
    connected = bool(fix_gateway and fix_gateway.connected)
    return {
        "status": "ok",
        "quantreplay_fix_configured": bool(settings.quantreplay_host),
        "quantreplay_fix_connected": connected,
        "trading_enabled": connected,
        "trading_reason": None if connected else "QuantReplay FIX session is not connected",
    }


@app.post("/api/v1/accounts/register", status_code=status.HTTP_202_ACCEPTED)
def register(payload: Registration) -> dict[str, str]:
    email = normalize_email(str(payload.email))
    salt, password_hash = hash_password(payload.password)
    code = new_verification_code()
    try:
        with connection() as conn:
            account = conn.execute(
                """INSERT INTO stock_accounts (id, email, display_name, password_salt, password_hash)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (email) DO NOTHING RETURNING id""",
                (uuid.uuid4(), email, payload.display_name.strip(), salt, password_hash),
            ).fetchone()
            if account is None:
                raise HTTPException(status_code=409, detail="An account with this email already exists")
            conn.execute(
                "INSERT INTO stock_cash_accounts (account_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (account["id"],),
            )
            conn.execute(
                """INSERT INTO email_verifications (email, code_hash, expires_at, attempts)
                   VALUES (%s, %s, now() + (%s * interval '1 second'), 0)
                   ON CONFLICT (email) DO UPDATE SET code_hash = EXCLUDED.code_hash,
                     expires_at = EXCLUDED.expires_at, attempts = 0, created_at = now()""",
                (email, hash_code(code), settings.verification_ttl_seconds),
            )
    except HTTPException:
        raise

    try:
        send_verification_code(email, code)
    except (EmailNotConfigured, OSError, smtplib.SMTPException) as error:
        raise HTTPException(status_code=503, detail="Email verification is temporarily unavailable") from error
    return {"status": "verification_sent"}


@app.post("/api/v1/accounts/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(payload: ResendVerification) -> dict[str, str]:
    email = normalize_email(str(payload.email))
    code = new_verification_code()
    with connection() as conn:
        account = conn.execute(
            "SELECT email_verified_at FROM stock_accounts WHERE email = %s FOR UPDATE",
            (email,),
        ).fetchone()
        if account is None or account["email_verified_at"] is not None:
            return {"status": "if_pending_account_exists_verification_was_sent"}
        existing = conn.execute(
            "SELECT created_at FROM email_verifications WHERE email = %s FOR UPDATE",
            (email,),
        ).fetchone()
        if existing and (datetime.now(timezone.utc) - existing["created_at"]).total_seconds() < 60:
            raise HTTPException(status_code=429, detail="Wait before requesting another verification code")
        conn.execute(
            """INSERT INTO email_verifications (email, code_hash, expires_at, attempts)
               VALUES (%s, %s, now() + (%s * interval '1 second'), 0)
               ON CONFLICT (email) DO UPDATE SET code_hash = EXCLUDED.code_hash,
                 expires_at = EXCLUDED.expires_at, attempts = 0, created_at = now()""",
            (email, hash_code(code), settings.verification_ttl_seconds),
        )
    try:
        send_verification_code(email, code)
    except (EmailNotConfigured, OSError, smtplib.SMTPException) as error:
        raise HTTPException(status_code=503, detail="Email verification is temporarily unavailable") from error
    return {"status": "verification_sent"}


@app.post("/api/v1/accounts/verify-email")
def verify_email(payload: VerifyEmail) -> dict[str, str]:
    email = normalize_email(str(payload.email))
    invalid = False
    with connection() as conn:
        challenge = conn.execute(
            "SELECT code_hash, expires_at, attempts FROM email_verifications WHERE email = %s FOR UPDATE",
            (email,),
        ).fetchone()
        if challenge is None or challenge["attempts"] >= 5:
            invalid = True
        elif challenge["expires_at"] <= datetime.now(timezone.utc) or not hmac.compare_digest(
            challenge["code_hash"], hash_code(payload.code)
        ):
            conn.execute("UPDATE email_verifications SET attempts = attempts + 1 WHERE email = %s", (email,))
            invalid = True
        else:
            conn.execute("UPDATE stock_accounts SET email_verified_at = now() WHERE email = %s", (email,))
            conn.execute("DELETE FROM email_verifications WHERE email = %s", (email,))
    if invalid:
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")
    return {"status": "verified"}


@app.post("/api/v1/accounts/login", response_model=KeyResponse)
def login(payload: Login) -> KeyResponse:
    email = normalize_email(str(payload.email))
    with connection() as conn:
        account = conn.execute(
            "SELECT id, password_salt, password_hash, email_verified_at FROM stock_accounts WHERE email = %s",
            (email,),
        ).fetchone()
        if account is None or not verify_password(
            payload.password, account["password_salt"], account["password_hash"]
        ):
            raise _unauthorized()
        if account["email_verified_at"] is None:
            raise HTTPException(status_code=403, detail="Verify your email before logging in")
        key_id, secret, token = issue_api_key()
        conn.execute(
            "INSERT INTO stock_api_keys (id, account_id, secret_hash) VALUES (%s, %s, %s)",
            (key_id, account["id"], hash_api_secret(secret)),
        )
    return KeyResponse(account_id=account["id"], api_key=token)


@app.post("/api/v1/accounts/api-keys/revoke")
def revoke_key(
    authorization: Annotated[str | None, Header()] = None,
    account: dict = Depends(authenticated_account),
) -> dict[str, str]:
    token = authorization[7:].strip() if authorization else ""
    key_id = token[4:].split(".", 1)[0]
    with connection() as conn:
        conn.execute(
            "UPDATE stock_api_keys SET revoked_at = now() WHERE id = %s AND account_id = %s AND revoked_at IS NULL",
            (key_id, account["id"]),
        )
    return {"status": "revoked"}


@app.get("/api/v1/accounts/me", response_model=AccountResponse)
def me(account: dict = Depends(authenticated_account)) -> AccountResponse:
    with connection() as conn:
        bank_linked = conn.execute(
            "SELECT 1 FROM stock_bank_links WHERE account_id = %s AND active LIMIT 1",
            (account["id"],),
        ).fetchone() is not None
    return AccountResponse(account_id=account["id"], email=account["email"],
                           display_name=account["display_name"], email_verified=True,
                           bank_linked=bank_linked)


@app.get("/api/v1/positions", response_model=list[PositionResponse])
def positions(account: dict = Depends(authenticated_account)) -> list[PositionResponse]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT symbol, quantity, reserved FROM stock_positions
               WHERE account_id = %s AND quantity > 0 ORDER BY symbol""",
            (account["id"],),
        ).fetchall()
    return [
        PositionResponse(
            symbol=row["symbol"],
            quantity=row["quantity"],
            reserved=row["reserved"],
            available=row["quantity"] - row["reserved"],
        )
        for row in rows
    ]


@app.get("/api/v1/cash", response_model=CashResponse)
def cash_balance(account: dict = Depends(authenticated_account)) -> CashResponse:
    with connection() as conn:
        row = conn.execute(
            """SELECT balance, reserved, currency FROM stock_cash_accounts
               WHERE account_id = %s""",
            (account["id"],),
        ).fetchone()
    if row is None:
        return CashResponse(balance=Decimal("0.00"), reserved=Decimal("0.00"),
                            available=Decimal("0.00"), currency="USD")
    return CashResponse(
        balance=row["balance"], reserved=row["reserved"],
        available=row["balance"] - row["reserved"], currency=row["currency"].strip(),
    )


def _bank_error(error: Exception) -> HTTPException:
    if isinstance(error, banking.BankRequestError):
        code = 403 if error.status in {401, 403} else 503 if error.status >= 500 else 400
        return HTTPException(status_code=code, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(status_code=503, detail="Bank operation is temporarily unavailable")


@app.get("/api/v1/bank-links")
def bank_links(account: dict = Depends(authenticated_account)) -> list[dict[str, object]]:
    try:
        return banking.list_links(account)
    except Exception as error:
        raise _bank_error(error) from error


@app.post("/api/v1/bank-links")
def begin_bank_link(payload: BankLinkStart, account: dict = Depends(authenticated_account)) -> dict[str, str]:
    try:
        return banking.begin_link(account, payload.bank, payload.card_id, payload.card_number)
    except Exception as error:
        raise _bank_error(error) from error


@app.post("/api/v1/bank-links/complete")
def finish_bank_link(payload: BankLinkFinish, account: dict = Depends(authenticated_account)) -> dict[str, object]:
    try:
        return banking.complete_link(account, payload.state, payload.code)
    except Exception as error:
        raise _bank_error(error) from error


@app.delete("/api/v1/bank-links/{link_id}")
def remove_bank_link(link_id: uuid.UUID, account: dict = Depends(authenticated_account)) -> dict[str, str]:
    try:
        banking.unlink(account, link_id)
    except Exception as error:
        raise _bank_error(error) from error
    return {"id": str(link_id), "status": "unlinked"}


@app.post("/api/v1/cash/deposits")
def deposit_cash(payload: CashDepositRequest, account: dict = Depends(authenticated_account)) -> dict[str, object]:
    try:
        return banking.deposit(account, payload.id, payload.bank_link_id, payload.amount)
    except Exception as error:
        raise _bank_error(error) from error


@app.get("/api/v1/cash/deposits/{deposit_id}")
def cash_deposit_status(deposit_id: uuid.UUID, account: dict = Depends(authenticated_account)) -> dict[str, object]:
    try:
        return banking.deposit_status(account, deposit_id)
    except Exception as error:
        raise _bank_error(error) from error


@app.post("/api/v1/admin/cash-allocations", status_code=status.HTTP_201_CREATED)
def allocate_initial_cash(
    payload: CashAllocation,
    admin_token: Annotated[str | None, Header(alias="X-Stock-Admin-Token")] = None,
) -> dict[str, object]:
    if not settings.admin_token or not admin_token or not hmac.compare_digest(
        admin_token, settings.admin_token
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    amount = payload.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    with connection() as conn:
        account = conn.execute(
            "SELECT id FROM stock_accounts WHERE id = %s AND email_verified_at IS NOT NULL",
            (payload.account_id,),
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=404, detail="Verified stock account not found")
        conn.execute(
            "INSERT INTO stock_cash_accounts (account_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (payload.account_id,),
        )
        entry = conn.execute(
            """INSERT INTO stock_cash_ledger
                 (entry_id, account_id, entry_type, balance_delta, external_reference)
               VALUES (%s, %s, 'DEPOSIT', %s, %s)
               ON CONFLICT DO NOTHING RETURNING entry_id""",
            (payload.allocation_id, payload.account_id, amount, payload.external_reference),
        ).fetchone()
        if entry is None:
            previous = conn.execute(
                """SELECT account_id, entry_type, balance_delta, external_reference
                   FROM stock_cash_ledger WHERE entry_id = %s OR external_reference = %s""",
                (payload.allocation_id, payload.external_reference),
            ).fetchone()
            if (previous is None or previous["account_id"] != payload.account_id
                    or previous["entry_type"] != "DEPOSIT"
                    or previous["balance_delta"] != amount
                    or previous["external_reference"] != payload.external_reference):
                raise HTTPException(status_code=409, detail="Cash allocation reference was already used")
            row = conn.execute(
                "SELECT balance, reserved FROM stock_cash_accounts WHERE account_id = %s",
                (payload.account_id,),
            ).fetchone()
            return {"allocation_id": payload.allocation_id, "account_id": payload.account_id,
                    "balance": row["balance"], "reserved": row["reserved"], "replayed": True}
        row = conn.execute(
            """UPDATE stock_cash_accounts SET balance = balance + %s, updated_at = now()
               WHERE account_id = %s RETURNING balance, reserved""",
            (amount, payload.account_id),
        ).fetchone()
    return {"allocation_id": payload.allocation_id, "account_id": payload.account_id,
            "balance": row["balance"], "reserved": row["reserved"], "replayed": False}


def _release_order_reserve(conn, order: dict) -> None:
    remaining = max(0, order["quantity"] - order["filled_quantity"])
    if not remaining:
        return
    if order["side"] == "BUY":
        amount = (order["limit_price"] * remaining).quantize(Decimal("0.01"))
        if amount:
            released = conn.execute(
                """UPDATE stock_cash_accounts SET reserved = reserved - %s, updated_at = now()
                   WHERE account_id = %s AND reserved >= %s RETURNING account_id""",
                (amount, order["account_id"], amount),
            ).fetchone()
            if released is None:
                raise ValueError("Could not release the remaining buy cash reservation")
            conn.execute(
                """INSERT INTO stock_cash_ledger
                     (entry_id, account_id, entry_type, reserved_delta, order_id)
                   VALUES (%s, %s, 'RELEASE', %s, %s)""",
                (uuid.uuid4(), order["account_id"], -amount, order["id"]),
            )
    else:
        released = conn.execute(
            """UPDATE stock_positions SET reserved = reserved - %s, updated_at = now()
               WHERE account_id = %s AND symbol = %s AND reserved >= %s RETURNING account_id""",
            (remaining, order["account_id"], order["symbol"], remaining),
        ).fetchone()
        if released is None:
            raise ValueError("Could not release the remaining share reservation")


def _process_fix_report(report) -> None:
    original_id = report.original_client_order_id or report.client_order_id
    with connection() as conn:
        order = conn.execute(
            """SELECT * FROM stock_orders
               WHERE fix_client_order_id = %s OR cancel_client_order_id = %s
                  OR fix_client_order_id = %s FOR UPDATE""",
            (original_id, report.client_order_id, report.client_order_id),
        ).fetchone()
        if order is None:
            return
        accepted = conn.execute(
            """INSERT INTO stock_fix_reports (order_id, execution_id, execution_type)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING execution_id""",
            (order["id"], report.execution_id, report.execution_type),
        ).fetchone()
        if accepted is None:
            return

        execution_type = report.execution_type
        filled = order["filled_quantity"]
        if execution_type == "F":
            if report.last_quantity <= 0 or report.last_price is None or report.last_price <= 0:
                raise ValueError("QuantReplay sent an invalid trade execution report")
            if not order["limit_price"]:
                raise ValueError("Stock order has no limit price for cash reservation")
            reserve_delta = (order["limit_price"] * report.last_quantity).quantize(Decimal("0.01"))
            trade_value = (report.last_price * report.last_quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            ledger_execution_id = str(order["id"]) + ":" + report.execution_id
            fill = conn.execute(
                """INSERT INTO stock_fills (execution_id, order_id, quantity, price)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING execution_id""",
                (ledger_execution_id, order["id"], report.last_quantity, report.last_price),
            ).fetchone()
            if fill is None:
                return
            if order["side"] == "BUY":
                changed = conn.execute(
                    """UPDATE stock_cash_accounts
                       SET balance = balance - %s, reserved = reserved - %s, updated_at = now()
                       WHERE account_id = %s AND balance >= %s AND reserved >= %s
                       RETURNING account_id""",
                    (trade_value, reserve_delta, order["account_id"], trade_value, reserve_delta),
                ).fetchone()
                if changed is None:
                    raise ValueError("Reserved buy cash is insufficient for the reported fill")
                conn.execute(
                    """INSERT INTO stock_positions (account_id, symbol, quantity)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (account_id, symbol) DO UPDATE SET
                         quantity = stock_positions.quantity + EXCLUDED.quantity, updated_at = now()""",
                    (order["account_id"], order["symbol"], report.last_quantity),
                )
                conn.execute(
                    """INSERT INTO stock_cash_ledger
                         (entry_id, account_id, entry_type, balance_delta, reserved_delta,
                          order_id, execution_id)
                       VALUES (%s, %s, 'BUY_FILL', %s, %s, %s, %s)""",
                    (uuid.uuid4(), order["account_id"], -trade_value, -reserve_delta,
                     order["id"], ledger_execution_id),
                )
            else:
                changed = conn.execute(
                    """UPDATE stock_positions SET quantity = quantity - %s,
                         reserved = reserved - %s, updated_at = now()
                       WHERE account_id = %s AND symbol = %s
                         AND quantity >= %s AND reserved >= %s RETURNING account_id""",
                    (report.last_quantity, report.last_quantity, order["account_id"], order["symbol"],
                     report.last_quantity, report.last_quantity),
                ).fetchone()
                if changed is None:
                    raise ValueError("Reserved shares are insufficient for the reported fill")
                conn.execute(
                    "UPDATE stock_cash_accounts SET balance = balance + %s, updated_at = now() WHERE account_id = %s",
                    (trade_value, order["account_id"]),
                )
                conn.execute(
                    """INSERT INTO stock_cash_ledger
                         (entry_id, account_id, entry_type, balance_delta, order_id, execution_id)
                       VALUES (%s, %s, 'SELL_FILL', %s, %s, %s)""",
                    (uuid.uuid4(), order["account_id"], trade_value, order["id"], ledger_execution_id),
                )
            filled = max(order["filled_quantity"] + report.last_quantity, report.cumulative_quantity)

        status_map = {"0": "NEW", "1": "PARTIALLY_FILLED", "2": "FILLED",
                      "4": "CANCELED", "8": "REJECTED"}
        new_status = status_map.get(report.order_status, order["status"])
        if filled >= order["quantity"]:
            new_status = "FILLED"
        if execution_type in {"4", "8", "CANCEL_REJECT"}:
            _release_order_reserve(conn, {**order, "filled_quantity": filled})
            if execution_type == "CANCEL_REJECT":
                new_status = "PARTIALLY_FILLED" if filled else "NEW"
            elif execution_type == "8":
                new_status = "REJECTED"
            else:
                new_status = "CANCELED"
        conn.execute(
            """UPDATE stock_orders SET filled_quantity = %s, average_fill_price = %s,
                 status = %s, quantreplay_order_id = COALESCE(NULLIF(%s, ''), quantreplay_order_id),
                 cancel_client_order_id = CASE WHEN %s = 'CANCEL_REJECT' THEN NULL
                     WHEN %s IN ('4', '8') THEN NULL ELSE cancel_client_order_id END,
                 updated_at = now() WHERE id = %s""",
            (filled, report.average_price, new_status, report.exchange_order_id,
             execution_type, execution_type, order["id"]),
        )


async def _consume_fix_reports(gateway: QuantReplayFixGateway) -> None:
    queue = gateway.reports
    if queue is None:
        return
    while True:
        report = await queue.get()
        try:
            await asyncio.to_thread(_process_fix_report, report)
        except Exception:
            import logging
            logging.exception("Could not apply QuantReplay execution report %s", report.execution_id)
        finally:
            queue.task_done()


def _order_response(row: dict) -> OrderResponse:
    return OrderResponse(
        id=row["id"], client_order_id=row["client_order_id"], symbol=row["symbol"],
        side=row["side"], quantity=row["quantity"], filled_quantity=row["filled_quantity"],
        limit_price=row["limit_price"], average_fill_price=row["average_fill_price"],
        status=row["status"], created_at=row["created_at"],
    )


@app.post("/api/v1/orders", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_order(payload: OrderRequest, account: dict = Depends(authenticated_account)) -> OrderResponse:
    if not fix_gateway or not fix_gateway.connected:
        raise HTTPException(status_code=503, detail="QuantReplay is not connected")
    symbol = payload.symbol.upper()
    limit_price = payload.limit_price.quantize(Decimal("0.01"))
    reserve = (limit_price * payload.quantity).quantize(Decimal("0.01"))
    order_id = uuid.uuid4()
    fix_client_order_id = str(order_id)
    with connection() as conn:
        if settings.bank_providers:
            linked = conn.execute(
                "SELECT 1 FROM stock_bank_links WHERE account_id = %s AND active LIMIT 1",
                (account["id"],),
            ).fetchone()
            if linked is None:
                raise HTTPException(status_code=403, detail="Link a bank card before trading")
        conn.execute(
            "INSERT INTO stock_cash_accounts (account_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (account["id"],),
        )
        conn.execute(
            "SELECT account_id FROM stock_cash_accounts WHERE account_id = %s FOR UPDATE",
            (account["id"],),
        )
        existing = conn.execute(
            "SELECT * FROM stock_orders WHERE account_id = %s AND client_order_id = %s",
            (account["id"], str(payload.client_order_id)),
        ).fetchone()
        if existing:
            if (existing["symbol"] != symbol or existing["side"] != payload.side
                    or existing["quantity"] != payload.quantity or existing["limit_price"] != limit_price):
                raise HTTPException(status_code=409, detail="Client order ID was already used")
            return _order_response(existing)
        if payload.side == "BUY":
            cash = conn.execute(
                "SELECT balance, reserved FROM stock_cash_accounts WHERE account_id = %s",
                (account["id"],),
            ).fetchone()
            if cash["balance"] - cash["reserved"] < reserve:
                raise HTTPException(status_code=409, detail="Insufficient available cash")
            conn.execute(
                "UPDATE stock_cash_accounts SET reserved = reserved + %s, updated_at = now() WHERE account_id = %s",
                (reserve, account["id"]),
            )
        else:
            position = conn.execute(
                "SELECT quantity, reserved FROM stock_positions WHERE account_id = %s AND symbol = %s FOR UPDATE",
                (account["id"], symbol),
            ).fetchone()
            if position is None or position["quantity"] - position["reserved"] < payload.quantity:
                raise HTTPException(status_code=409, detail="Insufficient available shares")
            conn.execute(
                """UPDATE stock_positions SET reserved = reserved + %s, updated_at = now()
                   WHERE account_id = %s AND symbol = %s""",
                (payload.quantity, account["id"], symbol),
            )
        row = conn.execute(
            """INSERT INTO stock_orders
                 (id, account_id, client_order_id, fix_client_order_id, symbol, side, order_type, quantity,
                  limit_price, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'LIMIT', %s, %s, 'PENDING') RETURNING *""",
            (order_id, account["id"], str(payload.client_order_id), fix_client_order_id,
             symbol, payload.side,
             payload.quantity, limit_price),
        ).fetchone()
        if payload.side == "BUY":
            conn.execute(
                """INSERT INTO stock_cash_ledger
                     (entry_id, account_id, entry_type, balance_delta, reserved_delta, order_id, external_reference)
                   VALUES (%s, %s, 'RESERVE', 0, %s, %s, %s)""",
                (uuid.uuid4(), account["id"], reserve, order_id, "order-reserve:" + str(order_id)),
            )
    try:
        fix_gateway.submit_limit_order(
            fix_client_order_id, symbol, payload.side, payload.quantity, limit_price,
            str(account["id"]),
        )
    except (ConnectionError, ValueError) as error:
        with connection() as conn:
            locked = conn.execute("SELECT * FROM stock_orders WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
            if locked and locked["status"] == "PENDING":
                _release_order_reserve(conn, locked)
                conn.execute(
                    "UPDATE stock_orders SET status = 'REJECTED', updated_at = now() WHERE id = %s",
                    (order_id,),
                )
        raise HTTPException(status_code=503, detail="Order could not be sent to QuantReplay") from error
    return _order_response(row)


@app.get("/api/v1/orders", response_model=list[OrderResponse])
def list_orders(account: dict = Depends(authenticated_account)) -> list[OrderResponse]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stock_orders WHERE account_id = %s ORDER BY created_at DESC LIMIT 100",
            (account["id"],),
        ).fetchall()
    return [_order_response(row) for row in rows]


@app.get("/api/v1/market/{symbol}")
def market_view(symbol: str) -> dict[str, object]:
    symbol = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,16}", symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol")
    with connection() as conn:
        orders = conn.execute(
            """SELECT o.id, o.account_id, a.display_name, o.side, o.limit_price,
                      o.quantity - o.filled_quantity AS leaves,
                      o.created_at
               FROM stock_orders o JOIN stock_accounts a ON a.id = o.account_id
               WHERE o.symbol = %s AND (
                   o.status IN ('NEW', 'PARTIALLY_FILLED')
                   OR (o.status = 'CANCEL_PENDING' AND o.quantreplay_order_id IS NOT NULL)
               )
                 AND o.quantity > o.filled_quantity
               ORDER BY CASE WHEN o.side = 'BUY' THEN 0 ELSE 1 END,
                        CASE WHEN o.side = 'BUY' THEN o.limit_price END DESC,
                        CASE WHEN o.side = 'SELL' THEN o.limit_price END ASC,
                        o.created_at ASC""",
            (symbol,),
        ).fetchall()
        fills = conn.execute(
            """SELECT f.execution_id, f.quantity, f.price, f.executed_at, o.side, o.account_id,
                      a.display_name
               FROM stock_fills f JOIN stock_orders o ON o.id = f.order_id
               JOIN stock_accounts a ON a.id = o.account_id
               WHERE o.symbol = %s AND o.side = 'BUY'
               ORDER BY f.executed_at DESC, f.execution_id DESC LIMIT 50""",
            (symbol,),
        ).fetchall()
        positions = conn.execute(
            """SELECT a.id AS account_id, a.display_name,
                      COALESCE(p.quantity, 0) AS quantity, COALESCE(p.reserved, 0) AS reserved
               FROM stock_orders o JOIN stock_accounts a ON a.id = o.account_id
               LEFT JOIN stock_positions p ON p.account_id = a.id AND p.symbol = o.symbol
               WHERE o.symbol = %s GROUP BY a.id, a.display_name, p.quantity, p.reserved
               ORDER BY quantity DESC, a.id""",
            (symbol,),
        ).fetchall()
    # Orders are sorted best price first on each side. Each trade is already
    # represented by its buy-side fill in the most recent first result.
    last_trade = fills[0] if fills else None
    return {
        "symbol": symbol,
        "quote": {
            "best_bid": next((row["limit_price"] for row in orders if row["side"] == "BUY"), None),
            "best_ask": next((row["limit_price"] for row in orders if row["side"] == "SELL"), None),
            "last_trade_price": last_trade["price"] if last_trade else None,
            "last_trade_at": last_trade["executed_at"] if last_trade else None,
        },
        "orders": [{"id": row["id"], "account_id": row["account_id"],
                    "agent": row["display_name"] or "Agent " + str(row["account_id"])[:8], "side": row["side"],
                    "price": row["limit_price"], "quantity": row["leaves"],
                    "created_at": row["created_at"]} for row in orders],
        "fills": [{"execution_id": row["execution_id"], "account_id": row["account_id"],
                   "side": row["side"], "agent": row["display_name"] or "Agent " + str(row["account_id"])[:8],
                   "quantity": row["quantity"], "price": row["price"],
                   "executed_at": row["executed_at"]} for row in fills],
        "positions": [{"account_id": row["account_id"],
                       "agent": row["display_name"] or "Agent " + str(row["account_id"])[:8],
                       "quantity": row["quantity"], "reserved": row["reserved"]}
                      for row in positions],
    }


@app.post("/api/v1/orders/{client_order_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_order(client_order_id: uuid.UUID, account: dict = Depends(authenticated_account)) -> dict[str, str]:
    if not fix_gateway or not fix_gateway.connected:
        raise HTTPException(status_code=503, detail="QuantReplay is not connected")
    cancel_id = str(uuid.uuid4())
    with connection() as conn:
        order = conn.execute(
            """SELECT * FROM stock_orders WHERE account_id = %s AND client_order_id = %s FOR UPDATE""",
            (account["id"], str(client_order_id)),
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order["status"] in {"FILLED", "CANCELED", "REJECTED"}:
            return {"status": order["status"].lower()}
        if order["cancel_client_order_id"]:
            return {"status": "cancel_pending"}
        conn.execute(
            "UPDATE stock_orders SET cancel_client_order_id = %s, status = 'CANCEL_PENDING', updated_at = now() WHERE id = %s",
            (cancel_id, order["id"]),
        )
    try:
        fix_gateway.cancel_order(cancel_id, order["fix_client_order_id"], order["symbol"], order["side"])
    except (ConnectionError, ValueError) as error:
        with connection() as conn:
            conn.execute(
                """UPDATE stock_orders SET cancel_client_order_id = NULL, status = %s, updated_at = now()
                   WHERE id = %s AND cancel_client_order_id = %s""",
                ("PARTIALLY_FILLED" if order["filled_quantity"] else "NEW", order["id"], cancel_id),
            )
        raise HTTPException(status_code=503, detail="Cancel request could not be sent") from error
    return {"status": "cancel_pending"}


@app.post("/api/v1/admin/allocations", status_code=status.HTTP_201_CREATED)
def allocate_initial_shares(
    payload: Allocation,
    admin_token: Annotated[str | None, Header(alias="X-Stock-Admin-Token")] = None,
) -> dict[str, object]:
    if not settings.admin_token or not admin_token or not hmac.compare_digest(
        admin_token, settings.admin_token
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    symbol = payload.symbol.upper()
    with connection() as conn:
        account = conn.execute(
            "SELECT id FROM stock_accounts WHERE id = %s AND email_verified_at IS NOT NULL",
            (payload.account_id,),
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=404, detail="Verified stock account not found")
        allocation = conn.execute(
            """INSERT INTO stock_allocations (allocation_id, account_id, symbol, quantity)
               VALUES (%s, %s, %s, %s) ON CONFLICT (allocation_id) DO NOTHING
               RETURNING allocation_id""",
            (payload.allocation_id, payload.account_id, symbol, payload.quantity),
        ).fetchone()
        if allocation is None:
            previous = conn.execute(
                "SELECT account_id, symbol, quantity FROM stock_allocations WHERE allocation_id = %s",
                (payload.allocation_id,),
            ).fetchone()
            if (
                previous is None
                or previous["account_id"] != payload.account_id
                or previous["symbol"] != symbol
                or previous["quantity"] != payload.quantity
            ):
                raise HTTPException(status_code=409, detail="Allocation ID was already used")
            position = conn.execute(
                "SELECT quantity, reserved FROM stock_positions WHERE account_id = %s AND symbol = %s",
                (payload.account_id, symbol),
            ).fetchone()
            return {
                "allocation_id": payload.allocation_id,
                "account_id": payload.account_id,
                "symbol": symbol,
                "allocated_quantity": payload.quantity,
                "quantity": position["quantity"],
                "reserved": position["reserved"],
                "replayed": True,
            }
        row = conn.execute(
            """INSERT INTO stock_positions (account_id, symbol, quantity)
               VALUES (%s, %s, %s)
               ON CONFLICT (account_id, symbol) DO UPDATE
                 SET quantity = stock_positions.quantity + EXCLUDED.quantity,
                     updated_at = now()
               RETURNING quantity, reserved""",
            (payload.account_id, symbol, payload.quantity),
        ).fetchone()
    return {
        "allocation_id": payload.allocation_id,
        "account_id": payload.account_id,
        "symbol": symbol,
        "allocated_quantity": payload.quantity,
        "quantity": row["quantity"],
        "reserved": row["reserved"],
        "replayed": False,
    }
