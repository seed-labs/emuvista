"""One-year simulated domain registration with a durable no-repeat journal."""

from decimal import Decimal
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPCookieProcessor,
    ProxyHandler,
    Request,
    build_opener,
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Customer:
    def __init__(self, config):
        self.origin = config["registrar_url"].rstrip("/")
        self.cookies = CookieJar()
        self.http = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(self.cookies), NoRedirect()
        )
        self.request("/")
        self.api(
            "guest/client/login",
            {"email": config["email"], "password": config["password"]},
        )

    def request(self, path, fields=None):
        headers = {}
        for cookie in self.cookies:
            if cookie.name in ("fossbilling_csrf", "csrf_token"):
                headers["X-CSRF-Token"] = unquote(cookie.value)
        body = None if fields is None else urlencode(fields).encode()
        with self.http.open(
            Request(self.origin + path, data=body, headers=headers), timeout=30
        ) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Response exceeds limit")
            return raw.decode()

    def api(self, path, fields):
        response = json.loads(self.request("/api/" + path, fields))
        if response.get("error"):
            raise ValueError("Registrar rejected request")
        return response["result"]


class PaymentForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "iframe" and "srcdoc" in attrs:
            nested = PaymentForm()
            nested.feed(attrs["srcdoc"])
            self.action, self.fields = nested.action, nested.fields
        elif tag == "form":
            self.action = attrs.get("action")
        elif tag == "input" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")


def domain_name(value):
    domain = value.lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,63}", domain):
        raise ValueError("Provide a second-level ASCII domain, such as example.com")
    return domain


def journal_path(config, domain):
    key = hashlib.sha256(
        (config["registrar_url"] + "\n" + config["email"] + "\n" + domain).encode()
    ).hexdigest()
    root = Path(config.get("state_dir", "/home/emuvista-agent/domain-purchases"))
    root.mkdir(parents=True, exist_ok=True)
    return root / (key + ".json")


def save(path, state):
    temporary = path.with_suffix(".tmp")
    with open(temporary, "w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def report(state):
    # Invoice hashes and signed forms are bearer secrets, never return them.
    return {
        key: state[key]
        for key in (
            "domain",
            "stage",
            "successful",
            "outcome_unknown",
            "order_id",
            "invoice_id",
            "order_status",
            "invoice_status",
            "amount",
            "currency",
            "error",
        )
        if key in state
    }


def purchase(arguments, context):
    domain = domain_name(arguments["domain"])
    config = _settings(context)
    if domain.split(".")[-1] not in config.get("tlds", ["com", "net"]):
        raise ValueError("Domain suffix is not offered by this registrar configuration")
    path = journal_path(config, domain)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            result = report(json.loads(path.read_text()))
            result["reused"] = True
            result["next_action"] = (
                "Use domain_purchase.status; no new order or payment was submitted."
            )
            return result
        state = {
            "domain": domain,
            "stage": "login",
            "successful": False,
            "outcome_unknown": False,
        }
        try:
            customer = Customer(config)
            gateways = customer.api("guest/invoice/gateways", {"format": "pairs"})
            gateway = next(
                key for key, title in gateways.items() if title.lower() == "fakepayment"
            )
            products = customer.api("guest/product/get_list", {"per_page": 100})["list"]
            product = next(item["id"] for item in products if item["type"] == "domain")
            sld, tld = domain.split(".", 1)
            state["stage"] = "cart"
            customer.api(
                "guest/cart/add_item",
                {
                    "id": product,
                    "action": "register",
                    "register_sld": sld,
                    "register_tld": "." + tld,
                    "register_years": 1,
                },
            )
            # Save BEFORE checkout: after a crash we must not silently submit again.
            state.update(stage="checkout", outcome_unknown=True)
            save(path, state)
            checkout = customer.api("client/cart/checkout", {"gateway_id": gateway})
            state["order_id"] = checkout["order_id"]
            state["invoice_hash"] = checkout.get("invoice_hash")
            save(path, state)
            if not state["invoice_hash"]:
                raise ValueError("Expected an unpaid invoice")
            invoice = customer.api("guest/invoice/get", {"hash": state["invoice_hash"]})
            state.update(invoice_id=invoice["id"], invoice_status=invoice["status"])
            payment = customer.api(
                "guest/invoice/payment",
                {"hash": state["invoice_hash"], "gateway_id": gateway},
            )
            form = PaymentForm()
            form.feed(payment["result"])
            expected = config["payment_url"].rstrip("/") + "/pay"
            if form.action != expected or form.fields.get("invoice") != str(
                invoice["id"]
            ):
                raise ValueError("Payment destination or invoice mismatch")
            callback, registrar = (
                urlsplit(form.fields["notify"]),
                urlsplit(config["registrar_url"]),
            )
            if (callback.scheme, callback.netloc) != (
                registrar.scheme,
                registrar.netloc,
            ):
                raise ValueError("Payment callback origin mismatch")
            amount = Decimal(form.fields["amount"])
            currency = form.fields["currency"]
            if (
                not amount.is_finite()
                or amount <= 0
                or currency != config.get("currency", "USD")
            ):
                raise ValueError("Invalid payment amount or currency")
            state.update(amount=str(amount), currency=currency)
            if amount * 100 > arguments["max_amount_minor"]:
                state.update(
                    stage="payment_limit",
                    outcome_unknown=False,
                    error="amount_exceeds_limit",
                )
                save(path, state)
                return report(state)
            state["stage"] = "payment"
            save(path, state)
            fields = {
                k: form.fields[k]
                for k in ("invoice", "amount", "currency", "notify", "signature")
            }
            fields["action"] = "confirm"
            # Separate opener: never forward registrar cookies to payment service.
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(expected, data=urlencode(fields).encode()), timeout=30
            ) as response:
                response.read(4096)
            state["stage"] = "verification"
            save(path, state)
            deadline = time.monotonic() + 60
            while True:
                invoice = customer.api(
                    "guest/invoice/get", {"hash": state["invoice_hash"]}
                )
                order = customer.api("client/order/get", {"id": state["order_id"]})
                state.update(
                    invoice_status=invoice["status"], order_status=order["status"]
                )
                if invoice["status"] == "paid" and order["status"] == "active":
                    state.update(
                        successful=True, outcome_unknown=False, stage="complete"
                    )
                    break
                if time.monotonic() >= deadline:
                    state["stage"] = "pending"
                    break
                time.sleep(2)
            save(path, state)
        except Exception:
            # Do not echo cookies, credentials, invoice hashes or signed payment fields.
            state["error"] = "purchase_not_confirmed"
            if path.exists():
                save(path, state)
        return report(state)


