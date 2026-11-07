#!/usr/bin/env python3

from __future__ import annotations

from seedemu.testing import ComposeRuntimeTest


def main() -> int:
    test = ComposeRuntimeTest(__file__)
    client = test.require_service(150, "client")
    test.require_service(150, "ca")
    dns = test.require_service(150, "dns")
    web = test.require_service(150, "web")

    if client and dns and web:
        test.exec_check(
            "Certbot renewal configuration uses dns-rfc2136",
            web,
            "grep -q '^authenticator = dns-rfc2136$' "
            "/etc/letsencrypt/renewal/wildcard-svc.conf",
        )
        test.exec_check(
            "Wildcard certificate is trusted for api.svc.pki.test",
            client,
            "curl -fsS https://api.svc.pki.test/",
        )
        test.exec_check(
            "ACME challenge TXT record was removed after issuance",
            dns,
            "test -z \"$(dig +short TXT _acme-challenge.svc.pki.test @127.0.0.1)\"",
        )
        test.exec_check(
            "Wildcard certificate covers api.svc.pki.test",
            client,
            "openssl s_client -connect api.svc.pki.test:443 "
            "-servername api.svc.pki.test -verify_hostname api.svc.pki.test "
            "-verify_return_error </dev/null 2>&1 | grep -q 'Verify return code: 0'",
        )

    test.write_summary("pki-dns01-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
