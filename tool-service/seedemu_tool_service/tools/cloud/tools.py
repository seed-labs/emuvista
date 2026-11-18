"""Nextcloud operations executed from emulated source containers."""

import base64
import hashlib
import json
from dataclasses import dataclass
from shlex import quote
from urllib.parse import quote as url_quote
from urllib.parse import urlparse

import docker
from docker.errors import DockerException

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.cloud.models import (
    CloudServiceLocation,
    CloudStorageFindResult,
    FileDownloadResult,
    FileShareResult,
    FileUploadResult,
)

_SERVICE_ID_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.service_id"
_PROVIDER_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.provider"
_WEBDAV_URL_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.webdav_url"
_OCS_URL_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.ocs_url"
_SOURCE_SERVICES_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.services"
_SOURCE_CREDENTIALS_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.credentials"
_MAX_TRANSFER_BYTES = 256 * 1024


class CloudMetadataError(RuntimeError):
    """Raised when cloud metadata is missing, inconsistent, or unauthorized."""


@dataclass(frozen=True)
class _CloudService:
    location: CloudServiceLocation
    credential_dir: str


class CloudTools:
    """Discover and operate explicitly exposed Nextcloud services."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def storage_find(self, source: str) -> CloudStorageFindResult:
        """Discover only cloud services explicitly assigned to ``source``."""

        services, credentials = self._source_metadata(source)
        locations = [self._service_location(service_id, credentials[service_id]) for service_id in services]
        return CloudStorageFindResult(source=source, services=locations)

    def file_upload(self, source: str, service_id: str, path: str, content_base64: str) -> FileUploadResult:
        """Upload bounded content through WebDAV from the selected source node."""

        service = self._authorized_service(source, service_id)
        content = base64.b64decode(content_base64, validate=True)
        encoded_path = self._encoded_path(path)
        script = self._credential_prelude(service.credential_dir) + [
            f"webdav={quote(service.location.webdav_url)}",
            f"printf %s {quote(content_base64)} | base64 -d | curl --fail --silent --show-error "
            f"--max-time 30 --max-filesize {_MAX_TRANSFER_BYTES} --user \"$username:$password\" "
            f"--upload-file - --output /dev/null --write-out '__SEED_CLOUD_HTTP__%{{http_code}}' "
            f"--url \"$webdav/files/$username{encoded_path}\"",
        ]
        result = self._backend.execute(source, ["sh", "-c", "\n".join(script)])
        status = self._http_status(result.stdout)
        return FileUploadResult(
            source=source, service_id=service_id, path=path,
            successful=result.exit_code == 0 and status in {200, 201, 204},
            exit_code=result.exit_code, http_status=status, stderr=result.stderr,
            bytes_uploaded=len(content), sha256=hashlib.sha256(content).hexdigest(),
        )

    def file_download(self, source: str, service_id: str, path: str) -> FileDownloadResult:
        """Download one bounded WebDAV object from the selected source node."""

        service = self._authorized_service(source, service_id)
        encoded_path = self._encoded_path(path)
        script = self._credential_prelude(service.credential_dir) + [
            f"webdav={quote(service.location.webdav_url)}",
            "file=$(mktemp)", "trap 'rm -f \"$file\"' EXIT",
            f"curl --fail --silent --show-error --max-time 30 --max-filesize {_MAX_TRANSFER_BYTES} "
            f"--user \"$username:$password\" --output \"$file\" --write-out '__SEED_CLOUD_HTTP__%{{http_code}}' "
            f"--url \"$webdav/files/$username{encoded_path}\"",
            "printf '\\n__SEED_CLOUD_BYTES__%s\\n' \"$(wc -c < \"$file\")\"",
            "printf '__SEED_CLOUD_SHA256__%s\\n' \"$(sha256sum \"$file\" | cut -d' ' -f1)\"",
            "printf '__SEED_CLOUD_CONTENT__'; base64 -w0 \"$file\"; printf '\\n'",
        ]
        result = self._backend.execute(source, ["sh", "-c", "\n".join(script)])
        status = self._http_status(result.stdout)
        values = self._markers(result.stdout)
        content_base64 = values.get("CONTENT", "")
        return FileDownloadResult(
            source=source, service_id=service_id, path=path,
            successful=result.exit_code == 0 and status == 200 and bool(content_base64),
            exit_code=result.exit_code, http_status=status, stderr=result.stderr,
            content_base64=content_base64, bytes_downloaded=int(values.get("BYTES", "0")),
            sha256=values.get("SHA256"),
        )

    def file_share(
        self, source: str, service_id: str, path: str, recipient: str, permission: str = "read"
    ) -> FileShareResult:
        """Create a read-only Nextcloud user share through its OCS API."""

        service = self._authorized_service(source, service_id)
        if permission != "read":
            raise ValueError("only read permission is currently supported")
        script = self._credential_prelude(service.credential_dir) + [
            "response=$(mktemp)", "trap 'rm -f \"$response\"' EXIT",
            f"curl --fail --silent --show-error --max-time 30 --user \"$username:$password\" "
            "--header 'OCS-APIRequest: true' --header 'Accept: application/json' --request POST "
            f"--data-urlencode {quote('path=' + path.lstrip('/'))} --data 'shareType=0' "
            f"--data-urlencode {quote('shareWith=' + recipient)} --output \"$response\" "
            f"--write-out '__SEED_CLOUD_HTTP__%{{http_code}}' --url {quote(service.location.ocs_url + '/apps/files_sharing/api/v1/shares')}",
            "printf '\\n__SEED_CLOUD_RESPONSE__'; base64 -w0 \"$response\"; printf '\\n'",
        ]
        result = self._backend.execute(source, ["sh", "-c", "\n".join(script)])
        status = self._http_status(result.stdout)
        values = self._markers(result.stdout)
        response: dict = {}
        try:
            response = json.loads(base64.b64decode(values.get("RESPONSE", ""), validate=True))
        except (ValueError, json.JSONDecodeError):
            pass
        ocs = response.get("ocs") if isinstance(response, dict) else None
        meta = ocs.get("meta") if isinstance(ocs, dict) else None
        data = ocs.get("data") if isinstance(ocs, dict) else None
        ocs_status = meta.get("status") if isinstance(meta, dict) else None
        share_id = str(data.get("id")) if isinstance(data, dict) and data.get("id") is not None else None
        return FileShareResult(
            source=source, service_id=service_id, path=path, recipient=recipient,
            successful=result.exit_code == 0 and status in {200, 201} and ocs_status == "ok",
            exit_code=result.exit_code, http_status=status, stderr=result.stderr,
            share_id=share_id, ocs_status=ocs_status,
        )

    def _authorized_service(self, source: str, service_id: str) -> _CloudService:
        services, credentials = self._source_metadata(source)
        if service_id not in services:
            raise CloudMetadataError("service_id is not assigned to this source")
        return _CloudService(self._service_location(service_id, credentials[service_id]), self._credential_dir(service_id))

    def _source_metadata(self, source: str) -> tuple[list[str], dict[str, str]]:
        try:
            container = docker.from_env().containers.get(source)
        except DockerException as error:
            raise CloudMetadataError("source container metadata lookup failed") from error
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        raw_services = labels.get(_SOURCE_SERVICES_LABEL)
        raw_credentials = labels.get(_SOURCE_CREDENTIALS_LABEL)
        if not raw_services or not raw_credentials:
            return [], {}
        services = raw_services.split(",")
        if any(not item or any(character.isspace() for character in item) for item in services):
            raise CloudMetadataError("source cloud service directory is invalid")
        try:
            credentials = json.loads(raw_credentials)
        except json.JSONDecodeError as error:
            raise CloudMetadataError("source cloud credential directory is invalid") from error
        if not isinstance(credentials, dict) or set(credentials) != set(services) or any(
            not isinstance(value, str) or not value for value in credentials.values()
        ):
            raise CloudMetadataError("source cloud credential directory is incomplete")
        return sorted(services), credentials

    def _service_location(self, service_id: str, credential_ref: str) -> CloudServiceLocation:
        try:
            containers = docker.from_env().containers.list(filters={"label": _SERVICE_ID_LABEL})
        except DockerException as error:
            raise CloudMetadataError("cloud service metadata lookup failed") from error
        matches = []
        for container in containers:
            labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
            if labels.get(_SERVICE_ID_LABEL) == service_id:
                matches.append(labels)
        if len(matches) != 1:
            raise CloudMetadataError("cloud service_id must resolve to exactly one service")
        labels = matches[0]
        if labels.get(_PROVIDER_LABEL) != "nextcloud":
            raise CloudMetadataError("cloud service provider is unsupported")
        webdav_url = labels.get(_WEBDAV_URL_LABEL)
        ocs_url = labels.get(_OCS_URL_LABEL)
        if not isinstance(webdav_url, str) or not isinstance(ocs_url, str):
            raise CloudMetadataError("cloud service endpoint metadata is incomplete")
        self._validate_origin(webdav_url, "webdav_url")
        self._validate_origin(ocs_url, "ocs_url")
        return CloudServiceLocation(
            service_id=service_id, provider="nextcloud", webdav_url=webdav_url.rstrip("/"),
            ocs_url=ocs_url.rstrip("/"), credential_ref=credential_ref,
        )

    @staticmethod
    def _credential_prelude(credential_dir: str) -> list[str]:
        return [
            "set -eu", f"credential={quote(credential_dir + '/credentials')}",
            "test -r \"$credential\"", "username=$(sed -n '1p' \"$credential\")",
            "password=$(sed -n '2p' \"$credential\")", "test -n \"$username\" && test -n \"$password\"",
        ]

    @staticmethod
    def _credential_dir(service_id: str) -> str:
        return "/opt/seedemu/cloud/" + service_id

    @staticmethod
    def _encoded_path(path: str) -> str:
        return "/" + "/".join(url_quote(part, safe="") for part in path.lstrip("/").split("/"))

    @staticmethod
    def _validate_origin(value: str, field: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CloudMetadataError(f"cloud {field} must be an HTTP(S) URL without credentials")

    @staticmethod
    def _http_status(stdout: str) -> int | None:
        marker = "__SEED_CLOUD_HTTP__"
        _, found, value = stdout.partition(marker)
        return int(value.splitlines()[0]) if found and value.splitlines()[0].isdigit() else None

    @staticmethod
    def _markers(stdout: str) -> dict[str, str]:
        markers: dict[str, str] = {}
        for line in stdout.splitlines():
            if line.startswith("__SEED_CLOUD_") and "__" in line.removeprefix("__SEED_CLOUD_"):
                key, _, value = line.removeprefix("__SEED_CLOUD_").partition("__")
                markers[key] = value
        return markers