def status(arguments, context):
    domain = domain_name(arguments["domain"])
    config = _settings(context)
    path = journal_path(config, domain)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            return {
                "domain": domain,
                "successful": False,
                "stage": "no_local_order",
                "outcome_unknown": False,
            }
        state = json.loads(path.read_text())
        if not state.get("order_id"):
            result = report(state)
            result["next_action"] = (
                "Check the registrar portal; checkout may have occurred. Do not resubmit."
            )
            return result
        try:
            customer = Customer(config)
            order = customer.api("client/order/get", {"id": state["order_id"]})
            state["order_status"] = order["status"]
            if state.get("invoice_hash"):
                invoice = customer.api(
                    "guest/invoice/get", {"hash": state["invoice_hash"]}
                )
                state["invoice_status"] = invoice["status"]
            state["successful"] = (
                state.get("invoice_status") == "paid"
                and state["order_status"] == "active"
            )
            if state["successful"]:
                state.update(stage="complete", outcome_unknown=False)
                state.pop("error", None)
            save(path, state)
            return report(state)
        except Exception:
            result = report(state)
            result.update(successful=False, error="status_unavailable")
            return result


def set_nameservers(arguments, context):
    """Replace NS for an owned active domain order; does not create glue or zones."""
    nameservers = arguments["nameservers"]
    if not 2 <= len(nameservers) <= 4:
        raise ValueError("Provide two to four nameserver hostnames")
    normalized = []
    for value in nameservers:
        name = value.lower().rstrip(".")
        if len(name) > 253 or "." not in name or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in name.split(".")
        ):
            raise ValueError("Invalid nameserver hostname")
        normalized.append(name)
    if len(set(normalized)) != len(normalized):
        raise ValueError("Nameserver hostnames must be distinct")
    config = _settings(context)
    customer = Customer(config)
    # FOSSBilling checks customer ownership, domain service type and active status.
    fields = {"order_id": arguments["order_id"], "ns1": normalized[0],
              "ns2": normalized[1], "ns3": "", "ns4": ""}
    if len(normalized) >= 3:
        fields["ns3"] = normalized[2]
    if len(normalized) == 4:
        fields["ns4"] = normalized[3]
    try:
        accepted = customer.api("client/servicedomain/update_nameservers", fields)
    except Exception:
        return {"successful": False, "outcome_unknown": True,
                "order_id": arguments["order_id"], "error": "nameserver_update_not_confirmed",
                "next_action": "Inspect the registrar portal and DNS before retrying."}
    return {"successful": accepted is True, "outcome_unknown": accepted is not True,
            "order_id": arguments["order_id"], "nameservers": normalized,
            "propagation_verified": False}


