"""Validate payment configuration and prepare Komunitin initialization data."""

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from .templates import FX_SETUP


CENT = Decimal("0.01")
MAX_MINOR_UNITS = 2**63 - 1


def _validate_users(data, admin_email):
    if not isinstance(data, list):
        raise ValueError("each group must contain a list of users")
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


def load_configuration(source: str | Path | dict, admin_email: str) -> dict:
    """Read a JSON file or copy a mapping into a validated configuration."""
    data = source if isinstance(source, dict) else json.loads(
        Path(source).expanduser().read_text(), parse_float=Decimal)
    if not isinstance(data, dict) or set(data) != {'groups', 'trustlines'}:
        raise ValueError('configuration requires groups and trustlines')
    if not isinstance(data['groups'], list) or not 1 <= len(data['groups']) <= 100:
        raise ValueError('configuration requires 1 to 100 groups')
    groups, codes, identities = [], set(), {}
    for group in data['groups']:
        if not isinstance(group, dict) or set(group) != {'code','name','currency','users'}:
            raise ValueError('each group requires code, name, currency and users')
        code, name, currency = group['code'], group['name'], group['currency']
        if not isinstance(code, str) or not re.fullmatch('[A-Z0-9]{4}', code) or code in codes:
            raise ValueError('group codes must be unique four-character uppercase letters or digits')
        codes.add(code)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 255:
            raise ValueError('invalid group name')
        if not isinstance(currency, dict) or set(currency) != {'name','symbol','rate'}:
            raise ValueError('each currency requires name, symbol and rate')
        if not isinstance(currency['name'], str) or not 1 <= len(currency['name']) <= 254:
            raise ValueError('invalid currency name')
        if not isinstance(currency['symbol'], str) or not 1 <= len(currency['symbol']) <= 3:
            raise ValueError('currency symbol requires 1 to 3 characters')
        try:
            if isinstance(currency['rate'], bool): raise ValueError
            rate = Fraction(Decimal(str(currency['rate'])))
            if rate <= 0 or max(rate.numerator, rate.denominator) > 2147483647: raise ValueError
        except (ValueError, InvalidOperation, OverflowError):
            raise ValueError('currency rate must be positive and exactly representable as a supported ratio') from None
        users = _validate_users(group['users'], admin_email)
        for user in users:
            previous = identities.setdefault(user['email'], user['password'])
            if previous != user['password']:
                raise ValueError('the same email must use the same password in every group')
        groups.append({'code':code,'name':name.strip(),'currency':{'name':currency['name'],
                       'symbol':currency['symbol'],'rate':format(Decimal(str(currency['rate'])), 'f')},'users':users})
    reserved = {_treasury_email(group['code'],admin_email) for group in groups}
    if any(user['email'] in reserved for group in groups for user in group['users']):
        raise ValueError('user email conflicts with an automatically generated community treasury')
    if not isinstance(data['trustlines'], list):
        raise ValueError('trustlines must be a list')
    lines, pairs = [], set()
    for line in data['trustlines']:
        if not isinstance(line, dict) or set(line) != {'from','to','limit'}:
            raise ValueError('each trustline requires from, to and limit')
        source, target = line['from'], line['to']
        if (not isinstance(source,str) or not isinstance(target,str) or source not in codes or target not in codes
                or source == target or (source,target) in pairs):
            raise ValueError('trustlines require two distinct configured groups and unique directions')
        try:
            if isinstance(line['limit'], bool): raise ValueError
            limit = Decimal(str(line['limit']))
            if not limit.is_finite() or limit < 0 or limit != limit.quantize(CENT) or limit*100 > 2**53-1: raise ValueError
        except (ValueError, InvalidOperation):
            raise ValueError('trustline limit must be a supported nonnegative amount with at most two decimal places') from None
        pairs.add((source,target))
        lines.append({'from':source,'to':target,'limit':format(limit.quantize(CENT),'f')})
    return {'groups':groups,'trustlines':lines}


def _identifier(kind: str, key: str, code: str) -> str:
    # Preserve the historical UUID namespace for existing payment state.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"emuvista:h20:{code}:{kind}:{key}"))


def _treasury_email(code, admin_email):
    return 'treasury.'+code.lower()+'@'+admin_email.split('@',1)[1]


