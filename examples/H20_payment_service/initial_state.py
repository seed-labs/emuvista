"""Translate the example's user configuration into an official Komunitin bundle."""

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


COMMUNITY = "SEED"
COMMUNITY_NAME = "Seed City"
CENT = Decimal("0.01")
MAX_MINOR_UNITS = 2**63 - 1


def load_users(path: Path, admin_email: str) -> list[dict]:
    """Validate configuration before rendering or replacing any compiled output."""
    data = json.loads(path.read_text(), parse_float=Decimal)
    if not isinstance(data, list):
        raise ValueError("users.json must contain a list of users")
    if len(data) > 10000:
        raise ValueError("at most 10000 initial users are supported")
    users, emails = [], {admin_email.lower()}
    for index, item in enumerate(data, 1):
        prefix = f"user {index}"
        if not isinstance(item, dict) or set(item) != {"name", "email", "password", "balance"}:
            raise ValueError(f"{prefix} requires exactly name, email, password and balance")
        name, email, password = item["name"], item["email"], item["password"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 255:
            raise ValueError(f"{prefix}: name must contain 1 to 255 characters")
        if not isinstance(email, str) or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email.strip()):
            raise ValueError(f"{prefix}: invalid email")
        email = email.strip().lower()
        if email in emails:
            raise ValueError(f"{prefix}: duplicate or reserved administrator email")
        emails.add(email)
        if not isinstance(password, str) or len(password) < 8 or len(password.encode()) > 72 or "\x00" in password:
            raise ValueError(f"{prefix}: password requires at least 8 characters and at most 72 UTF-8 bytes")
        try:
            if isinstance(item["balance"], bool):
                raise InvalidOperation
            balance = Decimal(str(item["balance"]))
            if (not balance.is_finite() or balance < 0
                    or balance != balance.quantize(CENT) or balance * 100 > MAX_MINOR_UNITS):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            raise ValueError(f"{prefix}: balance must be nonnegative, with at most two decimal places") from None
        users.append({"name": name.strip(), "email": email, "password": password,
                      "balance": format(balance.quantize(CENT), "f")})
    if sum(Decimal(user["balance"]) for user in users) * 100 > MAX_MINOR_UNITS:
        raise ValueError("total initial balances exceed the supported amount")
    return users


def _identifier(kind: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"emuvista:h20:{COMMUNITY}:{kind}:{key}"))