def hosting_purchase(arguments, context):
    domain = domain_name(arguments["domain"])
    config = _settings(context)
    path = journal_path(config, domain).with_suffix(".hosting.json")
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            result = report(json.loads(path.read_text()))
            result["reused"] = True
            result["next_action"] = (
                "Use domain_purchase.hosting_status; no new order or payment was submitted."
            )
            return result
        state = {
            "domain": domain,
            "stage": "login",
            "successful": False,
            "outcome_unknown": False,
        }
        try:
            customer = Customer(config)
            gateways = customer.api("guest/invoice/gateways", {"format": "pairs"})
            gateway = next(
                key for key, title in gateways.items() if title.lower() == "fakepayment"
            )
            products = customer.api("guest/product/get_list", {"per_page": 100})["list"]
            candidates = [item["id"] for item in products if item["type"] == "dns"]
            if len(candidates) != 1:
                raise ValueError("Expected exactly one DNS Hosting product")
            state["stage"] = "cart"
            customer.api("guest/cart/add_item", {"id": candidates[0], "domain_name": domain})
            # Save BEFORE checkout: after a crash we must not silently submit again.
            state.update(stage="checkout", outcome_unknown=True)
            save(path, state)
            checkout = customer.api("client/cart/checkout", {"gateway_id": gateway})
            state["order_id"] = checkout["order_id"]
            state["invoice_hash"] = checkout.get("invoice_hash")
            if not state["invoice_hash"]:
                state["invoice_status"] = "not_required"
            save(path, state)
            if state["invoice_hash"]:
                invoice = customer.api("guest/invoice/get", {"hash": state["invoice_hash"]})
                state.update(invoice_id=invoice["id"], invoice_status=invoice["status"])
                payment = customer.api(
                    "guest/invoice/payment",
                    {"hash": state["invoice_hash"], "gateway_id": gateway},
                )
                form = PaymentForm()
                form.feed(payment["result"])
                expected = config["payment_url"].rstrip("/") + "/pay"
                if form.action != expected or form.fields.get("invoice") != str(
                    invoice["id"]
                ):
                    raise ValueError("Payment destination or invoice mismatch")
                callback, registrar = (
                    urlsplit(form.fields["notify"]),
                    urlsplit(config["registrar_url"]),
                )
                if (callback.scheme, callback.netloc) != (
                    registrar.scheme,
                    registrar.netloc,
                ):
                    raise ValueError("Payment callback origin mismatch")
                amount = Decimal(form.fields["amount"])
                currency = form.fields["currency"]
                if (
                    not amount.is_finite()
                    or amount <= 0
                    or currency != config.get("currency", "USD")
                ):
                    raise ValueError("Invalid payment amount or currency")
                state.update(amount=str(amount), currency=currency)
                if amount * 100 > arguments["max_amount_minor"]:
                    state.update(
                        stage="payment_limit",
                        outcome_unknown=False,
                        error="amount_exceeds_limit",
                    )
                    save(path, state)
                    return report(state)
                state["stage"] = "payment"
                save(path, state)
                fields = {
                    k: form.fields[k]
                    for k in ("invoice", "amount", "currency", "notify", "signature")
                }
                fields["action"] = "confirm"
                # Separate opener: never forward registrar cookies to payment service.
                with build_opener(ProxyHandler({}), NoRedirect()).open(
                    Request(expected, data=urlencode(fields).encode()), timeout=30
                ) as response:
                    response.read(4096)
            else:
                state.update(invoice_status="not_required", amount="0", currency=config.get("currency", "USD"))
            state["stage"] = "verification"
            save(path, state)
            deadline = time.monotonic() + 60
            while True:
                if state["invoice_hash"]:
                    invoice = customer.api("guest/invoice/get", {"hash": state["invoice_hash"]})
                    state["invoice_status"] = invoice["status"]
                order = customer.api("client/order/get", {"id": state["order_id"]})
                state["order_status"] = order["status"]
                if state["invoice_status"] in ("paid", "not_required") and order["status"] == "active":
                    state.update(
                        successful=True, outcome_unknown=False, stage="complete"
                    )
                    break
                if time.monotonic() >= deadline:
                    state["stage"] = "pending"
                    break
                time.sleep(2)
            save(path, state)
        except Exception:
            # Do not echo cookies, credentials, invoice hashes or signed payment fields.
            state["error"] = "hosting_purchase_not_confirmed"
            if path.exists():
                save(path, state)
        return report(state)


