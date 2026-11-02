"""Standalone read-only probe copied to the selected node's Python interpreter."""

import configparser
import json
import os
import shutil
import ssl
import stat
import subprocess
from pathlib import Path
from urllib.request import HTTPSHandler, ProxyHandler, build_opener


def command(argv, timeout=5):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def environment(bundle):
    trusted_bundle = False
    try:
        ssl.create_default_context(cafile=bundle)
        trusted_bundle = True
    except (OSError, ssl.SSLError):
        pass
    executables = {
        name: shutil.which(name)
        for name in ("openssl", "certbot", "step", "step-ca", "nginx", "cron", "getent")
    }
    plugin_code, plugin_output = command(["certbot", "plugins", "--text"])
    plugins_available = plugin_code == 0
    return {
        "executables": executables,
        "seedemu_step_cli_available": executables["step"] is not None,
        "certbot_available": executables["certbot"] is not None,
        "certbot_plugins_available": plugins_available,
        "certbot_authenticators": (
            [name for name in ("nginx", "webroot", "dns-rfc2136") if name in plugin_output]
            if plugins_available
            else []
        ),
        "ca_bundle_path": bundle,
        "ca_bundle_loadable": trusted_bundle,
        "requests_ca_bundle": os.environ.get("REQUESTS_CA_BUNDLE"),
        "ca_endpoint_trust_verified": False,
    }


def renewal(path):
    # Certbot uses INI top-level keys before [renewalparams]. Ignore hook contents.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string("[lineage]\n" + _read_renewal_config(path))
    return {
        "cert_name": path.stem,
        "renewal_config_path": str(path),
        **{
            key: parser.get("lineage", key, fallback=None)
            for key in ("cert", "chain", "fullchain", "privkey", "renew_before_expiry")
        },
        **{
            key: parser.get("renewalparams", key, fallback=None)
            for key in ("server", "authenticator", "installer")
        },
        "hooks_configured": any(
            parser.has_option(section, key)
            for section in parser.sections()
            for key in ("pre_hook", "post_hook", "renew_hook", "deploy_hook")
        ),
    }


def _read_renewal_config(path):
    """Read a bounded regular file without following a renewal-config symlink."""
    limit = 1048576
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Invalid renewal configuration file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("Invalid renewal configuration file")
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Invalid renewal configuration file")
        return content
    except OSError as error:
        raise ValueError("Invalid renewal configuration file") from error