def build_bundle(users: list[dict], admin_email: str, group: dict) -> bytes:
    """Use documented CSV records and funding history; never modify a database."""
    try:
        import bcrypt
    except ImportError:
        raise RuntimeError("Install requirements.txt from the repository root") from None

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    code = group['code']
    group_name = group['name']
    money = group['currency']
    rate = Fraction(Decimal(money['rate']))
    identifier = lambda kind, key: _identifier(kind,key,code)
    total = sum((Decimal(user["balance"]) for user in users), Decimal(0))
    treasury = code + "0000"
    community = [{"id": identifier("community", code), "code": code,
                  "name": group_name, "status": "active", "description": "Payment simulation community",
                  "access": "public", "adminUsers": admin_email,
                  "createdAt": timestamp, "updatedAt": timestamp,
                  "settings.requireAcceptTerms": "false", "settings.minOffers": 0,
                  "settings.minNeeds": 0, "settings.enableGroupEmail": "false",
                  "settings.allowAnonymousMemberList": 'true',
                  "settings.defaultGroupEmailFrequency": "never"}]
    currency = [{"id": identifier("currency", code), "code": code,
                 "adminUser": admin_email, "name": money['name'], "namePlural": money['name']+'s',
                 "symbol": money['symbol'], "decimals": 2, "scale": 2,
                 "rateNumerator": rate.numerator, "rateDenominator": rate.denominator,
                 "createdAt": timestamp, "updatedAt": timestamp,
                 "settings.defaultInitialCreditLimit": "0.00",
                 "settings.defaultAllowPayments": "true", "settings.defaultAllowPaymentRequests": "true",
                 "settings.defaultAllowSimplePayments": "true", "settings.defaultAllowSimplePaymentRequests": "true",
                 "settings.defaultAcceptPaymentsAutomatically": "false",
                 "settings.defaultAcceptPaymentsAfter": "false", "settings.defaultHideBalance": "false",
                 "settings.defaultAllowExternalPayments": 'true',
                 "settings.defaultAllowExternalPaymentRequests": 'true',
                 "settings.externalTraderCreditLimit": group.get('external_credit','0.00'),
                 "settings.externalTraderMaximumBalance": 'false',
                 "settings.enableExternalPayments": 'true',
                 "settings.enableExternalPaymentRequests": 'true'}]
    identities = [{"email": admin_email, "name": "Community administrator", "status": "active",
                   "passwordHash": "", "language": "en", "createdAt": timestamp, "updatedAt": timestamp}]
    members, accounts, owners, transfers = [], [], [], []

    def account(code, name, email, balance, credit, kind):
        members.append({"id": identifier("member", email), "code": code, "name": name,
                        "type": kind, "status": "active", "access": 'public', "description": "",
                        "createdAt": timestamp, "updatedAt": timestamp, "contact.email": email})
        accounts.append({"id": identifier("account", email), "code": code,
                         "balance": format(balance, ".2f"), "creditLimit": format(credit, ".2f"),
                         "createdAt": timestamp, "updatedAt": timestamp,
                         "settings.acceptPaymentsAutomatically": "false"})
        owners.append({"member": code, "user": email, "notifications.myAccount": "false",
                       "notifications.group": "false", "emails.myAccount": "false", "emails.group": "never"})

    account(treasury, "Community treasury", admin_email, -total, total, "public")
    for index, user in enumerate(users, 1):
        member_code = code + f"{index:04d}"
        identities.append({"email": user["email"], "name": user["name"], "status": "active",
                           "passwordHash": bcrypt.hashpw(user["password"].encode(), bcrypt.gensalt(rounds=10)).decode(),
                           "language": "en", "createdAt": timestamp, "updatedAt": timestamp})
        balance = Decimal(user["balance"])
        account(member_code, user["name"], user["email"], balance, Decimal(0), "personal")
        if balance > 0:
            transfers.append({"id": identifier("funding", user["email"]), "payer": treasury,
                              "payee": member_code, "user": admin_email, "amount": user["balance"],
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


def build_initial_data(configuration, admin_email):
    output = io.BytesIO()
    names = []
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for group in configuration['groups']:
            name = 'group-'+group['code']+'.zip'
            external_credit = sum((Decimal(line['limit']) for line in configuration['trustlines']
                                   if line['from']==group['code']),Decimal(0))
            archive.writestr(name,build_bundle(group['users'],_treasury_email(group['code'],admin_email),
                             {**group,'external_credit':format(external_credit,'.2f')}))
            names.append(name)
        manifest = {'format':'seedemu-payment-v1','bundles':names}
        if configuration['trustlines']:
            script = 'const trustlines = '+json.dumps(configuration['trustlines'])+';\n'
            script += FX_SETUP
            archive.writestr('after-import.mjs',script)
            manifest['after_import'] = 'after-import.mjs'
        archive.writestr('payment-initialization.json',json.dumps(manifest))
        archive.comment = json.dumps({'config_sha256':_fingerprint(configuration,admin_email)}).encode()
    return output.getvalue()


def _fingerprint(users: dict | list[dict], admin_email: str) -> str:
    return hashlib.sha256(json.dumps({"admin": admin_email, "configuration": users},
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare_bundle(users: dict, admin_email: str, state: Path | None = None) -> bytes:
    """Prepare bytes without writing files; reuse compiled state when available."""
    if state is None:
        return build_initial_data(users, admin_email)
    state = state.expanduser().resolve()
    bundle = state / 'initial-data.zip'
    legacy_bundle, legacy_metadata = state / 'h20-initial-data.zip', state / 'h20-initial-data.json'
    if not bundle.exists():
        if legacy_bundle.exists() or legacy_metadata.exists():
            if not legacy_bundle.is_file() or not legacy_metadata.is_file():
                raise ValueError('incomplete initial data cache; restore both legacy initialization files')
            bundle = legacy_bundle
        else:
            return build_initial_data(users, admin_email)
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
                raise ValueError('saved initial data has no configuration identity')
            saved = json.loads(legacy_metadata.read_text())
            if saved.get('bundle_sha256') != hashlib.sha256(data).hexdigest():
                raise ValueError('cached initial data checksum mismatch')
    if saved.get('config_sha256') != _fingerprint(users, admin_email):
        raise ValueError('initial configuration changed; use a new state directory to start a new experiment')
    return data