def hosting_status(arguments, context):
    domain = domain_name(arguments["domain"])
    config = _settings(context)
    path = journal_path(config, domain).with_suffix(".hosting.json")
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            return {
                "domain": domain,
                "successful": False,
                "stage": "no_local_order",
                "outcome_unknown": False,
            }
        state = json.loads(path.read_text())
        if not state.get("order_id"):
            result = report(state)
            result["next_action"] = (
                "Check the registrar portal; checkout may have occurred. Do not resubmit."
            )
            return result
        try:
            customer = Customer(config)
            order = customer.api("client/order/get", {"id": state["order_id"]})
            state["order_status"] = order["status"]
            if state.get("invoice_hash"):
                invoice = customer.api(
                    "guest/invoice/get", {"hash": state["invoice_hash"]}
                )
                state["invoice_status"] = invoice["status"]
            state["successful"] = (
                state.get("invoice_status") in ("paid", "not_required")
                and state["order_status"] == "active"
            )
            if state["successful"]:
                state.update(stage="complete", outcome_unknown=False)
                state.pop("error", None)
            save(path, state)
            return report(state)
        except Exception:
            result = report(state)
            result.update(successful=False, error="status_unavailable")
            return result


def _dns_zone(customer, arguments):
    """Read only an owned, active DNS order; never expose provider credentials."""
    order_id = arguments["order_id"]
    order = customer.api("client/order/get", {"id": order_id})
    if order.get("service_type") != "dns" or order.get("status") != "active":
        raise ValueError("An active DNS Hosting order is required, not a domain order")
    service = customer.api("client/order/service", {"id": order_id})
    if domain_name(service["domain_name"]) != domain_name(arguments["domain"]):
        raise ValueError("DNS Hosting order does not match the requested domain")
    records = service["records"]
    if not isinstance(records, list):
        raise ValueError("Invalid DNS record list")
    return {"domain": service["domain_name"], "order_id": order_id,
            "records": [{key: row[key] for key in
                         ("id", "host", "type", "value", "ttl", "priority") if key in row}
                        for row in records], "propagation_verified": False}


def dns_list(arguments, context):
    """List registrar-managed records, not recursive DNS lookup results."""
    try:
        return dict(_dns_zone(Customer(_settings(context)), arguments), successful=True,
                    outcome_unknown=False)
    except Exception:
        return {"successful": False, "outcome_unknown": False,
                "error": "dns_records_unavailable", "propagation_verified": False,
                "next_action": "Check account ownership, domain and active DNS Hosting order_id."}


def _dns_write(arguments, context, operation):
    submitted = False
    accepted = False
    try:
        customer = Customer(_settings(context))
        before = _dns_zone(customer, arguments)
        fields = {key: value for key, value in arguments.items() if key != "domain"}
        record_type = arguments.get("record_type")
        if operation in ("update", "del"):
            selected = next((row for row in before["records"]
                             if str(row["id"]) == str(arguments["record_id"])), None)
            if selected is None:
                raise ValueError("Record does not belong to the DNS Hosting order")
            record_type = selected["type"]
        if operation != "del":
            value = arguments["record_value"]
            if record_type in ("A", "AAAA"):
                address = ipaddress.ip_address(value)
                if address.version != (4 if record_type == "A" else 6):
                    raise ValueError("IP address family does not match record type")
            if not value and record_type != "TXT":
                raise ValueError("Record value is required")
            if "record_priority" in fields and record_type != "MX":
                raise ValueError("Priority applies only to MX records")
        submitted = True
        accepted = customer.api("client/servicedns/" + operation, fields) is True
        if not accepted:
            raise ValueError("Write was not confirmed")
    except Exception:
        return {"successful": False, "outcome_unknown": submitted,
                "error": "dns_write_not_confirmed" if submitted else "dns_precheck_failed",
                "propagation_verified": False,
                "next_action": "Use domain_purchase.dns_list to inspect current records before retrying. Check the DNS Hosting order and record arguments."}
    # An accepted mutation remains accepted even if the subsequent read fails.
    result = {"successful": accepted, "outcome_unknown": False,
              "order_id": arguments["order_id"], "domain": arguments["domain"],
              "operation": operation, "propagation_verified": False,
              "records_readback": False}
    try:
        result.update(_dns_zone(customer, arguments), records_readback=True)
    except Exception:
        result["next_action"] = "Write accepted; use domain_purchase.dns_list to read records. Do not resubmit the write."
    return result


def dns_add(arguments, context):
    return _dns_write(arguments, context, "add")


def dns_update(arguments, context):
    return _dns_write(arguments, context, "update")


def dns_delete(arguments, context):
    return _dns_write(arguments, context, "del")


def _settings(context):
    """Read per-person credentials from the current AgentService persona."""
    if hasattr(context, "accounts"):
        return context.accounts["domain_purchase"]
    return context.service("domain_purchase")
