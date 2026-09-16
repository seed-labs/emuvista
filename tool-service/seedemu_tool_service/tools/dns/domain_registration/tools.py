"""Domain Registration DNS implementations."""

import base64
import json
import re
from hashlib import sha256
from shlex import quote
from urllib.parse import quote as url_quote
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import docker
from docker.errors import DockerException

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.dns.domain_registration.models import (
    DNSAuthoritativeFindResult,
    DNSConfigureResult,
    DNSRecordChange,
    DNSServiceLocation,
    RddsAuthority,
    RddsLookupResult,
    RddsProtocol,
    RegistrarFindResult,
    RegistrarLocation,
    RegistrarRequestMethod,
    RegistrarRequestResult,
)

_REGISTRAR_URL_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.registrar_url"
_REGISTRAR_CREDENTIAL_REF_LABEL = (
    "org.seedsecuritylabs.seedemu.meta.agent.exposed.registrar_credential_ref"
)
_REGISTRAR_RESPONSE_LIMIT = 256 * 1024
_RDDS_RESPONSE_LIMIT = 256 * 1024
_RDDS_AUTHORITY_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.authority"
_RDDS_WHOIS_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.whois_server"
_RDDS_RDAP_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.rdap_url"
_DNS_SERVICE_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.service_id"
_DNS_ROLE_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.role"
_DNS_PRIMARY_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.primary"
_DNS_SECONDARY_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.secondary"
_DNS_CREDENTIAL_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.credential_ref"
_DNS_SOURCE_SERVICES_LABEL = (
    "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.authoritative_services"
)


class RegistrarMetadataError(RuntimeError):
    """Raised when allowlisted Registrar metadata cannot be read."""


