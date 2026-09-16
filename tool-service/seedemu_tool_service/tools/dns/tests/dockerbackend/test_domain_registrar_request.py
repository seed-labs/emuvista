"""Read the B02a Loom frontend through the real Agent-facing tools.

These tests require a running B02a deployment generated from the *current*
source-auth-enabled topology. The checked-in ``examples/.../output`` may be an
older HTTP-only build, so regenerate B02a before running them:

    cd /path/to/seed-emulator
    .venv/bin/python examples/internet/B02a_domain_registration/domain_registration.py

The deployment must expose:

- source container ``as150h-host_1-10.150.0.72`` with a provisioned source
  identity under ``/opt/seedemu/registrar/<sha256>``;
- Loom at ``https://10.150.0.74:443`` with ``seedemu-source-auth.php``.

Run with ``--show-dns-results`` to inspect the returned HTML/redirect evidence.
"""

from collections.abc import Callable
from hashlib import sha256
from typing import Any
from urllib.parse import urljoin, urlsplit

import anyio

from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools

SOURCE_CONTAINER = "as150h-host_1-10.150.0.72"
REGISTRAR_URL = "https://10.150.0.74:443"


def test_registrar_request_reads_discovered_loom_frontend(
    show_dns_result: Callable[[Any], None],
) -> None:
    """Discover Loom, request its root from a client, and read its HTML page."""

    registry = ToolRegistry()
    register_dns_tools(registry, DockerRuntimeBackend())
    directory = anyio.run(registry.invoke, "domain.registrar_find", {})
    show_dns_result(directory)
    urls = [registrar.registrar_url for registrar in directory.registrars]
    assert urls == sorted(set(urls))
    assert REGISTRAR_URL in urls
    assert "domain.registrar_request" in directory.next_step
    candidates = [
        registrar for registrar in directory.registrars if registrar.registrar_url == REGISTRAR_URL
    ]
    assert len(candidates) == 1, "Expected one running B02a Loom frontend"
    registrar_url = candidates[0].registrar_url
    assert registrar_url == REGISTRAR_URL
    origin = urlsplit(registrar_url)
    path = "/"
    visited: set[str] = set()
    session_id = None
    try:
        # Each redirect requires a separate tool call, just as it does for the Agent.
        for _ in range(5):
            assert path not in visited, f"Frontend redirect loop at {path}"
            visited.add(path)
            response = anyio.run(
                registry.invoke,
                "domain.registrar_request",
                {
                    "source": SOURCE_CONTAINER,
                    "registrar_url": registrar_url,
                    "session_id": session_id,
                    "method": "GET",
                    "path": path,
                },
            )
            show_dns_result(response)
            if session_id is not None:
                assert response.session_id == session_id
            session_id = response.session_id
            assert response.transport_successful, response.stderr
            assert response.exit_code == 0
            assert response.registrar_url == registrar_url
            assert response.requested_path == path
            assert response.method == "GET"
            assert not response.truncated, "Frontend response exceeded the tool's size limit"
            if response.http_status in {301, 302, 303, 307, 308}:
                assert not response.successful
                assert response.location, "Redirect response did not expose Location"
                target = urlsplit(urljoin(urljoin(registrar_url + "/", path), response.location))
                assert (target.scheme, target.netloc) == (origin.scheme, origin.netloc), (
                    "Frontend redirected outside the discovered Registrar origin"
                )
                path = target.path or "/"
                if target.query:
                    path += "?" + target.query
                continue
            assert response.successful, f"Frontend returned HTTP {response.http_status}"
            assert response.http_status == 200
            assert "text/html" in (response.content_type or "").lower()
            html = response.body.lower()
            assert "<html" in html, "Expected a readable HTML document"
            assert "<form" in html or "<a " in html or "<script" in html, (
                "Frontend did not expose forms, links, or scripts for Agent exploration"
            )
            break
        else:
            raise AssertionError("Frontend exceeded five requests without returning HTML")
    finally:
        if session_id is not None:
            cleanup = anyio.run(
                registry.invoke,
                "domain.registrar_request",
                {
                    "source": SOURCE_CONTAINER,
                    "registrar_url": registrar_url,
                    "session_id": session_id,
                    "path": "/",
                    "close_session": True,
                },
            )
            assert cleanup.transport_successful, cleanup.stderr


