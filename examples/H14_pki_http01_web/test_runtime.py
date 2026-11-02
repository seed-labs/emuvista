#!/usr/bin/env python3

from __future__ import annotations

from seedemu.testing import ComposeRuntimeTest


def main() -> int:
    test = ComposeRuntimeTest(__file__)
    client = test.require_service(150, "client")
    test.require_service(150, "ca")
    test.require_service(150, "dns")
    web = test.require_service(150, "web")

    if web:
        test.exec_check(
            "Certbot renewal configuration uses the Nginx HTTP-01 authenticator",
            web,
            "grep -q '^authenticator = nginx$' /etc/letsencrypt/renewal/*.conf",
        )

    if client and web:
        test.exec_check(
            "CA-issued HTTPS certificate is trusted by the emulated client",
            client,
            "curl -fsS https://web.pki.test/",
        )
        test.exec_check(
            "HTTPS certificate matches web.pki.test",
            client,
            "openssl s_client -connect web.pki.test:443 "
            "-servername web.pki.test -verify_hostname web.pki.test "
            "-verify_return_error </dev/null 2>&1 | grep -q 'Verify return code: 0'",
        )

    test.write_summary("pki-http01-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