def probe(args):
    action = args["action"]
    if action == "renewal_server":
        path = Path(args["config_path"])
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string("[lineage]\n" + _read_renewal_config(path))
        if not parser.has_option("renewalparams", "server"):
            raise ValueError("Renewal configuration has no ACME server")
        server = parser.get("renewalparams", "server").strip()
        if not server:
            raise ValueError("Renewal configuration has an empty ACME server")
        return {"server": server}
    if action == "environment":
        return environment(args["ca_bundle_path"])
    if action == "certificates":
        directory = Path(args["config_directory"]) / "renewal"
        paths = sorted(directory.glob("*.conf"))
        entries = []
        for path in paths[: args["limit"]]:
            try:
                entry = renewal(path)
                code, output = command(
                    [
                        "openssl",
                        "x509",
                        "-in",
                        entry["cert"] or "",
                        "-noout",
                        "-dates",
                        "-serial",
                        "-fingerprint",
                        "-sha256",
                        "-ext",
                        "subjectAltName",
                    ]
                )
                entry["certificate_readable"] = code == 0
                entry["certificate_details"] = output if code == 0 else None
                entries.append(entry)
            except (OSError, ValueError, configparser.Error):
                entries.append({"cert_name": path.stem, "error": "unreadable_renewal_config"})
        return {
            "directory_exists": directory.is_dir(),
            "certificates": entries,
            "truncated": len(paths) > args["limit"],
        }
    if action == "renewal":
        path = Path(args["config_directory"]) / "renewal" / (args["cert_name"] + ".conf")
        details = renewal(path)
        cron = Path("/etc/cron.d/certbot")
        active_lines = []
        if cron.is_file():
            active_lines = [
                line
                for line in cron.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        cron_code, _ = command(["pgrep", "-x", "cron"])
        timer_code, _ = command(["systemctl", "is-active", "certbot.timer"])
        log_signals = []
        log = Path(args["log_path"])
        log_readable = False
        log_truncated = False
        try:
            with log.open("rb") as stream:
                stream.seek(0, 2)
                start = max(0, stream.tell() - 131072)
                stream.seek(start)
                lines = stream.read().decode("utf-8", errors="replace").splitlines()
            log_readable, log_truncated = True, start > 0
            if start:
                lines = lines[1:]
            for line in lines:
                lowered = line.lower()
                for text, signal in (
                    ("no renewals were attempted", "no_renewals_attempted"),
                    ("all renewals succeeded", "renewals_succeeded"),
                    ("failed to renew certificate", "renewal_failed"),
                ):
                    if text in lowered:
                        log_signals.append(signal)
        except OSError:
            pass
        details.update(
            {
                "cron_file_present": cron.is_file(),
                "certbot_cron_entry_present": any("certbot" in line for line in active_lines),
                "cron_running": None if cron_code is None else cron_code == 0,
                "systemd_timer_active": None if timer_code is None else timer_code == 0,
                "last_renewal_outcome": "unknown",
                "automatic_renewal_verified": False,
                "log_readable": log_readable,
                "log_truncated": log_truncated or len(log_signals) > 20,
                "recent_log_signals": log_signals[-20:],
                "log_signal_scope": "Certbot process; not attributed to this certificate",
            }
        )
        return details
    if action == "readiness":
        findings = environment(args["ca_bundle_path"])
        directory_ok = False
        directory_error = None
        try:
            context = ssl.create_default_context(cafile=args["ca_bundle_path"])
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
            with opener.open(args["directory_url"], timeout=args["timeout_seconds"]) as response:
                document = json.loads(response.read(65537))
            directory_ok = isinstance(document, dict) and all(
                isinstance(document.get(key), str) and document[key].startswith("https://")
                for key in ("newNonce", "newAccount", "newOrder")
            )
        except Exception as error:
            directory_error = type(error).__name__
        resolved = {}
        for name in args["domains"]:
            lookup_name = name[2:] if name.startswith("*.") else name
            code, output = command(["getent", "ahosts", lookup_name], args["timeout_seconds"])
            resolved[lookup_name] = (
                sorted({line.split()[0] for line in output.splitlines()}) if code == 0 else []
            )
        nginx_code, _ = command(["pgrep", "-x", "nginx"])
        authenticator = args["authenticator"]
        if authenticator == "nginx":
            authenticator_available = (
                findings["certbot_available"]
                and "nginx" in findings["certbot_authenticators"]
                and nginx_code == 0
            )
            credentials_secure = None
        elif authenticator == "webroot":
            webroot = Path(args["webroot_path"])
            authenticator_available = (
                findings["certbot_available"]
                and "webroot" in findings["certbot_authenticators"]
                and webroot.is_dir()
                and os.access(webroot, os.W_OK)
            )
            credentials_secure = None
        else:
            credentials_path = args.get("dns_credentials_path")
            try:
                credentials_root = Path("/etc/letsencrypt/credentials")
                root_resolved = credentials_root.resolve(strict=True)
                path = Path(credentials_path) if credentials_path else None
                file_stat = path.lstat() if path else None
                resolved_path = path.resolve(strict=True) if path else None
                mode = file_stat.st_mode & 0o777 if file_stat else 0o777
                credentials_secure = (
                    root_resolved == credentials_root
                    and resolved_path is not None
                    and resolved_path != root_resolved
                    and resolved_path.is_relative_to(root_resolved)
                    and file_stat is not None
                    and stat.S_ISREG(file_stat.st_mode)
                    and mode in {0o400, 0o600}
                )
            except OSError:
                credentials_secure = False
            authenticator_available = (
                findings["certbot_available"]
                and "dns-rfc2136" in findings["certbot_authenticators"]
                and credentials_secure
            )
        findings.update(
            {
                "directory_valid": directory_ok,
                "directory_error": directory_error,
                "resolved_addresses": resolved,
                "resolution_perspective": "requesting_node",
                "webroot_exists": Path(args["webroot_path"]).is_dir(),
                "webroot_writable": os.access(args["webroot_path"], os.W_OK),
                "nginx_running": None if nginx_code is None else nginx_code == 0,
                "selected_authenticator": authenticator,
                "authenticator_available": authenticator_available,
                "dns_credentials_secure": credentials_secure,
                "ca_challenge_reachability": "unverified",
                "ca_http01_reachability": (
                    "unverified" if authenticator in ("nginx", "webroot") else None
                ),
                "ready_for_issuance": None,
            }
        )
        return findings
    raise ValueError("Unknown action")
