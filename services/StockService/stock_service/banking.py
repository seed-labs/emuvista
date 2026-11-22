"""Bank Open Banking links, card balance queries, and idempotent deposits."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cryptography.fernet import Fernet

from .db import connection
from .settings import settings


class BankRequestError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _provider(alias: str) -> dict:
    provider = settings.bank_providers.get(alias)
    if not isinstance(provider, dict):
        raise ValueError("This bank is not connected to Stock Service")
    return provider


def _request(url: str, *, method="GET", headers=None, body=None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as error:
        message = error.read(8192).decode(errors="replace")
        raise BankRequestError(error.code, message or "Bank request failed") from None
    except (OSError, TimeoutError, ValueError) as error:
        raise BankRequestError(503, "Bank is temporarily unavailable") from error


def _token(provider: dict, fields: dict[str, str]) -> dict:
    credentials = base64.b64encode(
        (provider["clientId"] + ":" + provider["clientSecret"]).encode()
    ).decode()
    request = urllib.request.Request(
        provider["apiURL"].rstrip("/") + "/oauth2/token",
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Authorization": "Basic " + credentials,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as error:
        raise BankRequestError(error.code, "Bank authorization failed") from None
    except (OSError, TimeoutError, ValueError) as error:
        raise BankRequestError(503, "Bank authorization is temporarily unavailable") from error


def _bank(provider: dict, path: str, access_token: str, *, method="GET", body=None, extra_headers=None) -> dict:
    headers = {"Authorization": "Bearer " + access_token, **(extra_headers or {})}
    return _request(provider["apiURL"].rstrip("/") + path, method=method,
                    headers=headers, body=body)


def _fernet() -> Fernet:
    if not settings.token_encryption_key:
        raise RuntimeError("Stock Service token encryption is not configured")
    return Fernet(settings.token_encryption_key.encode())


def begin_link(account: dict, bank_alias: str, card_id: str, card_number: str) -> dict:
    if not re.fullmatch(r"[0-9]{16,19}", card_number):
        raise ValueError("Bank card could not be verified")
    provider = _provider(bank_alias)
    client_token = _token(provider, {
        "grant_type": "client_credentials", "scope": "openbanking:consents"
    })["access_token"]
    consent = _bank(provider, "/openbanking/account-access-consents/cards", client_token,
                    method="POST", body={"cardNumber": card_number, "walletOwnerEmail": account["email"]})
    if str(consent.get("cardId")) != str(card_id):
        raise ValueError("Bank card does not match the selected card")
    redirect_uri = provider["redirectURIs"][0]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    with connection() as conn:
        conn.execute(
            """INSERT INTO stock_bank_link_attempts
                 (state, account_id, bank_alias, card_id, consent_id, verifier, redirect_uri, expires_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (state, account["id"], bank_alias, str(card_id), consent["consentId"],
             verifier, redirect_uri, expires_at),
        )
    authorization = urllib.parse.urlencode({
        "response_type": "code", "client_id": provider["clientId"],
        "redirect_uri": redirect_uri, "scope": "openbanking:cards.read openbanking:payments",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "consent_id": consent["consentId"],
    })
    return {"state": state,
            "authorization_url": provider["apiURL"].rstrip("/") + "/oauth2/authorize?" + authorization,
            "redirect_uri": redirect_uri, "card_id": str(card_id), "bank": bank_alias}


