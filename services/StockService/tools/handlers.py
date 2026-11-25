"""Agent-owned Stock Service actions and account queries."""

import re
import importlib

from emuvista_agent.http import request
from emuvista_agent.mail import configuration as mailbox_configuration, messages

from .client import call, configuration, connection as authenticated_connection
from .client import opener as client_opener
from .client import register as registration_connection
from .client import service_configuration


def register(arguments, context):
    config, transport = registration_connection(context, arguments.get("instance"))
    mail = mailbox_configuration(context)
    previous = max((message["uid"] for message in messages(mail, 50)), default=0)
    response = request(
        config,
        "/api/v1/accounts/register",
        method="POST",
        opener=transport,
        body={"email": config["email"], "password": config["password"],
              "display_name": context.name},
    )
    pending = getattr(context, "_stock_verify_after", {})
    context._stock_verify_after = pending
    pending[config["url"]] = previous
    return response


def verify_email(arguments, context):
    config = configuration(context, arguments.get("instance"))
    mail = mailbox_configuration(context)
    previous = getattr(context, "_stock_verify_after", {}).get(config["url"], 0)
    code = None
    for message in reversed(messages(mail, 30)):
        sender = message["from"].lower()
        if message["uid"] <= previous or config["sender"].lower() not in sender:
            continue
        match = re.search(r"verification code is ([0-9]{6})", message["body"], re.IGNORECASE)
        if match:
            code = match.group(1)
            break
    if not code:
        raise RuntimeError("Stock Service verification email was not found")
    transport = registration_connection(context, arguments.get("instance"))[1]
    response = request(
        config,
        "/api/v1/accounts/verify-email",
        method="POST",
        opener=transport,
        body={"email": config["email"], "code": code},
    )
    context._stock_verify_after.pop(config["url"], None)
    return response


def login(arguments, context):
    context._stock_sessions = {}
    config, _, _ = authenticated_connection(context, arguments.get("instance"))
    return {"status": "authenticated", "email": config["email"]}


def cash(arguments, context):
    return call(context, "/api/v1/cash", instance=arguments.get("instance"))


def positions(arguments, context):
    return call(context, "/api/v1/positions", instance=arguments.get("instance"))


def orders(arguments, context):
    return call(context, "/api/v1/orders", instance=arguments.get("instance"))


def market(arguments, context):
    config = service_configuration(context, arguments.get("instance"))
    transport = client_opener(config)
    return request(config, "/api/v1/market/" + arguments["symbol"], opener=transport)


def place_order(arguments, context):
    body = {key: arguments[key] for key in ("client_order_id", "symbol", "side", "quantity", "limit_price")}
    return call(context, "/api/v1/orders", method="POST", body=body,
                instance=arguments.get("instance"))


def buy_from_system(arguments, context):
    body = {key: arguments[key] for key in ("client_order_id", "symbol", "quantity", "max_unit_price")
            if key in arguments}
    return call(context, "/api/v1/system-purchases", method="POST", body=body,
                instance=arguments.get("instance"))


def cancel_order(arguments, context):
    return call(context, "/api/v1/orders/" + arguments["client_order_id"] + "/cancel",
                method="POST", body={}, instance=arguments.get("instance"))


def bank_links(arguments, context):
    return call(context, "/api/v1/bank-links", instance=arguments.get("instance"))


def bank_cards(arguments, context):
    bank_alias = arguments["bank"]
    bank_client = importlib.import_module("emuvista_tools_bank.client")
    config, transport, headers = bank_client.connection(context, bank_alias)
    cards = request(config, "/api/v1/cards", opener=transport, headers=headers)
    return [{"cardId": card["cardId"], "name": card["name"],
             "maskedCard": "••••" + str(card["number"])[-4:],
             "currency": card["currency"], "status": card["status"],
             "balanceMinor": card["balanceMinor"]} for card in cards]


def link_bank_card(arguments, context):
    bank_alias = arguments["bank"]
    bank_client = importlib.import_module("emuvista_tools_bank.client")
    bank_config, bank_opener, bank_headers = bank_client.connection(context, bank_alias)
    bank_cards = request(bank_config, "/api/v1/cards", opener=bank_opener, headers=bank_headers)
    selected = next((card for card in bank_cards
                     if str(card.get("cardId")) == arguments["card_id"]), None)
    if selected is None or selected.get("status") != "active":
        raise ValueError("Choose an active card from bank.cards")
    begin = call(context, "/api/v1/bank-links", method="POST", body={
        "bank": bank_alias, "card_id": selected["cardId"], "card_number": selected["number"]
    }, instance=arguments.get("instance"))
    authorize = importlib.import_module("emuvista_tools_bank.client").authorize_card
    callback = authorize(context, bank_alias, begin["authorization_url"],
                         begin["redirect_uri"], selected["cardId"])
    return call(context, "/api/v1/bank-links/complete", method="POST", body=callback,
                instance=arguments.get("instance"))


def unlink_bank_card(arguments, context):
    link_id = arguments["bank_link_id"]
    config, transport, headers = authenticated_connection(context, arguments.get("instance"))
    return request(config, "/api/v1/bank-links/" + link_id, method="DELETE",
                   opener=transport, headers=headers)


def deposit(arguments, context):
    body = {"id": arguments["id"], "bank_link_id": arguments["bank_link_id"],
            "amount": arguments["amount"]}
    return call(context, "/api/v1/cash/deposits", method="POST", body=body,
                instance=arguments.get("instance"))


def deposit_status(arguments, context):
    return call(context, "/api/v1/cash/deposits/" + arguments["id"],
                instance=arguments.get("instance"))
