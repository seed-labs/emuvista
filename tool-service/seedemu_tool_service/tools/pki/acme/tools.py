"""ACME certificate lifecycle tool implementations."""

import re
from pathlib import PurePosixPath

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.runtime import RuntimeCommandResult
from seedemu_tool_service.tools.pki.acme.models import ACMECertificateResult
from seedemu_tool_service.tools.pki.acme.inspection import ACMEInspectionTools
from seedemu_tool_service.tools.pki.shared.ca_service import (
    ca_directory_urls,
    inspect_ca_service,
)


class ACMETools:
    """Operate a real ACME client inside an emulated service container."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def request_acme_certificate(
        self,
        source: str,
        ca_service_source: str,
        ca_service_config_path: str,
        directory_url: str,
        domains: list[str],
        email: str,
        authenticator: str = "nginx",
        webroot_path: str = "/var/www/html",
        cert_name: str | None = None,
        force_renewal: bool = False,
        dns_credentials_path: str | None = None,
        dns_propagation_seconds: int = 30,
    ) -> ACMECertificateResult:
        """Use an installed Certbot authenticator to request an ACME certificate."""
        name = cert_name or domains[0].removeprefix("*.")
        if not _directory_belongs_to_ca(
            self._backend, ca_service_source, ca_service_config_path, directory_url
        ):
            return _failed_acme_result(
                "request",
                source,
                "ACME directory is not configured by the selected SEEDEmu CA Service",
            )
        renewal_path = f"/etc/letsencrypt/renewal/{name}.conf"
        existed = self._backend.execute(source, ["test", "-e", renewal_path]).exit_code == 0
        client = self._backend.execute(source, ["certbot", "--version"])
        if client.exit_code != 0:
            return ACMECertificateResult(
                action="request",
                source=source,
                successful=False,
                cert_name=name,
                domains=domains,
                exit_code=client.exit_code or 127,
                output=client.stdout,
                stderr=client.stderr or "Certbot is not installed on the selected node",
            )
        command = [
            "certbot",
            "certonly",
            "--non-interactive",
            "--agree-tos",
            "--no-eff-email",
            "--server",
            directory_url,
            "--email",
            email,
            "--cert-name",
            name,
        ]
        if authenticator == "nginx":
            command.append("--nginx")
        elif authenticator == "webroot":
            command.extend(["--webroot", "--webroot-path", webroot_path])
        else:
            if not dns_credentials_path:
                return ACMECertificateResult(
                    action="request",
                    source=source,
                    successful=False,
                    cert_name=name,
                    domains=domains,
                    exit_code=2,
                    output="",
                    stderr="dns-rfc2136 requires a credentials file",
                )
            credentials_file = self._backend.execute(
                source,
                ["test", "-f", dns_credentials_path, "-a", "!", "-L", dns_credentials_path],
            )
            resolved_root = self._backend.execute(
                source,
                ["realpath", "-e", "--", "/etc/letsencrypt/credentials"],
            )
            resolved_file = self._backend.execute(
                source, ["realpath", "-e", "--", dns_credentials_path]
            )
            credentials_root = PurePosixPath("/etc/letsencrypt/credentials")
            canonical_root = PurePosixPath(resolved_root.stdout.strip())
            canonical_file = PurePosixPath(resolved_file.stdout.strip())
            credentials_path_scoped = (
                resolved_root.exit_code == 0
                and resolved_file.exit_code == 0
                and canonical_root == credentials_root
                and canonical_file.is_relative_to(credentials_root)
                and canonical_file != credentials_root
            )
            permissions = self._backend.execute(
                source, ["stat", "-c", "%a", "--", dns_credentials_path]
            )
            try:
                mode = int(permissions.stdout.strip(), 8)
            except ValueError:
                mode = 0o777
            if (
                credentials_file.exit_code != 0
                or not credentials_path_scoped
                or permissions.exit_code != 0
                or mode not in {0o400, 0o600}
            ):
                return ACMECertificateResult(
                    action="request",
                    source=source,
                    successful=False,
                    cert_name=name,
                    domains=domains,
                    exit_code=permissions.exit_code or 2,
                    output=permissions.stdout,
                    stderr=(
                        permissions.stderr
                        or "DNS credentials must exist and be readable only by their owner"
                    ),
                )
            plugins = self._backend.execute(source, ["certbot", "plugins", "--text"])
            if plugins.exit_code != 0 or "dns-rfc2136" not in plugins.stdout:
                return ACMECertificateResult(
                    action="request",
                    source=source,
                    successful=False,
                    cert_name=name,
                    domains=domains,
                    exit_code=plugins.exit_code or 2,
                    output=plugins.stdout,
                    stderr=plugins.stderr or "Certbot dns-rfc2136 plugin is not installed",
                )
            command.extend(
                [
                    "--authenticator",
                    "dns-rfc2136",
                    "--dns-rfc2136-credentials",
                    dns_credentials_path,
                    "--dns-rfc2136-propagation-seconds",
                    str(dns_propagation_seconds),
                ]
            )
        if force_renewal:
            command.append("--force-renewal")
        for domain in domains:
            command.extend(["-d", domain])

        result = self._backend.execute(source, command)
        return _certificate_result("request", source, name, domains, result, existed=existed)

    def renew_acme_certificate(
        self,
        source: str,
        ca_service_source: str,
        ca_service_config_path: str,
        cert_name: str,
        force_renewal: bool = False,
    ) -> ACMECertificateResult:
        """Renew a certificate using its Certbot renewal configuration."""
        renewal = ACMEInspectionTools(self._backend).inspect_renewal_server(
            source, cert_name
        )
        configured_url = renewal.data.get("server")
        if (
            not renewal.successful
            or not isinstance(configured_url, str)
            or not _directory_belongs_to_ca(
                self._backend, ca_service_source, ca_service_config_path, configured_url
            )
        ):
            return _failed_acme_result(
                "renew",
                source,
                "Renewal configuration does not target the selected SEEDEmu CA Service",
            )
        client = self._backend.execute(source, ["certbot", "--version"])
        if client.exit_code != 0:
            return ACMECertificateResult(
                action="renew",
                source=source,
                successful=False,
                cert_name=cert_name,
                exit_code=client.exit_code or 127,
                output=client.stdout,
                stderr=client.stderr or "Certbot is not installed on the selected node",
            )
        command = ["certbot", "renew", "--non-interactive", "--cert-name", cert_name]
        if force_renewal:
            command.append("--force-renewal")
        result = self._backend.execute(source, command)
        return _certificate_result("renew", source, cert_name, [], result)

    def deploy_acme_certificate_to_nginx(
        self, source: str, cert_name: str, server_name: str
    ) -> ACMECertificateResult:
        """Add an isolated TLS site without replacing SEEDEmu's default nginx site."""
        base = f"/etc/letsencrypt/live/{cert_name}"
        fullchain = f"{base}/fullchain.pem"
        private_key = f"{base}/privkey.pem"
        config_name = f"seedemu-pki-{cert_name}.conf"
        config_path = f"/etc/nginx/sites-available/{config_name}"
        enabled_path = f"/etc/nginx/sites-enabled/{config_name}"

        for path in [fullchain, private_key]:
            check = self._backend.execute(source, ["test", "-f", path])
            if check.exit_code != 0:
                return ACMECertificateResult(
                    action="deploy",
                    source=source,
                    successful=False,
                    cert_name=cert_name,
                    certificate_path=fullchain,
                    private_key_path=private_key,
                    exit_code=check.exit_code,
                    output=check.stdout,
                    stderr=check.stderr or f"certificate material not found: {path}",
                )

        existing_config = self._backend.execute(source, ["nginx", "-T"])
        if existing_config.exit_code != 0:
            safe_failure = RuntimeCommandResult(
                exit_code=existing_config.exit_code,
                stdout="",
                stderr="nginx configuration inspection failed; configuration output withheld",
            )
            return _deployment_result(
                source, cert_name, server_name, safe_failure, False
            )
        server_names = [
            name
            for declaration in re.findall(
                r"(?m)^\s*server_name\s+([^;]+);", existing_config.stdout
            )
            for name in declaration.split()
        ]
        if "ssl_certificate" in existing_config.stdout and server_name in server_names:
            return ACMECertificateResult(
                action="deploy",
                source=source,
                successful=False,
                cert_name=cert_name,
                domains=[server_name],
                fullchain_path=fullchain,
                private_key_path=private_key,
                exit_code=2,
                output="",
                stderr=(
                    "nginx already declares this name and has TLS configured; "
                    "use pki.verify_tls_deployment instead of adding a duplicate"
                ),
            )

        for path in (config_path, enabled_path):
            preflight = self._backend.execute(source, ["test", "!", "-e", path])
            if preflight.exit_code != 0:
                return _deployment_result(source, cert_name, server_name, preflight, False)

        config = _nginx_tls_config(server_name, fullchain, private_key)
        write = self._backend.execute(
            source,
            [
                "sh",
                "-c",
                'umask 022; printf "%s" "$1" > "$2"',
                "seedemu-pki",
                config,
                config_path,
            ],
        )
        if write.exit_code != 0:
            self._backend.execute(source, ["rm", "-f", "--", config_path])
            return _deployment_result(source, cert_name, server_name, write, False)

        link = self._backend.execute(source, ["ln", "-s", config_path, enabled_path])
        if link.exit_code != 0:
            self._backend.execute(source, ["rm", "-f", "--", config_path])
            return _deployment_result(source, cert_name, server_name, link, False)

        check = self._backend.execute(source, ["nginx", "-t"])
        if check.exit_code != 0:
            self._backend.execute(source, ["rm", "-f", "--", enabled_path, config_path])
            return _deployment_result(source, cert_name, server_name, check, False)

        reload_result = self._backend.execute(source, ["nginx", "-s", "reload"])
        if reload_result.exit_code != 0:
            self._backend.execute(source, ["rm", "-f", "--", enabled_path, config_path])
            self._backend.execute(source, ["nginx", "-s", "reload"])
            return _deployment_result(source, cert_name, server_name, reload_result, False)
        return _deployment_result(
            source, cert_name, server_name, reload_result, True, config_path, enabled_path
        )

    def revoke_acme_certificate(
        self,
        source: str,
        ca_service_source: str,
        ca_service_config_path: str,
        directory_url: str,
        certificate_path: str,
        reason: str = "unspecified",
        delete_after_revoke: bool = False,
    ) -> ACMECertificateResult:
        """Revoke a certificate through the configured ACME CA."""
        if not _directory_belongs_to_ca(
            self._backend, ca_service_source, ca_service_config_path, directory_url
        ):
            return _failed_acme_result(
                "revoke",
                source,
                "ACME directory is not configured by the selected SEEDEmu CA Service",
            )
        client = self._backend.execute(source, ["certbot", "--version"])
        if client.exit_code != 0:
            return ACMECertificateResult(
                action="revoke",
                source=source,
                successful=False,
                certificate_path=certificate_path,
                exit_code=client.exit_code or 127,
                output=client.stdout,
                stderr=client.stderr or "Certbot is not installed on the selected node",
            )
        command = [
            "certbot",
            "revoke",
            "--non-interactive",
            "--server",
            directory_url,
            "--cert-path",
            certificate_path,
            "--reason",
            reason,
        ]
        if delete_after_revoke:
            command.append("--delete-after-revoke")
        result = self._backend.execute(source, command)
        return ACMECertificateResult(
            action="revoke",
            source=source,
            successful=result.exit_code == 0,
            certificate_path=certificate_path,
            modified_paths=[certificate_path] if result.exit_code == 0 else [],
            exit_code=result.exit_code,
            output=result.stdout,
            stderr=result.stderr,
        )


