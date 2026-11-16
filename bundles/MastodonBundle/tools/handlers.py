"""Mastodon operations executed locally under the agent's identity and policy."""

import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from pydantic import TypeAdapter, ValidationError

from .models import (
    FollowArguments,
    FollowResult,
    AccountInfo,
    ProfileArguments,
    ProfileResult,
    PostsArguments,
    RelationshipInfo,
    StatusContextInfo,
    ReadResult,
    PostArguments,
    PostResult,
    LikeArguments,
    StatusInfo,
    ReadArguments,
    BoostArguments,
    InboxArguments,
    InboxResult,
    MentionInfo,
    BrowseArguments,
    PostsResult,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def browse(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    if credential_file and not Path(credential_file).is_file():
        credential_file = None
    a = BrowseArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    limit = a.limit
    max_id = a.max_id
    query = {"limit": limit}
    if max_id is not None:
        query["max_id"] = max_id
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/timelines/public?{urlencode(query)}",
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(list[StatusInfo]).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    return PostsResult(
        **metadata, statuses=data or [], next_max_id=data[-1].id if data else None
    ).model_dump(mode="json")


def inbox(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    if credential_file and not Path(credential_file).is_file():
        credential_file = None
    a = InboxArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    limit = a.limit
    query = {"limit": limit, "min_id": a.min_id, "types[]": "mention"}
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/notifications?{urlencode(query)}",
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(list[MentionInfo]).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    next_min_id = None
    if metadata["successful"]:
        data.sort(key=lambda notification: int(notification.id))
        next_min_id = data[-1].id if data else a.min_id
    return InboxResult(
        **metadata, notifications=data or [], next_min_id=next_min_id
    ).model_dump(mode="json")


def post(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    a = PostArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    status = a.status
    visibility = a.visibility
    in_reply_to_id = a.in_reply_to_id
    idempotency_key = a.idempotency_key
    body = {"status": status, "visibility": visibility}
    if in_reply_to_id is not None:
        body["in_reply_to_id"] = in_reply_to_id
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": "/api/v1/statuses",
        "method": "POST",
        "body": body,
        "idempotency_key": idempotency_key,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    error_message = None
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
                # Read bounded JSON error text, never echo credentials or HTML pages.
                raw_error = response.read(8193)
                if len(raw_error) <= 8192:
                    try:
                        message = json.loads(raw_error).get("error")
                        if isinstance(message, str):
                            error_message = message.replace(token, "[redacted]")[:500]
                    except (ValueError, AttributeError, UnicodeError):
                        pass
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if sent and out["error"] and out["http_status"] not in (400, 401, 403, 404, 413, 422, 429):
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(StatusInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=True)
    result = PostResult(**metadata, status=data).model_dump(mode="json")
    result["sent"] = bool(result["successful"] and data is not None and data.id)
    result["error_message"] = error_message
    if not result["sent"]:
        if result["outcome_unknown"]:
            result["next_action"] = "Check your published posts before retrying; delivery is uncertain."
        elif result["http_status"] == 422:
            result["next_action"] = "Post rejected, not delivered. Check error_message and shorten/correct the text (maximum 500 characters). Use a new idempotency_key for changed text."
        else:
            result["next_action"] = "Post not delivered. Resolve the reported error before trying again; do not wait for a reply."
    return result


def profile(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    a = ProfileArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    acct = a.acct
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": "/api/v1/accounts/lookup?" + urlencode({"acct": acct}),
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(AccountInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    return ProfileResult(**metadata, account=data).model_dump(mode="json")


def posts(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    if credential_file and not Path(credential_file).is_file():
        credential_file = None
    a = PostsArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    account_id = a.account_id
    limit = a.limit
    max_id = a.max_id
    query = {"limit": limit}
    if max_id is not None:
        query["max_id"] = max_id
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/accounts/{account_id}/statuses?{urlencode(query)}",
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(list[StatusInfo]).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    return PostsResult(
        **metadata, statuses=data or [], next_max_id=data[-1].id if data else None
    ).model_dump(mode="json")


def read(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    if credential_file and not Path(credential_file).is_file():
        credential_file = None
    a = ReadArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    status_id = a.status_id
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/statuses/{status_id}",
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(StatusInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    focal_post = data
    if not metadata["successful"]:
        return ReadResult(**metadata, status=focal_post).model_dump(mode="json")

    # Fetch visible replies only after the focal post has been read successfully.
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    if credential_file and not Path(credential_file).is_file():
        credential_file = None
    a = ReadArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    status_id = a.status_id
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/statuses/{status_id}/context",
        "method": "GET",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(StatusContextInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=False)
    return ReadResult(**metadata, status=focal_post, context=data).model_dump(mode="json")


def like(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    a = LikeArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    status_id = a.status_id
    enabled = a.enabled
    action = "favourite" if enabled else "unfavourite"
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/statuses/{status_id}/{action}",
        "method": "POST",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(StatusInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=True)
    return PostResult(**metadata, status=data).model_dump(mode="json")


def boost(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    a = BoostArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    status_id = a.status_id
    enabled = a.enabled
    action = "reblog" if enabled else "unreblog"
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/statuses/{status_id}/{action}",
        "method": "POST",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(StatusInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=True)
    return PostResult(**metadata, status=data).model_dump(mode="json")


def follow(arguments, context):
    settings = _settings(context)
    source = context.identity
    instance_url = settings["instance_url"].rstrip("/")
    origin = urlsplit(instance_url)
    if (
        (origin.scheme != "https" and not (origin.scheme == "http" and settings.get("allow_http") is True))
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("socialmedia instance_url must be an HTTPS origin (HTTP requires allow_http=true)")
    credential_file = settings.get("credential_file")
    a = FollowArguments.model_validate(arguments)
    timeout_seconds = a.timeout_seconds
    account_id = a.account_id
    enabled = a.enabled
    action = "follow" if enabled else "unfollow"
    instance_url = instance_url.rstrip("/")
    cfg = {
        "source": source,
        "instance_url": instance_url,
        "credential_file": credential_file,
        "timeout_seconds": timeout_seconds,
        "path": f"/api/v1/accounts/{account_id}/{action}",
        "method": "POST",
        "body": None,
        "idempotency_key": None,
    }
    out = {"http_status": None, "error": None, "data": None, "outcome_unknown": False}
    sent = False
    try:
        if not credential_file:
            raise ValueError("credentials required")
        headers = {"Accept": "application/json"}
        if cfg["credential_file"]:
            with open(cfg["credential_file"]) as stream:
                credentials = json.load(stream)
            if credentials["instance_url"].rstrip("/") != cfg["instance_url"]:
                raise ValueError("credential origin mismatch")
            token = credentials["access_token"]
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise ValueError("invalid credential")
            headers["Authorization"] = "Bearer " + token
        if cfg["idempotency_key"]:
            headers["Idempotency-Key"] = cfg["idempotency_key"]
        body = None
        if cfg["body"] is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(cfg["body"]).encode()
        tls_context = ssl.create_default_context()
        opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=tls_context), NoRedirect()
        )
        request = Request(
            cfg["instance_url"] + cfg["path"],
            data=body,
            headers=headers,
            method=cfg["method"],
        )
        sent = True
        try:
            response = opener.open(request, timeout=cfg["timeout_seconds"])
        except HTTPError as error:
            response = error
        with response:
            out["http_status"] = response.code
            if not 200 <= response.code < 300:
                out["error"] = "http_error"
            else:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    out["error"] = "response_too_large"
                else:
                    try:
                        out["data"] = json.loads(raw)
                    except (ValueError, UnicodeError):
                        out["error"] = "invalid_response"
    except (URLError, TimeoutError, ConnectionError):
        out["error"] = "transport_error"
    except (OSError, ValueError, KeyError, TypeError):
        out["error"] = "client_error" if not sent else "transport_error"
    if cfg["method"] == "POST" and sent and out["error"]:
        out["outcome_unknown"] = True
    metadata = {
        "source": source,
        "instance_url": instance_url,
        "successful": False,
        "http_status": None,
        "error": None,
        "outcome_unknown": False,
    }
    data = None
    try:
        response = out
        metadata.update(
            http_status=response["http_status"],
            error=response["error"],
            outcome_unknown=response["outcome_unknown"],
        )
        if metadata["error"] is None:
            if (
                not isinstance(metadata["http_status"], int)
                or not 200 <= metadata["http_status"] < 300
            ):
                raise ValueError("missing successful HTTP status")
            data = TypeAdapter(RelationshipInfo).validate_python(response["data"])
            metadata["successful"] = True
    except (ValueError, KeyError, TypeError, ValidationError):
        metadata.update(error="invalid_response", outcome_unknown=True)
    return FollowResult(**metadata, relationship=data).model_dump(mode="json")


def _settings(context):
    """Read per-person credentials from the current AgentService persona."""
    if hasattr(context, "accounts"):
        return context.accounts["socialmedia"]
    return context.service("socialmedia")