def test_registrar_session_rejects_other_sources_and_can_be_closed() -> None:
    """Keep one cookie jar across requests and invalidate it on explicit close."""
    import pytest

    from seedemu_tool_service.tools.dns.tools import RegistrarMetadataError

    registry = ToolRegistry()
    backend = DockerRuntimeBackend()
    register_dns_tools(registry, backend)
    arguments = {"source": SOURCE_CONTAINER, "registrar_url": REGISTRAR_URL, "path": "/"}
    first = anyio.run(registry.invoke, "domain.registrar_request", arguments)
    assert first.transport_successful, first.stderr
    arguments["session_id"] = first.session_id
    cookie_path = (
        f"/var/lib/seedemu/registrar/{sha256(REGISTRAR_URL.encode()).hexdigest()}"
        f"/session-{first.session_id}/cookies"
    )
    try:
        # Verify a private curl jar exists in the selected source container.
        jar = backend.execute(SOURCE_CONTAINER, ["stat", "-c", "%a", cookie_path])
        assert jar.exit_code == 0, jar.stderr
        assert jar.stdout.strip() == "600"
        with pytest.raises(RegistrarMetadataError, match="Unknown session"):
            anyio.run(
                registry.invoke,
                "domain.registrar_request",
                {
                    **arguments,
                    "source": "as160h-host_0-10.160.0.71",
                },
            )
        other_worker = ToolRegistry()
        register_dns_tools(other_worker, DockerRuntimeBackend())
        repeated = anyio.run(other_worker.invoke, "domain.registrar_request", arguments)
        assert repeated.transport_successful, repeated.stderr
        assert repeated.session_id == first.session_id
    finally:
        closed = anyio.run(
            registry.invoke,
            "domain.registrar_request",
            {
                **arguments,
                "close_session": True,
            },
        )
        assert closed.transport_successful, closed.stderr
    missing = backend.execute(SOURCE_CONTAINER, ["test", "!", "-e", cookie_path])
    assert missing.exit_code == 0
    with pytest.raises(RegistrarMetadataError, match="Unknown session"):
        anyio.run(registry.invoke, "domain.registrar_request", arguments)


def test_source_auto_authentication_opens_native_loom_profile() -> None:
    """The Agent supplies only source and origin, never credentials or login fields."""
    registry = ToolRegistry()
    register_dns_tools(registry, DockerRuntimeBackend())
    args = {"source": SOURCE_CONTAINER, "registrar_url": REGISTRAR_URL, "path": "/profile"}
    anonymous = anyio.run(
        registry.invoke,
        "domain.registrar_request",
        {
            **args,
            "authentication": "none",
            "close_session": True,
        },
    )
    assert anonymous.http_status in {301, 302}
    assert "/login" in (anonymous.location or "")
    assert not anonymous.authenticated
    logged_in = anyio.run(registry.invoke, "domain.registrar_request", args)
    assert logged_in.authenticated
    assert logged_in.http_status == 200, logged_in.stderr
    assert "b02a-host1@example.com" in logged_in.body
    try:
        worker = ToolRegistry()
        register_dns_tools(worker, DockerRuntimeBackend())
        repeated = anyio.run(
            worker.invoke,
            "domain.registrar_request",
            {
                **args,
                "session_id": logged_in.session_id,
            },
        )
        assert repeated.authenticated and repeated.http_status == 200
        assert "b02a-host1@example.com" in repeated.body
        # Token authentication does not disable native form CSRF protection.
        rejected = anyio.run(
            worker.invoke,
            "domain.registrar_request",
            {
                **args,
                "session_id": logged_in.session_id,
                "method": "POST",
                "content_type": "application/x-www-form-urlencoded",
                "body": "",
            },
        )
        assert rejected.http_status in {400, 403}
    finally:
        anyio.run(
            registry.invoke,
            "domain.registrar_request",
            {
                **args,
                "session_id": logged_in.session_id,
                "close_session": True,
            },
        )


def test_unprovisioned_source_and_invalid_tokens_are_rejected() -> None:
    import pytest

    from seedemu_tool_service.tools.dns.tools import RegistrarMetadataError

    backend = DockerRuntimeBackend()
    registry = ToolRegistry()
    register_dns_tools(registry, backend)
    with pytest.raises(RegistrarMetadataError, match="No source identity"):
        anyio.run(
            registry.invoke,
            "domain.registrar_request",
            {
                "source": "as160h-host_0-10.160.0.71",
                "registrar_url": REGISTRAR_URL,
                "authentication": "required",
                "close_session": True,
            },
        )
    credentials = "/opt/seedemu/registrar/" + sha256(REGISTRAR_URL.encode()).hexdigest()
    permissions = backend.execute(SOURCE_CONTAINER, ["stat", "-c", "%a", credentials + "/token"])
    assert permissions.stdout.strip() == "600"
    for fields in [
        ["--data", "source_id=b02a.as150.host_1"],
        ["--data", "source_id=b02a.as150.host_1&token=incorrect"],
        [
            "--data",
            "source_id=another-source",
            "--data-urlencode",
            "token@" + credentials + "/token",
        ],
    ]:
        response = backend.execute(
            SOURCE_CONTAINER,
            [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "10",
                "--cacert",
                credentials + "/ca.crt",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                *fields,
                REGISTRAR_URL + "/seedemu-source-auth.php",
            ],
        )
        assert response.exit_code == 0, response.stderr
        assert response.stdout == "401"