def complete_link(account: dict, state: str, code: str) -> dict:
    with connection() as conn:
        attempt = conn.execute(
            """SELECT * FROM stock_bank_link_attempts
               WHERE state = %s AND account_id = %s FOR UPDATE""",
            (state, account["id"]),
        ).fetchone()
        if attempt is None or attempt["expires_at"] <= datetime.now(timezone.utc):
            raise ValueError("Bank linking request expired or belongs to another account")
        conn.execute("DELETE FROM stock_bank_link_attempts WHERE state = %s", (state,))
    provider = _provider(attempt["bank_alias"])
    tokens = _token(provider, {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": attempt["redirect_uri"], "code_verifier": attempt["verifier"],
    })
    access_token = tokens["access_token"]
    card = _bank(provider, "/openbanking/cards/current", access_token)
    if (str(card.get("cardId")) != attempt["card_id"]
            or card.get("currency") not in provider["currencies"]
            or card.get("currency") != "USD"):
        _bank(provider, "/openbanking/cards/current/revoke", access_token, method="POST", body={})
        raise ValueError("Bank authorization returned another card or currency")
    link_id = uuid.uuid4()
    encrypted = _fernet().encrypt(json.dumps(tokens).encode()).decode()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(tokens.get("expires_in", 0))))
    try:
        with connection() as conn:
            conn.execute(
                """INSERT INTO stock_bank_links
                     (id, account_id, bank_alias, card_id, card_name, masked_card,
                      currency, encrypted_tokens, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (link_id, account["id"], attempt["bank_alias"], attempt["card_id"],
                 card["name"], card["maskedCard"], card["currency"], encrypted, expires_at),
            )
    except Exception:
        try:
            _bank(provider, "/openbanking/cards/current/revoke", access_token, method="POST", body={})
        except BankRequestError:
            pass
        raise
    return {"id": str(link_id), "bank": attempt["bank_alias"], "name": card["name"],
            "masked_card": card["maskedCard"], "currency": card["currency"],
            "balance_minor": card["balanceMinor"]}


def _link_access(link: dict) -> tuple[dict, str]:
    provider = _provider(link["bank_alias"])
    tokens = json.loads(_fernet().decrypt(link["encrypted_tokens"].encode()))
    if link["expires_at"] <= datetime.now(timezone.utc) + timedelta(seconds=30):
        if not tokens.get("refresh_token"):
            raise BankRequestError(401, "Reconnect this bank card to continue")
        old_tokens = tokens
        tokens = _token(provider, {"grant_type": "refresh_token", "refresh_token": old_tokens["refresh_token"]})
        if not tokens.get("refresh_token"):
            tokens["refresh_token"] = old_tokens["refresh_token"]
        encrypted = _fernet().encrypt(json.dumps(tokens).encode()).decode()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(tokens.get("expires_in", 0))))
        with connection() as conn:
            conn.execute(
                "UPDATE stock_bank_links SET encrypted_tokens = %s, expires_at = %s WHERE id = %s AND active",
                (encrypted, expires_at, link["id"]),
            )
    return provider, tokens["access_token"]


def list_links(account: dict) -> list[dict]:
    with connection() as conn:
        links = conn.execute(
            """SELECT id, bank_alias, card_id, card_name, masked_card, currency,
                      encrypted_tokens, expires_at, active
               FROM stock_bank_links WHERE account_id = %s AND active ORDER BY created_at""",
            (account["id"],),
        ).fetchall()
    result = []
    for link in links:
        item = {"id": str(link["id"]), "bank": link["bank_alias"], "card_id": link["card_id"],
                "name": link["card_name"], "masked_card": link["masked_card"],
                "currency": link["currency"].strip(), "balance_minor": None, "available": False}
        try:
            provider, access = _link_access(link)
            card = _bank(provider, "/openbanking/cards/current", access)
            if (str(card.get("cardId")) == link["card_id"]
                    and card.get("currency") == link["currency"].strip()):
                item["balance_minor"] = card.get("balanceMinor")
                item["available"] = True
        except BankRequestError:
            pass
        result.append(item)
    return result


def unlink(account: dict, link_id: uuid.UUID) -> None:
    with connection() as conn:
        link = conn.execute(
            """SELECT * FROM stock_bank_links
               WHERE id = %s AND account_id = %s AND active FOR UPDATE""",
            (link_id, account["id"]),
        ).fetchone()
        if link is None:
            raise ValueError("Linked bank card not found")
        pending = conn.execute(
            """SELECT 1 FROM stock_cash_deposits
               WHERE bank_link_id = %s AND status IN ('REQUESTED', 'PENDING', 'NEEDS_REVIEW') LIMIT 1""",
            (link_id,),
        ).fetchone()
        if pending:
            raise ValueError("A pending bank deposit must be reconciled before unlinking this card")
    provider, access = _link_access(link)
    _bank(provider, "/openbanking/cards/current/revoke", access, method="POST", body={})
    with connection() as conn:
        conn.execute(
            "UPDATE stock_bank_links SET active = FALSE, encrypted_tokens = '' WHERE id = %s",
            (link_id,),
        )


def _deposit_row(account_id: uuid.UUID, deposit_id: uuid.UUID, link_id: uuid.UUID,
                 amount: Decimal) -> dict:
    with connection() as conn:
        conn.execute("SELECT account_id FROM stock_cash_accounts WHERE account_id = %s FOR UPDATE", (account_id,))
        row = conn.execute("SELECT * FROM stock_cash_deposits WHERE id = %s FOR UPDATE", (deposit_id,)).fetchone()
        if row:
            if (row["account_id"] != account_id or row["bank_link_id"] != link_id
                    or row["amount"] != amount):
                raise ValueError("Deposit ID was already used for another request")
            return row
        link = conn.execute(
            """SELECT id, currency FROM stock_bank_links
               WHERE id = %s AND account_id = %s AND active""",
            (link_id, account_id),
        ).fetchone()
        if link is None:
            raise ValueError("Linked bank card not found")
        conn.execute("INSERT INTO stock_cash_accounts (account_id) VALUES (%s) ON CONFLICT DO NOTHING", (account_id,))
        row = conn.execute(
            """INSERT INTO stock_cash_deposits
                 (id, account_id, bank_link_id, amount, currency, status)
               VALUES (%s, %s, %s, %s, %s, 'REQUESTED') RETURNING *""",
            (deposit_id, account_id, link_id, amount, link["currency"]),
        ).fetchone()
        return row


def _confirm_deposit(account_id: uuid.UUID, deposit_id: uuid.UUID, bank_transaction_id: int) -> dict:
    external_reference = "bank-deposit:" + str(deposit_id)
    with connection() as conn:
        deposit = conn.execute(
            "SELECT * FROM stock_cash_deposits WHERE id = %s AND account_id = %s FOR UPDATE",
            (deposit_id, account_id),
        ).fetchone()
        if deposit is None:
            raise ValueError("Deposit not found")
        entry = conn.execute(
            """INSERT INTO stock_cash_ledger
                 (entry_id, account_id, entry_type, balance_delta, external_reference)
               VALUES (%s, %s, 'DEPOSIT', %s, %s)
               ON CONFLICT DO NOTHING RETURNING entry_id""",
            (deposit_id, account_id, deposit["amount"], external_reference),
        ).fetchone()
        if entry:
            conn.execute(
                """INSERT INTO stock_cash_accounts (account_id, balance) VALUES (%s, %s)
                   ON CONFLICT (account_id) DO UPDATE SET
                     balance = stock_cash_accounts.balance + EXCLUDED.balance,
                     updated_at = now()""",
                (account_id, deposit["amount"]),
            )
        conn.execute(
            """UPDATE stock_cash_deposits SET status = 'COMPLETED', bank_transaction_id = %s,
                 updated_at = now() WHERE id = %s""",
            (bank_transaction_id, deposit_id),
        )
        cash = conn.execute(
            "SELECT balance, reserved FROM stock_cash_accounts WHERE account_id = %s",
            (account_id,),
        ).fetchone()
    return {"id": str(deposit_id), "status": "COMPLETED", "amount": deposit["amount"],
            "currency": deposit["currency"].strip(), "balance": cash["balance"],
            "available": cash["balance"] - cash["reserved"]}


def _reconcile_deposit(account: dict, deposit_id: uuid.UUID) -> dict:
    with connection() as conn:
        deposit = conn.execute(
            """SELECT * FROM stock_cash_deposits
               WHERE id = %s AND account_id = %s FOR UPDATE""",
            (deposit_id, account["id"]),
        ).fetchone()
        if deposit is None:
            raise ValueError("Deposit not found")
        if deposit["status"] == "COMPLETED":
            cash = conn.execute(
                "SELECT balance, reserved FROM stock_cash_accounts WHERE account_id = %s",
                (account["id"],),
            ).fetchone()
            return {"id": str(deposit_id), "status": "COMPLETED", "amount": deposit["amount"],
                    "currency": deposit["currency"].strip(), "balance": cash["balance"],
                    "available": cash["balance"] - cash["reserved"]}
        if deposit["status"] == "DECLINED":
            return {"id": str(deposit_id), "status": "DECLINED", "amount": deposit["amount"],
                    "currency": deposit["currency"].strip()}
        if deposit["status"] == "NEEDS_REVIEW":
            return {"id": str(deposit_id), "status": "NEEDS_REVIEW", "amount": deposit["amount"],
                    "currency": deposit["currency"].strip()}
        link = conn.execute(
            """SELECT * FROM stock_bank_links
               WHERE id = %s AND account_id = %s AND active""",
            (deposit["bank_link_id"], account["id"]),
        ).fetchone()
    if link is None:
        raise ValueError("The linked card was removed before this deposit was reconciled")
    provider, access = _link_access(link)
    request_id = str(deposit_id)
    expected = {
        "cardId": link["card_id"], "amount": format(deposit["amount"], ".2f"),
        "currency": deposit["currency"].strip(), "payeeId": "stock:" + str(account["id"]),
        "payeeName": "Stock Service", "description": "Cash deposit to Stock Service",
    }
    redirect = urllib.parse.urlsplit(provider["redirectURIs"][0])
    expected_platform = redirect.scheme + "://" + redirect.netloc
    try:
        payment = _bank(provider, "/openbanking/payments/" + request_id,
                        _token(provider, {"grant_type": "client_credentials",
                                          "scope": "openbanking:payments"})["access_token"])
    except BankRequestError as error:
        # The Bank consumer reports an unknown payment ID as HTTP 409 with
        # this specific error code (rather than HTTP 404). Treat only that
        # response as "not created yet" so the idempotent POST can start it.
        try:
            missing_payment = (
                error.status == 409
                and json.loads(str(error)).get("code")
                == "error.msg.consumer.openbanking.payment.invalid"
            )
        except (TypeError, ValueError):
            missing_payment = False
        if error.status != 404 and not missing_payment:
            return {"id": request_id, "status": "PENDING", "amount": deposit["amount"],
                    "currency": deposit["currency"].strip()}
        try:
            payment = _bank(provider, "/openbanking/payments", access, method="POST", body=expected,
                            extra_headers={"Idempotency-Key": request_id})
        except BankRequestError:
            with connection() as conn:
                conn.execute(
                    "UPDATE stock_cash_deposits SET status = 'PENDING', updated_at = now() WHERE id = %s",
                    (deposit_id,),
                )
            return {"id": request_id, "status": "PENDING", "amount": deposit["amount"],
                    "currency": deposit["currency"].strip()}
    matches = (
        str(payment.get("id")) == request_id
        and str(payment.get("clientId")) == str(provider["clientId"])
        and payment.get("platform") == expected_platform
        and payment.get("payeeId") == expected["payeeId"]
        and payment.get("payeeName") == expected["payeeName"]
        and payment.get("description") == expected["description"]
        and payment.get("currency") == expected["currency"]
        and Decimal(str(payment.get("amount", "0"))) == deposit["amount"]
    )
    if not matches:
        with connection() as conn:
            conn.execute(
                "UPDATE stock_cash_deposits SET status = 'NEEDS_REVIEW', updated_at = now() WHERE id = %s",
                (deposit_id,),
            )
        return {"id": request_id, "status": "NEEDS_REVIEW", "amount": deposit["amount"],
                "currency": deposit["currency"].strip()}
    if payment.get("status") == "declined":
        with connection() as conn:
            conn.execute("UPDATE stock_cash_deposits SET status = 'DECLINED', updated_at = now() WHERE id = %s",
                         (deposit_id,))
        return {"id": request_id, "status": "DECLINED", "amount": deposit["amount"],
                "currency": deposit["currency"].strip()}
    transaction_id = payment.get("transactionId")
    if payment.get("status") != "completed" or not isinstance(transaction_id, int):
        with connection() as conn:
            conn.execute("UPDATE stock_cash_deposits SET status = 'PENDING', updated_at = now() WHERE id = %s",
                         (deposit_id,))
        return {"id": request_id, "status": "PENDING", "amount": deposit["amount"],
                "currency": deposit["currency"].strip()}
    with connection() as conn:
        conn.execute(
            "UPDATE stock_cash_deposits SET status = 'PENDING', bank_transaction_id = %s, updated_at = now() WHERE id = %s",
            (transaction_id, deposit_id),
        )
    return _confirm_deposit(account["id"], deposit_id, transaction_id)


def deposit(account: dict, deposit_id: uuid.UUID, link_id: uuid.UUID, amount: Decimal) -> dict:
    amount = amount.quantize(Decimal("0.01"))
    row = _deposit_row(account["id"], deposit_id, link_id, amount)
    if row["status"] == "COMPLETED":
        return _reconcile_deposit(account, deposit_id)
    return _reconcile_deposit(account, deposit_id)


def deposit_status(account: dict, deposit_id: uuid.UUID) -> dict:
    return _reconcile_deposit(account, deposit_id)