class DomainRegistrationTools:
    """Domain Registration DNS operations."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def registrar_find(self, filter: dict[str, str] | None = None) -> RegistrarFindResult:
        """Return Registrar frontends explicitly exposed by the emulator."""

        if filter:
            raise ValueError("filter is reserved and must currently be empty")

        try:
            containers = docker.from_env().containers.list(filters={"label": _REGISTRAR_URL_LABEL})
        except DockerException as error:
            raise RegistrarMetadataError("Docker metadata lookup failed") from error

        registrars: dict[str, str | None] = {}
        for container in containers:
            labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
            registrar_url = labels.get(_REGISTRAR_URL_LABEL)
            if not isinstance(registrar_url, str) or not registrar_url:
                raise RegistrarMetadataError("Exposed registrar URL label is missing")
            credential_ref = labels.get(_REGISTRAR_CREDENTIAL_REF_LABEL)
            if credential_ref is not None and not isinstance(credential_ref, str):
                raise RegistrarMetadataError("Registrar credential reference is invalid")
            normalized_url = registrar_url.rstrip("/")
            normalized_ref = credential_ref or None
            previous_ref = registrars.get(normalized_url)
            if previous_ref and normalized_ref and previous_ref != normalized_ref:
                raise RegistrarMetadataError("Conflicting Registrar credential references")
            if normalized_url not in registrars or previous_ref is None:
                registrars[normalized_url] = normalized_ref
        return RegistrarFindResult(
            registrars=[
                RegistrarLocation(registrar_url=url, credential_ref=registrars[url])
                for url in sorted(registrars)
            ]
        )

    def registrar_request(
        self,
        source: str,
        registrar_url: str,
        method: RegistrarRequestMethod = "GET",
        path: str = "/",
        content_type: str | None = None,
        body: str | None = None,
        session_id: str | None = None,
        close_session: bool = False,
        authentication: str = "auto",
    ) -> RegistrarRequestResult:
        """Make one bounded, non-redirecting request to a Registrar origin."""

        directory = self.registrar_find().registrars
        allowed_urls = {registrar.registrar_url for registrar in directory}
        if registrar_url not in allowed_urls:
            raise RegistrarMetadataError(
                "registrar_url is not present in the current exposed Registrar directory"
            )

        # Validate direct Python calls as well as registered tool calls.
        from seedemu_tool_service.tools.dns.domain_registration.models import (
            RegistrarRequestArguments,
        )

        arguments = RegistrarRequestArguments(
            source=source,
            registrar_url=registrar_url,
            method=method,
            path=path,
            content_type=content_type,
            body=body,
            session_id=session_id,
            close_session=close_session,
            authentication=authentication,
        ).model_dump()
        arguments["url"] = urljoin(f"{registrar_url}/", path.lstrip("/"))
        # Source-local filesystem is the identity boundary; flock spans workers.
        root = "/var/lib/seedemu/registrar/" + sha256(registrar_url.encode()).hexdigest()
        new_session = session_id is None
        session_id = session_id or uuid4().hex
        session = root + "/session-" + session_id
        q = quote
        lines = [
            "set -eu",
            "umask 077",
            f"mkdir -p {q(root)}",
            f"exec 9>{q(root + '/lock')}",
            "flock -x 9",
        ]
        if new_session:
            lines += [f"mkdir {q(session)}", f": > {q(session + '/cookies')}"]
        else:
            lines += [f"test -f {q(session + '/cookies')} || exit 42"]
        if close_session:
            cleanup = f"rm -f {q(session + '/cookies')}; rmdir {q(session)}"
            lines += ["trap " + q(cleanup) + " EXIT"]
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "30",
            "--max-redirs",
            "0",
            "--max-filesize",
            "262144",
            "--proto",
            "=http,https",
            "--request",
            method,
            "--cookie",
            session + "/cookies",
            "--cookie-jar",
            session + "/cookies",
            "--dump-header",
            "-",
            "--write-out",
            "\n__SEED_REGISTRAR_HEADERS__%{http_code}",
            "--header",
            "Accept: text/html,application/javascript,application/json,text/plain",
        ]
        if body is not None:
            command += ["--header", "Content-Type: " + content_type]
        credentials = "/opt/seedemu/registrar/" + sha256(registrar_url.encode()).hexdigest()
        ca_file = credentials + "/ca.crt"
        # Public trust material and token stay in source; nothing reads token into Python.
        lines += [
            "set --",
            f"if [ -f {q(ca_file)} ]; then set -- --cacert {q(ca_file)}; fi",
            "authenticated=0",
        ]
        if authentication != "none":
            lines += [
                f"if [ -f {q(credentials + '/token')} ] && "
                f"[ -f {q(credentials + '/source-id')} ]; then"
            ]
            if not registrar_url.startswith("https://"):
                lines += ["exit 46"]
            else:
                auth_command = [
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "30",
                    "--proto",
                    "=https",
                    "--cookie",
                    session + "/cookies",
                    "--cookie-jar",
                    session + "/cookies",
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code}",
                    "--data-urlencode",
                    "source_id@" + credentials + "/source-id",
                    "--data-urlencode",
                    "token@" + credentials + "/token",
                    "--url",
                    registrar_url + "/seedemu-source-auth.php",
                ]
                auth_shell = 'curl "$@" ' + " ".join(q(part) for part in auth_command)
                lines += [
                    "code=$(" + auth_shell + ") || exit 46",
                    '[ "$code" = 204 ] || exit 45',
                    "authenticated=1",
                ]
            lines += ["else"]
            lines += ["exit 44" if authentication == "required" else ":"]
            lines += ["fi"]
        if body is not None:
            command += ["--data", body]
        command += ["--url", arguments["url"]]
        lines += [
            'printf "__SEED_REGISTRAR_AUTH__%s\\n" "$authenticated"',
            'curl "$@" ' + " ".join(q(part) for part in command[1:]),
        ]
        result = self._backend.execute(source, ["sh", "-c", "\n".join(lines)])
        if result.exit_code in {42, 44, 45, 46}:
            raise RegistrarMetadataError(
                {
                    42: "Unknown session in this source/Registrar",
                    44: "No source identity configured for this Registrar",
                    45: "Registrar rejected source authentication",
                    46: "Source authentication requires trusted HTTPS and a reachable Registrar",
                }[result.exit_code]
            )
        authenticated = result.stdout.startswith("__SEED_REGISTRAR_AUTH__1\n")
        stdout = result.stdout
        if stdout.startswith("__SEED_REGISTRAR_AUTH__"):
            stdout = stdout.partition("\n")[2]
        header_marker = "__SEED_REGISTRAR_HEADERS__"
        response_text, marker, status_text = stdout.rpartition(f"\n{header_marker}")
        http_status = int(status_text) if marker and status_text.isdigit() else None
        raw_headers, separator, response_body = response_text.partition("\r\n\r\n")
        if not separator:
            raw_headers, separator, response_body = response_text.partition("\n\n")
        headers: dict[str, str] = {}
        if separator:
            for line in raw_headers.splitlines()[1:]:
                name, colon, value = line.partition(":")
                if colon:
                    headers[name.strip().lower()] = value.strip()
        else:
            response_body = response_text
        stderr = result.stderr
        encoded = response_body.encode("utf-8")
        truncated = len(encoded) > _REGISTRAR_RESPONSE_LIMIT
        if truncated:
            response_body = encoded[:_REGISTRAR_RESPONSE_LIMIT].decode("utf-8", errors="replace")
        transport_successful = result.exit_code == 0 and http_status is not None
        return RegistrarRequestResult(
            registrar_url=registrar_url,
            session_id=session_id,
            authenticated=authenticated,
            requested_path=path,
            method=method,
            transport_successful=transport_successful,
            http_status=http_status,
            successful=transport_successful and 200 <= http_status < 300,
            content_type=headers.get("content-type"),
            location=headers.get("location"),
            body=response_body,
            truncated=truncated,
            exit_code=result.exit_code,
            stderr=stderr,
        )

    def rdds_lookup(
        self,
        source: str,
        protocol: RddsProtocol,
        authority: RddsAuthority,
        domain: str,
    ) -> RddsLookupResult:
        """Query a metadata-published Registrar or Registry WHOIS/RDAP endpoint."""
        from seedemu_tool_service.tools.dns.domain_registration.models import (
            RddsLookupArguments,
        )

        arguments = RddsLookupArguments(
            source=source, protocol=protocol, authority=authority, domain=domain
        )
        endpoint = self._rdds_endpoint(arguments.authority, arguments.protocol)
        marker = "__SEED_RDDS_RESPONSE__"
        if arguments.protocol == "whois":
            result = self._backend.execute(
                arguments.source, ["whois", "-h", endpoint, arguments.domain]
            )
            body = result.stdout
            http_status = None
            content_type = None
            transport_successful = result.exit_code == 0
            successful = transport_successful
            found = (
                not bool(re.search(r"(?im)^(?:NOT FOUND|No match|No Data Found)\b", body))
                if transport_successful
                else None
            )
        else:
            url = endpoint + "/domain/" + url_quote(arguments.domain, safe="")
            result = self._backend.execute(
                arguments.source,
                [
                    "curl", "--silent", "--show-error", "--max-time", "30",
                    "--max-redirs", "0", "--max-filesize", str(_RDDS_RESPONSE_LIMIT),
                    "--proto", "=http,https", "--write-out",
                    "\n" + marker + "%{http_code}|%{content_type}", "--url", url,
                ],
            )
            body, separator, metadata = result.stdout.rpartition("\n" + marker)
            status_text, pipe, content_type = metadata.partition("|") if separator else ("", "", "")
            http_status = int(status_text) if status_text.isdigit() else None
            content_type = content_type or None
            transport_successful = result.exit_code == 0 and http_status is not None
            successful = transport_successful and 200 <= http_status < 300
            found = True if successful else False if http_status == 404 else None

        encoded = body.encode("utf-8")
        truncated = len(encoded) > _RDDS_RESPONSE_LIMIT
        if truncated:
            body = encoded[:_RDDS_RESPONSE_LIMIT].decode("utf-8", errors="replace")
        rdap = None
        if arguments.protocol == "rdap" and successful and not truncated:
            try:
                parsed = json.loads(body)
                rdap = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass
        return RddsLookupResult(
            source=arguments.source,
            protocol=arguments.protocol,
            authority=arguments.authority,
            domain=arguments.domain,
            endpoint=endpoint,
            transport_successful=transport_successful,
            successful=successful,
            found=found,
            http_status=http_status,
            content_type=content_type,
            body=body,
            rdap=rdap,
            truncated=truncated,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def _rdds_endpoint(self, authority: RddsAuthority, protocol: RddsProtocol) -> str:
        """Resolve one RDDS endpoint exclusively from emulator-owned labels."""
        endpoint_label = _RDDS_WHOIS_LABEL if protocol == "whois" else _RDDS_RDAP_LABEL
        try:
            containers = docker.from_env().containers.list(
                filters={"label": _RDDS_AUTHORITY_LABEL}
            )
        except DockerException as error:
            raise RegistrarMetadataError("Docker RDDS metadata lookup failed") from error
        endpoints = {
            labels[endpoint_label]
            for container in containers
            for labels in [container.attrs.get("Config", {}).get("Labels", {}) or {}]
            if labels.get(_RDDS_AUTHORITY_LABEL) == authority and labels.get(endpoint_label)
        }
        if not endpoints:
            raise RegistrarMetadataError(
                f"No exposed {authority} {protocol.upper()} endpoint is available"
            )
        if len(endpoints) != 1:
            raise RegistrarMetadataError(
                f"Conflicting exposed {authority} {protocol.upper()} endpoints"
            )
        endpoint = endpoints.pop()
        if not isinstance(endpoint, str):
            raise RegistrarMetadataError("Exposed RDDS endpoint is invalid")
        if protocol == "whois":
            if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", endpoint):
                raise RegistrarMetadataError("Exposed WHOIS endpoint is invalid")
            return endpoint.lower()
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise RegistrarMetadataError("Exposed RDAP endpoint must be an HTTP(S) base URL")
        return endpoint.rstrip("/")

    def _source_owned_dns(self, service_id: str) -> DNSServiceLocation:
        """Resolve a paired DNS service exclusively from emulator-owned labels."""
        try:
            containers = docker.from_env().containers.list(filters={"label": _DNS_SERVICE_LABEL})
        except DockerException as error:
            raise RegistrarMetadataError("Docker DNS metadata lookup failed") from error
        matches: list[dict[str, str]] = []
        for container in containers:
            labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
            if labels.get(_DNS_SERVICE_LABEL) == service_id:
                matches.append(labels)
        roles = {labels.get(_DNS_ROLE_LABEL) for labels in matches}
        if roles != {"primary", "secondary"} or len(matches) != 2:
            raise RegistrarMetadataError(
                "source-owned DNS service must expose one Primary and one Secondary"
            )
        first = matches[0]
        fields = [_DNS_PRIMARY_LABEL, _DNS_SECONDARY_LABEL, _DNS_CREDENTIAL_LABEL]
        if any(not first.get(field) for field in fields):
            raise RegistrarMetadataError("source-owned DNS metadata is incomplete")
        if any(
            any(labels.get(field) != first.get(field) for field in fields) for labels in matches
        ):
            raise RegistrarMetadataError("source-owned DNS metadata conflicts between nodes")
        return DNSServiceLocation(
            service_id=service_id,
            primary=first[_DNS_PRIMARY_LABEL],
            secondary=first[_DNS_SECONDARY_LABEL],
            credential_ref=first[_DNS_CREDENTIAL_LABEL],
        )

    def authoritative_find(self, source: str) -> DNSAuthoritativeFindResult:
        """Discover authoritative DNS services explicitly assigned to a source."""
        from seedemu_tool_service.tools.dns.domain_registration.models import (
            DNSAuthoritativeFindArguments,
        )

        arguments = DNSAuthoritativeFindArguments(source=source)
        try:
            container = docker.from_env().containers.get(arguments.source)
        except DockerException as error:
            raise RegistrarMetadataError("Docker source metadata lookup failed") from error
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        raw_service_ids = labels.get(_DNS_SOURCE_SERVICES_LABEL)
        if raw_service_ids is None:
            return DNSAuthoritativeFindResult(source=arguments.source)
        service_ids = raw_service_ids.split(",")
        if (
            any(not item.strip() or any(character.isspace() for character in item)
                for item in service_ids)
            or len(service_ids) != len(set(service_ids))
        ):
            raise RegistrarMetadataError("source-owned DNS directory is invalid")
        return DNSAuthoritativeFindResult(
            source=arguments.source,
            services=[self._source_owned_dns(service_id) for service_id in sorted(service_ids)],
        )

    def configure(
        self,
        source: str,
        dns_service_id: str,
        zone: str,
        changes: list[DNSRecordChange] | list[dict] | None = None,
    ) -> DNSConfigureResult:
        """Provision and update a paired source-owned authoritative DNS service."""
        from seedemu_tool_service.tools.dns.domain_registration.models import DNSConfigureArguments

        arguments = DNSConfigureArguments(
            source=source, dns_service_id=dns_service_id, zone=zone, changes=changes or []
        )
        location = self._source_owned_dns(arguments.dns_service_id)
        credential_dir = "/opt/seedemu/dns/" + arguments.dns_service_id
        provision = base64.b64encode(
            json.dumps(
                {"operation": "provision", "zone": arguments.zone}, separators=(",", ":")
            ).encode()
        ).decode()
        apply_request = base64.b64encode(
            json.dumps(
                {
                    "operation": "apply",
                    "zone": arguments.zone,
                    "changes": [change.model_dump() for change in arguments.changes],
                },
                separators=(",", ":"),
            ).encode()
        ).decode()
        ssh = (
            f"ssh -i {quote(credential_dir + '/control.key')} "
            f"-o BatchMode=yes -o IdentitiesOnly=yes "
            f"-o UserKnownHostsFile={quote(credential_dir + '/known_hosts')} "
            "-o StrictHostKeyChecking=yes -o ConnectTimeout=10"
        )
        lines = [
            "set -eu",
            f"test -f {quote(credential_dir + '/control.key')}",
            f"test -f {quote(credential_dir + '/known_hosts')}",
            f"{ssh} root@{quote(location.secondary)} {quote(provision)}",
            f"{ssh} root@{quote(location.primary)} {quote(provision)}",
        ]
        if arguments.changes:
            lines.append(f"{ssh} root@{quote(location.primary)} {quote(apply_request)}")
        primary_query = f"@{quote(location.primary)} {quote(arguments.zone)}"
        secondary_query = f"@{quote(location.secondary)} {quote(arguments.zone)}"
        lines += [
            "primary_soa=''",
            "secondary_soa=''",
            "for attempt in 1 2 3 4 5 6 7 8 9 10; do",
            f"  primary_soa=$(dig +short {primary_query} SOA | head -n1)",
            f"  secondary_soa=$(dig +short {secondary_query} SOA | head -n1)",
            '  [ -n "$primary_soa" ] && [ "$primary_soa" = "$secondary_soa" ] && break',
            "  sleep 1",
            "done",
            '[ -n "$primary_soa" ] && [ "$primary_soa" = "$secondary_soa" ]',
            "printf '__SEED_DNS_PRIMARY_SOA__%s\\n' \"$primary_soa\"",
            "printf '__SEED_DNS_SECONDARY_SOA__%s\\n' \"$secondary_soa\"",
            "printf '__SEED_DNS_PRIMARY_NS__%s\\n' "
            f'"$(dig +short {primary_query} NS | sort | paste -sd, -)"',
            "printf '__SEED_DNS_SECONDARY_NS__%s\\n' "
            f'"$(dig +short {secondary_query} NS | sort | paste -sd, -)"',
            f"dig {primary_query} SOA | grep -q 'flags:.* aa[; ]'",
            "printf '__SEED_DNS_PRIMARY_AA__1\\n'",
            f"dig {secondary_query} SOA | grep -q 'flags:.* aa[; ]'",
            "printf '__SEED_DNS_SECONDARY_AA__1\\n'",
        ]
        command = ["sh", "-c", "\n".join(lines)]
        result = self._backend.execute(source, command)
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if line.startswith("__SEED_DNS_"):
                key, _, value = line.removeprefix("__SEED_DNS_").partition("__")
                values[key.lower()] = value
        return DNSConfigureResult(
            source=source,
            dns_service_id=arguments.dns_service_id,
            zone=arguments.zone,
            primary=location.primary,
            secondary=location.secondary,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
            primary_soa=values.get("primary_soa") or None,
            secondary_soa=values.get("secondary_soa") or None,
            primary_ns=values.get("primary_ns", "").split(",") if values.get("primary_ns") else [],
            secondary_ns=values.get("secondary_ns", "").split(",")
            if values.get("secondary_ns")
            else [],
            primary_authoritative=values.get("primary_aa") == "1",
            secondary_authoritative=values.get("secondary_aa") == "1",
        )
