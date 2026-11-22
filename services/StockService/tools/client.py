"""Authenticated client for an Agent's Stock Service account."""

from __future__ import annotations

import ssl
import threading
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from emuvista_agent.http import request


_lock = threading.RLock()


def service_configuration(context, instance=None):
    providers = context.tool_config.get("stock", {})
    instance = instance or next(iter(providers), None)
    if not instance or instance not in providers:
        raise ValueError("Stock Service is not configured for this agent")
    return providers[instance]


def configuration(context, instance=None):
    provider = service_configuration(context, instance)
    account = context.accounts.get("stock", {})
    mailbox = context.accounts.get("email", {})
    email = account.get("email") or mailbox.get("email")
    password = account.get("password")
    if not email or not password:
        raise ValueError("Configure this agent's stock email and password")
    return {**provider, "email": email, "password": password}


def opener(config):
    tls = ssl.create_default_context(cadata=config["certificate"])
    # The generated StockBundle certificate is pinned as the trust anchor.
    # This allows the bundle's internal IP and optional hostname to vary safely.
    tls.check_hostname = False
    return build_opener(ProxyHandler({}), HTTPSHandler(context=tls))


def register(context, instance=None):
    config = configuration(context, instance)
    return config, opener(config)


def connection(context, instance=None):
    config = configuration(context, instance)
    with _lock:
        sessions = getattr(context, "_stock_sessions", {})
        context._stock_sessions = sessions
        cached = sessions.get(config["url"])
        if cached:
            return config, cached[0], cached[1]
        transport = opener(config)
        response = request(config, "/api/v1/accounts/login", method="POST", opener=transport,
                           body={"email": config["email"], "password": config["password"]})
        token = response["api_key"]
        headers = {"Authorization": "Bearer " + token}
        sessions[config["url"]] = (token, transport, headers)
        return config, transport, headers


def call(context, path, *, method="GET", body=None, instance=None):
    config, transport, headers = connection(context, instance)
    return request(config, path, method=method, body=body, opener=transport, headers=headers)