def _certificate_result(
    action: str,
    source: str,
    cert_name: str,
    domains: list[str],
    result: RuntimeCommandResult,
    existed: bool = True,
) -> ACMECertificateResult:
    base = f"/etc/letsencrypt/live/{cert_name}"
    paths = {
        "certificate_path": f"{base}/cert.pem",
        "chain_path": f"{base}/chain.pem",
        "fullchain_path": f"{base}/fullchain.pem",
        "private_key_path": f"{base}/privkey.pem",
        "renewal_config_path": f"/etc/letsencrypt/renewal/{cert_name}.conf",
    }
    changed = list(paths.values()) if result.exit_code == 0 else []
    return ACMECertificateResult(
        action=action,
        source=source,
        successful=result.exit_code == 0,
        cert_name=cert_name,
        domains=domains,
        **paths,
        created_paths=changed if action == "request" and not existed else [],
        modified_paths=changed if action == "renew" or (action == "request" and existed) else [],
        exit_code=result.exit_code,
        output=result.stdout,
        stderr=result.stderr,
    )


def _directory_belongs_to_ca(
    backend: RuntimeBackend, ca_source: str, config_path: str, directory_url: str
) -> bool:
    observation = inspect_ca_service(backend, ca_source, config_path)
    return observation.successful and directory_url in ca_directory_urls(observation)


