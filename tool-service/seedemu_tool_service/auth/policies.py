"""Explicit role capabilities. New tools are denied until reviewed here."""

DIAGNOSTICS = frozenset(
    {
        "network.inspect_ip_address",
        "network.ping",
        "bgp.summary",
        "dns.lookup",
        "dns.reverse_lookup",
        "dns.compare",
        "dns.trace",
        "pki.explain_verification_failure",
    }
)
PROFILE_READS = frozenset(
    {
        "pki.inspect_environment",
        "pki.list_managed_certificates",
        "pki.inspect_acme_readiness",
        "pki.inspect_renewal_status",
        "pki.inspect_remote_tls_certificate",
        "pki.inspect_remote_tls_chain",
        "pki.inspect_tls_handshake",
        "pki.check_tls_protocols",
        "pki.check_tls_cipher",
        "pki.check_remote_certificate_expiration",
        "pki.verify_tls_deployment",
        "pki.test_mtls_connection",
        "pki.check_certificate_status",
        "pki.inspect_certificate_file",
        "pki.inspect_certificate_names",
        "pki.inspect_certificate_extensions",
        "pki.inspect_certificate_public_key",
        "pki.get_certificate_fingerprint",
        "pki.check_certificate_expiration",
        "pki.compare_certificate_versions",
        "pki.list_expiring_certificates",
        "pki.check_tls_hostname",
        "pki.verify_remote_tls_chain",
        "pki.verify_certificate_chain",
        "pki.verify_certificate_against_ca",
        "pki.verify_certificate_with_intermediates",
        "pki.inspect_private_key",
        "pki.inspect_csr",
        "pki.verify_private_key_matches_certificate",
        "pki.inspect_trust_store",
        "pki.check_ca_installed",
    }
)
PROFILE_WRITES = frozenset(
    {
        "pki.backup_certificate_material",
        "pki.request_acme_certificate",
        "pki.renew_acme_certificate",
        "pki.restore_certificate_material",
        "pki.install_certificate",
        "pki.install_certificate_chain",
        "pki.install_private_key",
        "pki.remove_ca_certificate",
        "pki.update_trust_store",
        "pki.deploy_acme_certificate_to_nginx",
        "pki.revoke_acme_certificate",
    }
)
CA_READS = frozenset({"pki.inspect_ca_service", "pki.inspect_ca_events"})
PROFILE_TOOLS = PROFILE_READS | PROFILE_WRITES | CA_READS
ROLE_TOOLS = {
    "observer": DIAGNOSTICS | PROFILE_READS,
    "member": (
        DIAGNOSTICS | PROFILE_READS | {"dns.update"}
    ),
    "dns_admin": (
        DIAGNOSTICS | PROFILE_READS | {"dns.update"}
    ),
    "pki_operator": (
        DIAGNOSTICS | PROFILE_READS | PROFILE_WRITES
    ),
    "ca_operator": DIAGNOSTICS | PROFILE_READS | CA_READS,
}
