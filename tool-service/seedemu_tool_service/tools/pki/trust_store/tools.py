"""Trust-store PKI tool implementations."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.trust_store.models import (
    CAInstalledResult,
    TrustStoreInspectionResult,
    TrustStoreMutationResult,
)


class TrustStoreTools:
    """Bound-method tools for trust-store inspection and mutation."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def inspect_trust_store(self, source: str, trust_store_path: str) -> TrustStoreInspectionResult:
        """List trust-store material at a constrained path."""

        result = self._backend.execute(source, ["ls", "-1", trust_store_path])
        entries = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return TrustStoreInspectionResult(
            source=source,
            trust_store_path=trust_store_path,
            successful=result.exit_code == 0,
            entries=entries,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def check_ca_installed(
        self,
        source: str,
        trust_store_path: str,
        ca_certificate_path: str,
    ) -> CAInstalledResult:
        """Check whether a CA certificate appears trusted by a bundle or directory."""

        result = self._backend.execute(
            source,
            ["openssl", "verify", "-CAfile", trust_store_path, ca_certificate_path],
        )
        return CAInstalledResult(
            source=source,
            ca_certificate_path=ca_certificate_path,
            installed=result.exit_code == 0,
            output=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def remove_ca_certificate(
        self,
        source: str,
        ca_certificate_path: str,
        expected_fingerprint_sha256: str,
    ) -> TrustStoreMutationResult:
        """Remove one pinned CA certificate from the SEEDEmu trust-store location."""

        inspected = self._backend.execute(
            source,
            ["openssl", "x509", "-in", ca_certificate_path, "-noout", "-fingerprint", "-sha256"],
        )
        if inspected.exit_code != 0:
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=inspected.stdout,
                exit_code=inspected.exit_code,
                stderr=inspected.stderr or "CA certificate could not be inspected",
            )
        regular_file = self._backend.execute(
            source, ["test", "-f", ca_certificate_path, "-a", "!", "-L", ca_certificate_path]
        )
        if regular_file.exit_code != 0:
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=regular_file.stdout,
                exit_code=regular_file.exit_code,
                stderr="Only a regular CA certificate file may be removed",
            )
        observed = inspected.stdout.partition("=")[2].strip().replace(":", "").lower()
        if observed != expected_fingerprint_sha256:
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=inspected.stdout,
                exit_code=2,
                stderr="CA certificate fingerprint does not match the expected value",
            )

        backup_path = ca_certificate_path + ".seedemu-pki.bak"
        preflight = self._backend.execute(source, ["test", "!", "-e", backup_path])
        if preflight.exit_code != 0:
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=preflight.stdout,
                exit_code=preflight.exit_code,
                stderr=preflight.stderr or "Removal backup path already exists",
            )
        backed_up = self._backend.execute(
            source, ["cp", "--", ca_certificate_path, backup_path]
        )
        if backed_up.exit_code != 0:
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=backed_up.stdout,
                exit_code=backed_up.exit_code,
                stderr=backed_up.stderr,
            )

        removed = self._backend.execute(source, ["rm", "--", ca_certificate_path])
        if removed.exit_code != 0:
            self._backend.execute(source, ["rm", "-f", "--", backup_path])
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=removed.stdout,
                exit_code=removed.exit_code,
                stderr=removed.stderr,
            )
        updated = self._backend.execute(source, ["update-ca-certificates"])
        if updated.exit_code != 0:
            self._backend.execute(
                source, ["cp", "--", backup_path, ca_certificate_path]
            )
            self._backend.execute(source, ["update-ca-certificates"])
            self._backend.execute(source, ["rm", "-f", "--", backup_path])
            return TrustStoreMutationResult(
                source=source,
                successful=False,
                output=updated.stdout,
                exit_code=updated.exit_code,
                stderr=updated.stderr or "Trust-store update failed; removed certificate was restored",
            )
        self._backend.execute(source, ["rm", "-f", "--", backup_path])
        return TrustStoreMutationResult(
            source=source,
            successful=True,
            removed_paths=[ca_certificate_path],
            output=updated.stdout,
            exit_code=updated.exit_code,
            stderr=updated.stderr,
        )

    def update_trust_store(
        self,
        source: str,
    ) -> TrustStoreMutationResult:
        """Run the fixed Debian/Ubuntu trust-store update command used by SEEDEmu."""

        result = self._backend.execute(source, ["update-ca-certificates"])
        return TrustStoreMutationResult(
            source=source,
            successful=result.exit_code == 0,
            output=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )
