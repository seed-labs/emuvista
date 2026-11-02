"""OpenSSL output parsing helpers for PKI tools."""

from seedemu_tool_service.tools.pki.shared.models import CertificateFields


def parse_certificate_fields(output: str) -> CertificateFields:
    """Extract common fields from OpenSSL text output when present."""

    return CertificateFields(
        subject=parse_prefixed_value(output, "subject"),
        issuer=parse_prefixed_value(output, "issuer"),
        serial=parse_prefixed_value(output, "serial"),
        not_before=parse_prefixed_value(output, "notBefore"),
        not_after=parse_prefixed_value(output, "notAfter"),
        fingerprint_sha256=parse_prefixed_value(output, "sha256 Fingerprint"),
    )


def parse_prefixed_value(output: str, key: str) -> str | None:
    """Return the value from an OpenSSL key=value or key: value line."""

    prefixes = (f"{key}=", f"{key}:")
    for line in output.splitlines():
        stripped = line.strip()
        for prefix in prefixes:
            if stripped.lower().startswith(prefix.lower()):
                return stripped[len(prefix) :].strip()
    return None


def extract_pem_certificates(output: str) -> list[str]:
    """Extract complete PEM certificate blocks from command output."""

    certificates: list[str] = []
    current: list[str] = []
    in_certificate = False

    for line in output.splitlines():
        if line == "-----BEGIN CERTIFICATE-----":
            current = [line]
            in_certificate = True
            continue
        if not in_certificate:
            continue
        current.append(line)
        if line == "-----END CERTIFICATE-----":
            certificates.append("\n".join(current))
            current = []
            in_certificate = False

    return certificates


def parse_subject_common_name(subject: str | None) -> str | None:
    """Extract a simple CN component from an OpenSSL subject string."""

    if subject is None:
        return None

    for separator in (",", "/"):
        for part in subject.split(separator):
            stripped = part.strip()
            if stripped.startswith("CN="):
                return stripped[3:].strip()
            if " = " in stripped:
                key, value = stripped.split(" = ", 1)
                if key.strip() == "CN":
                    return value.strip()
    return None


def parse_subject_alt_names(output: str) -> list[str]:
    """Extract SAN entries from OpenSSL extension output."""

    names: list[str] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if "Subject Alternative Name" not in line:
            continue

        for san_line in lines[index + 1 :]:
            stripped = san_line.strip()
            if not stripped:
                break
            if stripped.startswith("X509v3 ") or stripped.startswith("Signature Algorithm"):
                break
            names.extend(part.strip() for part in stripped.split(",") if part.strip())
        break
    return names


def parse_extension_value(output: str, extension_name: str) -> str | None:
    """Extract the value lines for a named X.509 extension."""

    lines = output.splitlines()
    for index, line in enumerate(lines):
        if extension_name not in line:
            continue

        values: list[str] = []
        for extension_line in lines[index + 1 :]:
            stripped = extension_line.strip()
            if not stripped:
                break
            if stripped.startswith("X509v3 ") or stripped.startswith("Signature Algorithm"):
                break
            values.append(stripped)
        return "; ".join(values) if values else None
    return None


def parse_public_key_algorithm(output: str) -> str | None:
    """Extract public-key algorithm from OpenSSL text output."""

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Public Key Algorithm:"):
            return stripped.split(":", 1)[1].strip()
        if "Public-Key:" in stripped:
            algorithm = stripped.split("Public-Key:", 1)[0].strip()
            if algorithm:
                return algorithm
    if "ASN1 OID:" in output or "EC PARAMETERS:" in output:
        return "EC"
    if "Modulus:" in output:
        return "RSA"
    return None


def parse_public_key_bits(output: str) -> int | None:
    """Extract public-key size from OpenSSL text output."""

    marker = "Public-Key: ("
    for line in output.splitlines():
        stripped = line.strip()
        if marker not in stripped:
            continue
        after_marker = stripped.split(marker, 1)[1]
        bits_text = after_marker.split(" bit", 1)[0]
        try:
            return int(bits_text)
        except ValueError:
            return None
    return None


def parse_openssl_error_category(output: str, stderr: str) -> str:
    """Map common OpenSSL failures to stable agent-facing categories."""

    text = f"{output}\n{stderr}".lower()
    if "no such file" in text or "not found" in text:
        return "file_not_found"
    if "unable to load certificate" in text or "expecting: trusted certificate" in text:
        return "invalid_certificate_file"
    if "certificate has expired" in text or "expired" in text:
        return "certificate_expired"
    if "self-signed certificate" in text:
        return "self_signed_certificate"
    if "unable to get local issuer certificate" in text:
        return "incomplete_chain"
    if "unable to verify the first certificate" in text or "unknown ca" in text:
        return "unknown_issuer"
    if "hostname mismatch" in text or "verify error:num=62" in text:
        return "hostname_mismatch"
    if "permission denied" in text:
        return "permission_denied"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "key values mismatch" in text or "key mismatch" in text:
        return "private_key_mismatch"
    return "unknown_error"
