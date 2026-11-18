"""Standalone TLS probe, using the selected node's clock and trust material."""

import hashlib
import socket
import ssl


def connect(args, client_identity=False, http=False):
    result = {"tls_verified": False, "http_status": None, "error": None}
    try:
        context = ssl.create_default_context(cafile=args["ca_file_path"])
        if client_identity:
            # Empty password rejects encrypted keys without an interactive prompt.
            context.load_cert_chain(
                args["client_certificate_path"], args["client_private_key_path"], password=""
            )
        with socket.create_connection(
            (args["target"], args["port"]), timeout=args["timeout_seconds"]
        ) as connection:
            with context.wrap_socket(connection, server_hostname=args["expected_hostname"]) as tls:
                certificate = tls.getpeercert()
                result.update(
                    {
                        "tls_verified": True,
                        "protocol": tls.version(),
                        "cipher": tls.cipher()[0],
                        "not_after": certificate.get("notAfter"),
                        "fingerprint_sha256": hashlib.sha256(
                            tls.getpeercert(binary_form=True)
                        ).hexdigest(),
                    }
                )
                if http:
                    tls.sendall(
                        (
                            "HEAD / HTTP/1.1\r\nHost: "
                            + args["expected_hostname"]
                            + "\r\nConnection: close\r\n\r\n"
                        ).encode("ascii")
                    )
                    response = b""
                    while b"\r\n" not in response and len(response) < 4096:
                        block = tls.recv(min(1024, 4096 - len(response)))
                        if not block:
                            break
                        response += block
                    first = response.split(b"\r\n", 1)[0].split()
                    if len(first) >= 2 and first[0].startswith(b"HTTP/") and first[1].isdigit():
                        result["http_status"] = int(first[1])
    except ssl.SSLCertVerificationError as error:
        result.update(
            {"error": "certificate_verification_failed", "verify_code": error.verify_code}
        )
    except ssl.SSLError as error:
        result["error"] = getattr(error, "reason", "tls_error")
    except (OSError, ValueError) as error:
        result["error"] = type(error).__name__
    return result


def probe(args):
    if args["action"] == "deployment":
        result = connect(args)
        result["fingerprint_matches"] = (
            result.get("fingerprint_sha256") == args["expected_fingerprint_sha256"]
            if result["tls_verified"]
            else None
        )
        result["deployment_verified"] = result["tls_verified"] and result["fingerprint_matches"]
        result["revocation_checked"] = False
        return result
    authenticated = connect(args, client_identity=True, http=True)
    anonymous = connect(args, http=True)
    accepted = (
        authenticated["http_status"] is not None and 200 <= authenticated["http_status"] < 400
    )
    anonymous_accepted = (
        anonymous["http_status"] is not None and 200 <= anonymous["http_status"] < 400
    )
    # A generic disconnect/403 does not prove certificate enforcement. A specific
    # TLS certificate-required alert with a working authenticated request does.
    required = anonymous.get("error") in {
        "TLSV13_ALERT_CERTIFICATE_REQUIRED",
        "TLSV1_ALERT_CERTIFICATE_REQUIRED",
    }
    return {
        "with_client_identity": authenticated,
        "without_client_identity": anonymous,
        "authenticated_http_request_accepted": accepted,
        "client_certificate_required": True
        if accepted and required
        else (False if anonymous_accepted else None),
        "application_identity_verified": False,
        "scope": "HTTPS HEAD /; application identity mapping is not checked",
    }