def _failed_acme_result(action: str, source: str, message: str) -> ACMECertificateResult:
    return ACMECertificateResult(
        action=action,
        source=source,
        successful=False,
        exit_code=2,
        output="",
        stderr=message,
    )


def _deployment_result(
    source: str,
    cert_name: str,
    server_name: str,
    result: RuntimeCommandResult,
    successful: bool,
    config_path: str | None = None,
    enabled_path: str | None = None,
) -> ACMECertificateResult:
    base = f"/etc/letsencrypt/live/{cert_name}"
    return ACMECertificateResult(
        action="deploy",
        source=source,
        successful=successful,
        cert_name=cert_name,
        domains=[server_name],
        fullchain_path=f"{base}/fullchain.pem",
        private_key_path=f"{base}/privkey.pem",
        modified_paths=(
            [config_path, enabled_path]
            if successful and config_path and enabled_path
            else []
        ),
        backup_paths=[],
        exit_code=result.exit_code,
        output=result.stdout,
        stderr=result.stderr,
    )


def _nginx_tls_config(server_name: str, fullchain: str, private_key: str) -> str:
    return f"""server {{
    listen 443 ssl;
    server_name {server_name};
    root /var/www/html;
    index index.html;
    ssl_certificate {fullchain};
    ssl_certificate_key {private_key};
    location / {{ try_files $uri $uri/ =404; }}
}}
"""
