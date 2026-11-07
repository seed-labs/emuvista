"""Node-local ACME discovery, independent of Certbot's mutable CLI listing."""

from pathlib import Path

from ..execution import RuntimeBackend
from ..shared.runtime import NodeObservation, observe
from ..shared.ca_service import (
    ca_directory_urls,
    inspect_ca_service,
)


class ACMEInspectionTools:
    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def _inspect_acme(self, action: str, source: str, **arguments: object) -> NodeObservation:
        return observe(
            self._backend,
            source,
            Path(__file__).with_name("inspection_probe.py"),
            {"action": action, **arguments},
        )

    def inspect_renewal_server(self, source: str, cert_name: str) -> NodeObservation:
        """Parse one Certbot renewal server setting, rejecting duplicate INI keys."""
        return self._inspect_acme(
            "renewal_server",
            source,
            config_path=f"/etc/letsencrypt/renewal/{cert_name}.conf",
        )

    def inspect_environment(self, source: str, ca_bundle_path: str) -> NodeObservation:
        return self._inspect_acme("environment", source, ca_bundle_path=ca_bundle_path)

    def list_managed_certificates(
        self, source: str, config_directory: str, limit: int
    ) -> NodeObservation:
        return self._inspect_acme(
            "certificates", source, config_directory=config_directory, limit=limit
        )

    def inspect_renewal_status(
        self,
        source: str,
        cert_name: str,
        config_directory: str,
        log_path: str = "/var/log/letsencrypt/letsencrypt.log",
    ) -> NodeObservation:
        return self._inspect_acme(
            "renewal",
            source,
            cert_name=cert_name,
            config_directory=config_directory,
            log_path=log_path,
        )

    def inspect_acme_readiness(
        self,
        source: str,
        ca_bundle_path: str,
        ca_service_source: str,
        ca_service_config_path: str,
        directory_url: str,
        domains: list[str],
        webroot_path: str,
        timeout_seconds: int,
        authenticator: str = "nginx",
        dns_credentials_path: str | None = None,
    ) -> NodeObservation:
        ca_observation = inspect_ca_service(
            self._backend, ca_service_source, ca_service_config_path
        )
        if (
            not ca_observation.successful
            or directory_url not in ca_directory_urls(ca_observation)
        ):
            return NodeObservation(
                source=source,
                successful=False,
                data={},
                exit_code=2,
                error="ACME directory is not configured by the selected SEEDEmu CA Service",
            )
        return self._inspect_acme(
            "readiness",
            source,
            ca_bundle_path=ca_bundle_path,
            ca_service_source=ca_service_source,
            ca_service_config_path=ca_service_config_path,
            directory_url=directory_url,
            domains=domains,
            webroot_path=webroot_path,
            authenticator=authenticator,
            dns_credentials_path=dns_credentials_path,
            timeout_seconds=timeout_seconds,
        )