def build_bundle(users: list[dict], admin_email: str) -> bytes:
    """Use documented CSV records and funding history; never modify a database."""
    try:
        import bcrypt
    except ImportError:
        raise RuntimeError("Install requirements.txt from the repository root") from None

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    total = sum((Decimal(user["balance"]) for user in users), Decimal(0))
    treasury = COMMUNITY + "0000"
    community = [{"id": _identifier("community", COMMUNITY), "code": COMMUNITY,
                  "name": COMMUNITY_NAME, "status": "active", "description": "Payment simulation community",
                  "access": "public", "adminUsers": admin_email,
                  "createdAt": timestamp, "updatedAt": timestamp,
                  "settings.requireAcceptTerms": "false", "settings.minOffers": 0,
                  "settings.minNeeds": 0, "settings.enableGroupEmail": "false",
                  "settings.defaultGroupEmailFrequency": "never"}]
    currency = [{"id": _identifier("currency", COMMUNITY), "code": COMMUNITY,
                 "adminUser": admin_email, "name": "Seed Credit", "namePlural": "Seed Credits",
                 "symbol": "SC", "decimals": 2, "scale": 2,
                 "rateNumerator": 1, "rateDenominator": 1,
                 "createdAt": timestamp, "updatedAt": timestamp,
                 "settings.defaultInitialCreditLimit": "0.00",
                 "settings.defaultAllowPayments": "true", "settings.defaultAllowPaymentRequests": "true",
                 "settings.defaultAllowSimplePayments": "true", "settings.defaultAllowSimplePaymentRequests": "true",
                 "settings.defaultAcceptPaymentsAutomatically": "false",
                 "settings.defaultAcceptPaymentsAfter": "false", "settings.defaultHideBalance": "false",
                 "settings.enableExternalPayments": "false", "settings.enableExternalPaymentRequests": "false"}]
    identities = [{"email": admin_email, "name": "Community administrator", "status": "active",
                   "passwordHash": "", "language": "en", "createdAt": timestamp, "updatedAt": timestamp}]
    members, accounts, owners, transfers = [], [], [], []

    def account(code, name, email, balance, credit, kind):
        members.append({"id": _identifier("member", email), "code": code, "name": name,
                        "type": kind, "status": "active", "access": "group", "description": "",
                        "createdAt": timestamp, "updatedAt": timestamp, "contact.email": email})
        accounts.append({"id": _identifier("account", email), "code": code,
                         "balance": format(balance, ".2f"), "creditLimit": format(credit, ".2f"),
                         "createdAt": timestamp, "updatedAt": timestamp,
                         "settings.acceptPaymentsAutomatically": "false"})
        owners.append({"member": code, "user": email, "notifications.myAccount": "false",
                       "notifications.group": "false", "emails.myAccount": "false", "emails.group": "never"})

    account(treasury, "Community treasury", admin_email, -total, total, "public")
    for index, user in enumerate(users, 1):
        code = COMMUNITY + f"{index:04d}"
        identities.append({"email": user["email"], "name": user["name"], "status": "active",
                           "passwordHash": bcrypt.hashpw(user["password"].encode(), bcrypt.gensalt(rounds=10)).decode(),
                           "language": "en", "createdAt": timestamp, "updatedAt": timestamp})
        balance = Decimal(user["balance"])
        account(code, user["name"], user["email"], balance, Decimal(0), "personal")
        if balance > 0:
            transfers.append({"id": _identifier("funding", user["email"]), "payer": treasury,
                              "payee": code, "user": admin_email, "amount": user["balance"],
                              "description": "Initial wallet allocation", "createdAt": timestamp, "updatedAt": timestamp})

    files = {"community.csv": community, "currency.csv": currency, "users.csv": identities,
             "members.csv": members, "accounts.csv": accounts, "member-users.csv": owners}
    if transfers:
        files["transfers.csv"] = transfers
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, rows in files.items():
            content = io.StringIO(newline="")
            writer = csv.DictWriter(content, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(filename, content.getvalue())
        archive.comment = json.dumps({"config_sha256": _fingerprint(users, admin_email)}).encode()
    return output.getvalue()


def _fingerprint(users: list[dict], admin_email: str) -> str:
    return hashlib.sha256(json.dumps({"community": COMMUNITY, "admin": admin_email, "users": users},
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare_bundle(users: list[dict], admin_email: str, state: Path | None = None) -> bytes:
    """Prepare bytes without writing files; reuse compiled state when available."""
    if state is None:
        return build_bundle(users, admin_email)
    state = state.expanduser().resolve()
    bundle = state / 'initial-data.zip'
    legacy_bundle, legacy_metadata = state / 'h20-initial-data.zip', state / 'h20-initial-data.json'
    if not bundle.exists():
        if legacy_bundle.exists() or legacy_metadata.exists():
            if not legacy_bundle.is_file() or not legacy_metadata.is_file():
                raise ValueError('incomplete initial data cache; restore both H20 initialization files')
            bundle = legacy_bundle
        else:
            return build_bundle(users, admin_email)
    data = bundle.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise ValueError('cached initial data checksum mismatch')
        if archive.comment:
            saved = json.loads(archive.comment)
        else:
            # Existing installations used a separate metadata file. Keep their
            # exact ZIP bytes so the startup checkpoint remains unchanged.
            if not legacy_metadata.is_file():
                raise ValueError('saved initial data has no H20 configuration identity')
            saved = json.loads(legacy_metadata.read_text())
            if saved.get('bundle_sha256') != hashlib.sha256(data).hexdigest():
                raise ValueError('cached initial data checksum mismatch')
    if saved.get('config_sha256') != _fingerprint(users, admin_email):
        raise ValueError('initial users changed; use a new state directory to start a new experiment')
    return data
