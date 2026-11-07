"""Standalone step-ca probe. Never return secrets or raw CA configuration/logs."""

import json
import re
import ssl
import subprocess
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPSHandler, ProxyHandler, build_opener


def probe(args):
    if args["action"] == "events":
        path = Path(args["log_path"])
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - 262144)
            stream.seek(start)
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        if start:
            lines = lines[1:]  # Discard a possibly partial first record.
        events = []
        unparsed = 0
        for line in lines:
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Not a log record")
            except ValueError:
                unparsed += 1
                continue
            # Keep only known event metadata. URLs/account IDs, bodies and messages
            # can contain challenge values or credentials and are not returned.
            endpoint = str(record.get("path", record.get("requestPath", "")))
            kind = "other"
            for fragment, label in (
                ("revoke", "revocation"),
                ("renew", "renewal"),
                ("challenge", "challenge"),
                ("finalize", "finalization"),
                ("new-order", "order"),
                ("sign", "signing"),
            ):
                if fragment in endpoint:
                    kind = label
                    break
            events.append(
                {
                    "time": record.get("time"),
                    "kind": kind,
                    "status": record.get("status"),
                    "method": record.get("method"),
                }
            )
        return {
            "events": events[-args["limit"] :],
            "unparsed_lines": unparsed,
            "truncated": start > 0 or len(events) > args["limit"],
            "source": "step_ca_log",
            "complete_audit_history": False,
        }

    path = Path(args["config_path"])
    if args["action"] == "service":
        config = json.loads(path.read_text())
        authority = config.get("authority", {})
        try:
            result = subprocess.run(["pgrep", "-x", "step-ca"], capture_output=True, timeout=5)
            running = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            running = None
        roots = config.get("root", [])
        if isinstance(roots, str):
            roots = [roots]
        certificate_observations = []
        for certificate_path in [*roots[:4], config.get("crt")]:
            if not certificate_path:
                continue
            try:
                result = subprocess.run(
                    [
                        "openssl",
                        "x509",
                        "-in",
                        certificate_path,
                        "-noout",
                        "-dates",
                        "-subject",
                        "-issuer",
                        "-fingerprint",
                        "-sha256",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                certificate_observations.append(
                    {
                        "path": certificate_path,
                        "readable": result.returncode == 0,
                        "details": result.stdout if result.returncode == 0 else None,
                    }
                )
            except (OSError, subprocess.TimeoutExpired):
                certificate_observations.append({"path": certificate_path, "readable": False})
        health = "unverified"
        names = config.get("dnsNames", [])
        address = str(config.get("address", ":443"))
        try:
            port = int(address.rsplit(":", 1)[-1])
        except ValueError:
            port = None
        if port is not None and not 1 <= port <= 65535:
            port = None
        acme_directory_urls = []
        if (
            port is not None
            and names
            and isinstance(names[0], str)
            and re.fullmatch(r"[A-Za-z0-9.-]+", names[0])
        ):
            hostname = names[0].rstrip(".")
            authority_port = f":{port}" if port and port != 443 else ""
            for provisioner in authority.get("provisioners", []):
                if provisioner.get("type") != "ACME":
                    continue
                provisioner_name = provisioner.get("name")
                if not isinstance(provisioner_name, str) or not provisioner_name:
                    continue
                acme_directory_urls.append(
                    {
                        "provisioner": provisioner_name,
                        "directory_url": (
                            f"https://{hostname}{authority_port}/acme/"
                            f"{quote(provisioner_name, safe='-._~')}/directory"
                        ),
                    }
                )
        if (
            roots
            and names
            and isinstance(names[0], str)
            and re.fullmatch(r"[A-Za-z0-9.-]+", names[0])
            and port is not None
        ):
            try:
                context = ssl.create_default_context(cafile=roots[0])
                opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
                with opener.open(f"https://{names[0]}:{port}/health", timeout=5) as response:
                    body = json.loads(response.read(4096))
                health = "ok" if body.get("status") == "ok" else "unexpected_response"
            except Exception:
                health = "check_failed"
        return {
            "process_running": running,
            "endpoint_health": health,
            "certificates": certificate_observations,
            "address": address,
            "dns_names": names,
            "acme_directory_urls": acme_directory_urls,
            "root_certificate_paths": config.get("root"),
            "intermediate_certificate_path": config.get("crt"),
            "configured_default_duration": authority.get("claims", {}).get(
                "defaultTLSCertDuration"
            ),
            "provisioners": [
                {"name": item.get("name"), "type": item.get("type")}
                for item in authority.get("provisioners", [])
            ],
            "effective_policy_verified": False,
        }

    raise ValueError("Unknown action")
