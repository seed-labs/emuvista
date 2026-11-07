"""Certificate installation PKI tool implementations."""

from pathlib import PurePosixPath

from ..execution import RuntimeBackend
from ..installation.models import (
    CertificateMaterialOperationResult,
)


class InstallationTools:
    """Bound-method tools for certificate material installation."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def backup_certificate_material(
        self,
        source: str,
        paths: list[str],
        backup_directory_path: str,
    ) -> CertificateMaterialOperationResult:
        """Back up certificate, private-key, or chain files before replacement."""

        backup_paths = [
            str(PurePosixPath(backup_directory_path) / PurePosixPath(path).name)
            for path in paths
        ]
        path_error = _protected_certificate_path_error(
            self._backend, source, backup_directory_path
        )
        if path_error:
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=2,
                stderr=path_error,
            )
        if any(PurePosixPath(path).name in {"", ".", "/"} for path in paths):
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=2,
                stderr="every backup source must have a filename",
            )
        if len(set(backup_paths)) != len(backup_paths):
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=2,
                stderr="backup sources contain duplicate filenames",
            )

        no_symlink = self._backend.execute(
            source, ["test", "!", "-L", backup_directory_path]
        )
        if no_symlink.exit_code != 0:
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=no_symlink.exit_code,
                stderr="backup directory must not be a symbolic link",
            )
        mkdir = self._backend.execute(
            source, ["mkdir", "-m", "700", "-p", backup_directory_path]
        )
        if mkdir.exit_code != 0:
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=mkdir.exit_code,
                stderr=mkdir.stderr,
            )
        directory_mode = self._backend.execute(
            source, ["stat", "-c", "%a", "--", backup_directory_path]
        )
        if (
            directory_mode.exit_code != 0
            or directory_mode.stdout.strip().lstrip("0") != "700"
        ):
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=directory_mode.exit_code or 2,
                stderr="backup directory must have mode 0700",
            )

        for backup_path in backup_paths:
            symlink_check = self._backend.execute(
                source, ["test", "!", "-L", backup_path]
            )
            if symlink_check.exit_code != 0:
                return CertificateMaterialOperationResult(
                    source=source,
                    successful=False,
                    backup_paths=[],
                    exit_code=symlink_check.exit_code,
                    stderr=symlink_check.stderr
                    or f"backup path must not be a symbolic link: {backup_path}",
                )
            preflight = self._backend.execute(source, ["test", "!", "-e", backup_path])
            if preflight.exit_code != 0:
                return CertificateMaterialOperationResult(
                    source=source,
                    successful=False,
                    backup_paths=[],
                    exit_code=preflight.exit_code,
                    stderr=preflight.stderr or f"backup path already exists: {backup_path}",
                )

        completed_paths: list[str] = []
        exit_code = 0
        stderr = ""
        for path, backup_path in zip(paths, backup_paths, strict=True):
            result = self._backend.execute(
                source, ["install", "-m", "600", "--", path, backup_path]
            )
            if result.exit_code == 0:
                completed_paths.append(backup_path)
            else:
                exit_code = result.exit_code
            if result.stderr:
                stderr = f"{stderr}\n{result.stderr}".strip()
            if exit_code != 0:
                break
        if exit_code != 0:
            self._backend.execute(
                source,
                ["rm", "-f", "--", backup_paths[len(completed_paths)]],
            )
            for backup_path in completed_paths:
                self._backend.execute(source, ["rm", "-f", "--", backup_path])
            completed_paths = []
        return CertificateMaterialOperationResult(
            source=source,
            successful=exit_code == 0,
            backup_paths=completed_paths,
            exit_code=exit_code,
            stderr=stderr,
        )

    def install_certificate(
        self,
        source: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> CertificateMaterialOperationResult:
        """Install a certificate file to an explicit destination."""

        return _copy_material(
            self._backend,
            source,
            source_path,
            destination_path,
            overwrite,
            mode=None,
        )

    def install_private_key(
        self,
        source: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> CertificateMaterialOperationResult:
        """Install a private key with restrictive permissions."""

        return _copy_material(
            self._backend,
            source,
            source_path,
            destination_path,
            overwrite,
            mode="600",
        )

    def install_certificate_chain(
        self,
        source: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> CertificateMaterialOperationResult:
        """Install a certificate chain bundle."""

        return _copy_material(
            self._backend,
            source,
            source_path,
            destination_path,
            overwrite,
            mode=None,
        )

    def restore_certificate_material(
        self,
        source: str,
        backup_path: str,
        restore_path: str,
        overwrite: bool = False,
    ) -> CertificateMaterialOperationResult:
        """Restore backed-up certificate material."""

        return _copy_material(
            self._backend,
            source,
            backup_path,
            restore_path,
            overwrite,
            mode=None,
        )


def _copy_material(
    backend: RuntimeBackend,
    source: str,
    source_path: str,
    destination_path: str,
    overwrite: bool,
    mode: str | None,
) -> CertificateMaterialOperationResult:
    path_error = _protected_certificate_path_error(backend, source, destination_path)
    if path_error:
        return CertificateMaterialOperationResult(
            source=source,
            successful=False,
            exit_code=2,
            stderr=path_error,
        )

    symlink_check = backend.execute(source, ["test", "!", "-L", destination_path])
    if symlink_check.exit_code != 0:
        return CertificateMaterialOperationResult(
            source=source,
            successful=False,
            exit_code=symlink_check.exit_code,
            stderr=symlink_check.stderr or "destination must not be a symbolic link",
        )

    if not overwrite:
        preflight = backend.execute(source, ["test", "!", "-e", destination_path])
        if preflight.exit_code != 0:
            return CertificateMaterialOperationResult(
                source=source,
                successful=False,
                exit_code=preflight.exit_code,
                stderr=preflight.stderr or f"destination path already exists: {destination_path}",
            )

    command = (
        ["install", "-m", mode, "--", source_path, destination_path]
        if mode is not None
        else ["cp", source_path, destination_path]
    )
    result = backend.execute(source, command)
    exit_code = result.exit_code
    stderr = result.stderr
    return CertificateMaterialOperationResult(
        source=source,
        successful=exit_code == 0,
        created_paths=[destination_path] if exit_code == 0 and not overwrite else [],
        modified_paths=[destination_path] if exit_code == 0 and overwrite else [],
        exit_code=exit_code,
        stderr=stderr,
    )


def _protected_certificate_path_error(
    backend: RuntimeBackend, source: str, path: str
) -> str | None:
    """Keep generic helpers out of Certbot state and system CA trust roots."""

    resolved = backend.execute(source, ["realpath", "-m", "--", path])
    if resolved.exit_code != 0 or not resolved.stdout.strip():
        return resolved.stderr or "destination path could not be resolved safely"
    canonical = PurePosixPath(resolved.stdout.strip())
    protected_roots = (
        PurePosixPath("/etc/letsencrypt"),
        PurePosixPath("/usr/local/share/ca-certificates"),
        PurePosixPath("/etc/ssl/certs"),
        PurePosixPath("/etc/ssl/cert.pem"),
        PurePosixPath("/etc/ssl/ca-bundle.pem"),
        PurePosixPath("/etc/ssl/ca-bundle.crt"),
        PurePosixPath("/etc/ca-certificates"),
        PurePosixPath("/etc/pki/ca-trust"),
        PurePosixPath("/etc/pki/tls/certs"),
        PurePosixPath("/etc/pki/tls/cert.pem"),
        PurePosixPath("/etc/pki/tls/ca-bundle.pem"),
        PurePosixPath("/usr/share/ca-certificates"),
    )
    for protected_root in protected_roots:
        if canonical == protected_root or canonical.is_relative_to(protected_root):
            return (
                "Certbot-managed files and system CA roots may only be changed through "
                "their dedicated SEEDEmu CAService workflows"
            )
    return None
