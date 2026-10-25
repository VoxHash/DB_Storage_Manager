"""
Proton Drive backup adapter (rclone protondrive remote).

Uploads encrypted (DSMENC1) backup payloads to Proton Drive via the rclone
``protondrive`` backend. Credentials come from adapter config, SecureStore
settings, or environment — never from committed files.

Official Proton Drive third-party SDKs do not yet expose standalone auth for
production apps; rclone's Proton Drive backend is the supported automation
path until Proton's SDK ships third-party authentication.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..native import (
    ENCRYPTION_SCHEME,
    encrypt_file,
    gzip_compress_file,
    sha256_file,
    zstd_compress_file,
)


class ProtonDriveNotConfiguredError(RuntimeError):
    """Raised when rclone or Proton Drive credentials are missing."""


@dataclass
class RcloneResult:
    """Captured rclone subprocess result."""

    returncode: int
    stdout: str
    stderr: str
    args: Sequence[str]


class RcloneRunner(Protocol):
    """Injectable boundary for rclone invocations (tests use a double)."""

    def run(
        self,
        args: Sequence[str],
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> RcloneResult:
        ...


class SubprocessRcloneRunner:
    """Real rclone binary runner."""

    def __init__(self, binary: str = "rclone"):
        self.binary = binary

    def run(
        self,
        args: Sequence[str],
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> RcloneResult:
        cmd = [self.binary, *args]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
        return RcloneResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            args=cmd,
        )


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def resolve_proton_drive_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge adapter config, SecureStore settings, and environment.

    Precedence (highest first): explicit ``config`` → SecureStore
    ``proton_drive`` settings → environment variables.
    """
    stored = {}
    if settings and isinstance(settings.get("proton_drive"), dict):
        stored = dict(settings["proton_drive"])
    elif settings is None:
        try:
            from ..security.store import SecureStore

            stored = dict(SecureStore().get_settings().get("proton_drive") or {})
        except Exception:
            stored = {}

    merged: Dict[str, Any] = {
        "remote": "protondrive",
        "path": "db-storage-manager-backups",
        "rclone_bin": "rclone",
        "prefer_encryption": True,
        "timeout_seconds": 300,
    }
    merged.update({k: v for k, v in stored.items() if v is not None})
    if config:
        merged.update({k: v for k, v in config.items() if v is not None})

    env_remote = _env_first("DSM_PROTONDRIVE_REMOTE")
    if env_remote and "remote" not in (config or {}):
        merged["remote"] = env_remote
    env_path = _env_first("DSM_PROTONDRIVE_PATH")
    if env_path and "path" not in (config or {}):
        merged["path"] = env_path.strip().strip("/")
    env_bin = _env_first("DSM_PROTONDRIVE_RCLONE", "RCLONE_BIN")
    if env_bin and "rclone_bin" not in (config or {}):
        merged["rclone_bin"] = env_bin

    username = merged.get("username") or _env_first(
        "DSM_PROTONDRIVE_USERNAME", "RCLONE_PROTONDRIVE_USERNAME"
    )
    password = merged.get("password") or _env_first(
        "DSM_PROTONDRIVE_PASSWORD", "RCLONE_PROTONDRIVE_PASSWORD"
    )
    otp_secret = merged.get("otp_secret_key") or _env_first(
        "DSM_PROTONDRIVE_OTP_SECRET",
        "DSM_PROTONDRIVE_OTP_SECRET_KEY",
        "RCLONE_PROTONDRIVE_OTP_SECRET_KEY",
    )
    mailbox_password = merged.get("mailbox_password") or _env_first(
        "DSM_PROTONDRIVE_MAILBOX_PASSWORD", "RCLONE_PROTONDRIVE_MAILBOX_PASSWORD"
    )
    two_fa = merged.get("two_fa") or merged.get("2fa") or _env_first(
        "DSM_PROTONDRIVE_2FA", "RCLONE_PROTONDRIVE_2FA"
    )

    if username:
        merged["username"] = username
    if password:
        merged["password"] = password
    if otp_secret:
        merged["otp_secret_key"] = otp_secret
    if mailbox_password:
        merged["mailbox_password"] = mailbox_password
    if two_fa:
        merged["2fa"] = two_fa

    prefer = merged.get("prefer_encryption")
    if isinstance(prefer, str):
        merged["prefer_encryption"] = prefer.strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    else:
        merged["prefer_encryption"] = bool(prefer)

    return merged


def configuration_status(
    config: Optional[Dict[str, Any]] = None,
    *,
    runner: Optional[RcloneRunner] = None,
) -> Dict[str, Any]:
    """Describe whether Proton Drive backups can run on this machine."""
    cfg = resolve_proton_drive_config(config)
    binary = str(cfg.get("rclone_bin") or "rclone")
    binary_path = shutil.which(binary) or (
        binary if Path(binary).is_file() else None
    )
    has_creds = bool(cfg.get("username") and cfg.get("password"))
    remotes: List[str] = []
    remote_listed = False
    rclone_error: Optional[str] = None

    if binary_path:
        client = runner or SubprocessRcloneRunner(binary_path)
        try:
            result = client.run(["listremotes"], timeout=30)
            if result.returncode == 0:
                remotes = [
                    line.strip().rstrip(":")
                    for line in result.stdout.splitlines()
                    if line.strip()
                ]
                remote_listed = cfg["remote"] in remotes
            else:
                rclone_error = (result.stderr or result.stdout or "").strip() or None
        except Exception as exc:  # noqa: BLE001 — surface status, not crash
            rclone_error = str(exc)

    configured = bool(binary_path) and (has_creds or remote_listed)
    messages: List[str] = []
    if not binary_path:
        messages.append(
            "rclone is not installed or not on PATH. Install rclone "
            "(https://rclone.org/install/) with the protondrive backend."
        )
    elif not has_creds and not remote_listed:
        messages.append(
            "Proton Drive is not configured. Set DSM_PROTONDRIVE_USERNAME / "
            "DSM_PROTONDRIVE_PASSWORD (see .env.protondrive.local.example), "
            f"or run `rclone config` and create a '{cfg['remote']}' protondrive remote."
        )
    if rclone_error and not configured:
        messages.append(f"rclone probe error: {rclone_error}")

    return {
        "configured": configured,
        "rclone_bin": binary,
        "rclone_found": bool(binary_path),
        "rclone_path": binary_path,
        "remote": cfg["remote"],
        "remote_path": cfg["path"],
        "has_credentials": has_creds,
        "remote_in_rclone_config": remote_listed,
        "remotes": remotes,
        "prefer_encryption": bool(cfg.get("prefer_encryption", True)),
        "message": " ".join(messages) if messages else "Proton Drive ready.",
        "error": None if configured else (messages[0] if messages else "Not configured"),
    }


class ProtonDriveBackupAdapter(BackupAdapter):
    """Backup adapter that stores payloads on Proton Drive via rclone."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        runner: Optional[RcloneRunner] = None,
        settings: Optional[Dict[str, Any]] = None,
    ):
        self.config = resolve_proton_drive_config(config, settings=settings)
        self.remote = str(self.config["remote"])
        self.remote_folder = str(self.config.get("path") or "").strip().strip("/")
        self.prefer_encryption = bool(self.config.get("prefer_encryption", True))
        self.timeout = float(self.config.get("timeout_seconds") or 300)
        binary = str(self.config.get("rclone_bin") or "rclone")
        self._runner: RcloneRunner = runner or SubprocessRcloneRunner(binary)
        self._binary = binary

    def _require_configured(self) -> None:
        status = configuration_status(self.config, runner=self._runner)
        if not status["configured"]:
            raise ProtonDriveNotConfiguredError(
                status.get("error")
                or status.get("message")
                or "Proton Drive is not configured"
            )

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        # Identify as third-party rclone consumer when creating an ephemeral remote.
        env.setdefault(
            "RCLONE_PROTONDRIVE_APP_VERSION",
            "external-drive-db-storage-manager@1.0.5",
        )
        username = self.config.get("username")
        password = self.config.get("password")
        if username:
            env["RCLONE_PROTONDRIVE_USERNAME"] = str(username)
        if password:
            env["RCLONE_PROTONDRIVE_PASSWORD"] = str(password)
        if self.config.get("otp_secret_key"):
            env["RCLONE_PROTONDRIVE_OTP_SECRET_KEY"] = str(
                self.config["otp_secret_key"]
            )
        if self.config.get("mailbox_password"):
            env["RCLONE_PROTONDRIVE_MAILBOX_PASSWORD"] = str(
                self.config["mailbox_password"]
            )
        if self.config.get("2fa"):
            env["RCLONE_PROTONDRIVE_2FA"] = str(self.config["2fa"])
        return env

    def _remote_target(self, filename: str = "") -> str:
        base = f"{self.remote}:"
        if self.remote_folder:
            base = f"{self.remote}:{self.remote_folder}"
        if filename:
            return f"{base}/{filename}" if self.remote_folder else f"{base}{filename}"
        return base if self.remote_folder else f"{self.remote}:"

    def _run(self, args: Sequence[str]) -> RcloneResult:
        result = self._runner.run(
            list(args), env=self._build_env(), timeout=self.timeout
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"rclone {' '.join(args[:2])} failed (exit {result.returncode})"
                + (f": {detail}" if detail else "")
            )
        return result

    def _prepare_payload(self, options: BackupOptions) -> tuple[Path, Dict[str, Any], List[Path]]:
        """Compress/encrypt source dump; return (payload, metadata, temps)."""
        source_path = Path(options.backupPath)
        if not source_path.exists():
            raise FileNotFoundError(
                f"Backup source file not found: {options.backupPath}"
            )

        temps: List[Path] = []
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = f"{options.connectionName}_{timestamp}.backup"
        final_filename = original_filename
        work_dir = Path(tempfile.mkdtemp(prefix="dsm-proton-"))
        temps.append(work_dir)

        compression = (options.compression or "none").lower()
        current = source_path

        if compression == "gzip":
            out = work_dir / f"{original_filename}.gz"
            gzip_compress_file(source_path, out)
            current = out
            final_filename = f"{original_filename}.gz"
        elif compression == "zstd":
            out = work_dir / f"{original_filename}.zst"
            zstd_compress_file(source_path, out)
            current = out
            final_filename = f"{original_filename}.zst"
        else:
            compression = "none"
            out = work_dir / original_filename
            shutil.copy2(source_path, out)
            current = out

        encrypt = bool(options.encryption)
        if self.prefer_encryption and not encrypt:
            if options.encryptionKey:
                encrypt = True
            else:
                raise ValueError(
                    "Proton Drive backups prefer DSMENC1 encryption before upload. "
                    "Pass encryption=True with encryptionKey, or set "
                    "proton_drive.prefer_encryption=false in SecureStore settings "
                    "(not recommended for opsec)."
                )

        encrypted = False
        if encrypt:
            if not options.encryptionKey:
                raise ValueError(
                    "encryption=True requires encryptionKey (passphrase) for Proton Drive upload"
                )
            enc_path = work_dir / f"{final_filename}.enc"
            encrypt_file(current, enc_path, options.encryptionKey)
            current = enc_path
            final_filename = f"{final_filename}.enc"
            encrypted = True

        checksum = sha256_file(current)
        created_at = datetime.now()
        metadata: Dict[str, Any] = {
            "id": backup_id,
            "name": final_filename,
            "compression": compression,
            "encryption": encrypted,
            "encryptionScheme": ENCRYPTION_SCHEME if encrypted else None,
            "databaseType": options.databaseType,
            "connectionId": options.connectionId,
            "connectionName": options.connectionName,
            "sha256": checksum,
            "createdAt": created_at.isoformat(),
            "destination": "protondrive",
            "remote": self.remote,
            "remotePath": self.remote_folder,
        }
        return current, metadata, temps

    def _cleanup_temps(self, temps: List[Path]) -> None:
        for path in reversed(temps):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Encrypt (preferred) then upload backup + meta sidecar to Proton Drive."""
        self._require_configured()
        payload, metadata, temps = self._prepare_payload(options)
        try:
            filename = str(metadata["name"])
            meta_name = f"{filename}.meta.json"
            meta_local = payload.parent / meta_name
            with open(meta_local, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2, default=str)

            # Ensure remote folder exists, then upload payload + sidecar
            if self.remote_folder:
                self._run(["mkdir", self._remote_target()])
            self._run(["copyto", str(payload), self._remote_target(filename)])
            self._run(["copyto", str(meta_local), self._remote_target(meta_name)])

            size = payload.stat().st_size
            info_meta = {
                "key": filename,
                "remote": self.remote,
                "remotePath": self.remote_folder,
                "metaKey": meta_name,
                "compression": metadata["compression"],
                "encryption": metadata["encryption"],
                "databaseType": options.databaseType,
                "connectionId": options.connectionId,
                "sha256": metadata["sha256"],
                "destination": "protondrive",
            }
            if metadata["encryption"]:
                info_meta["encryptionScheme"] = ENCRYPTION_SCHEME

            return BackupInfo(
                id=str(metadata["id"]),
                name=filename,
                path=self._remote_target(filename),
                size=size,
                createdAt=datetime.fromisoformat(metadata["createdAt"]),
                status="completed",
                metadata=info_meta,
            )
        finally:
            self._cleanup_temps(temps)

    def _download_to_temp(self, backup_info: BackupInfo) -> Path:
        """Download a Proton Drive backup object to a local temp file."""
        self._require_configured()
        key = (backup_info.metadata or {}).get("key") or Path(backup_info.path).name
        remote = self._remote_target(str(key))
        fd, temp_name = tempfile.mkstemp(suffix=".backup")
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            self._run(["copyto", remote, str(temp_path)])
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    async def restore_backup(
        self,
        backup_info: BackupInfo,
        encryption_key: Optional[str] = None,
    ) -> str:
        """Download a Proton Drive backup to a local temp file."""
        return str(self._download_to_temp(backup_info))

    def _load_remote_meta(self, filename: str) -> Dict[str, Any]:
        meta_key = f"{filename}.meta.json"
        try:
            result = self._run(["cat", self._remote_target(meta_key)])
            data = json.loads(result.stdout)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def list_backups(self) -> list[BackupInfo]:
        """List backup objects under the configured Proton Drive folder."""
        self._require_configured()
        result = self._run(
            ["lsjson", self._remote_target(), "--files-only", "--no-mimetype"]
        )
        try:
            entries = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid rclone lsjson output: {exc}") from exc

        backups: List[BackupInfo] = []
        for entry in entries:
            name = str(entry.get("Name") or entry.get("Path") or "")
            if not name or name.endswith(".meta.json"):
                continue
            if ".backup" not in name:
                continue
            stored = self._load_remote_meta(name)
            backup_id = str(stored.get("id") or uuid.uuid4())
            size = int(entry.get("Size") or stored.get("size") or 0)
            created_at = datetime.now()
            mod = entry.get("ModTime") or stored.get("createdAt")
            if isinstance(mod, str):
                try:
                    created_at = datetime.fromisoformat(mod.replace("Z", "+00:00"))
                except ValueError:
                    pass

            metadata: Dict[str, Any] = {
                "key": name,
                "remote": self.remote,
                "remotePath": self.remote_folder,
                "metaKey": f"{name}.meta.json",
                "destination": "protondrive",
                "compression": stored.get("compression", "none"),
                "encryption": bool(stored.get("encryption", name.endswith(".enc"))),
            }
            for key in (
                "databaseType",
                "connectionId",
                "connectionName",
                "sha256",
                "encryptionScheme",
            ):
                if key in stored and stored[key] is not None:
                    metadata[key] = stored[key]

            backups.append(
                BackupInfo(
                    id=backup_id,
                    name=name,
                    path=self._remote_target(name),
                    size=size,
                    createdAt=created_at,
                    status="completed",
                    metadata=metadata,
                )
            )
        return backups

    async def delete_backup(self, backup_id: str) -> None:
        """Delete a backup (and sidecar) from Proton Drive."""
        self._require_configured()
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)
        if not backup:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        key = (backup.metadata or {}).get("key") or Path(backup.path).name
        self._run(["deletefile", self._remote_target(str(key))])
        meta_key = (backup.metadata or {}).get("metaKey") or f"{key}.meta.json"
        try:
            self._run(["deletefile", self._remote_target(str(meta_key))])
        except RuntimeError:
            pass

    async def validate_options(self, options: BackupOptions) -> bool:
        """Return True when Proton Drive appears configured and reachable."""
        try:
            self._require_configured()
            self._run(["lsd", f"{self.remote}:"])
            return True
        except Exception:
            return False

    def verify_remote_checksum(self, backup_info: BackupInfo) -> Dict[str, Any]:
        """Download payload and compare against stored SHA-256 metadata."""
        expected = (backup_info.metadata or {}).get("sha256")
        local_path: Optional[Path] = None
        try:
            local_path = self._download_to_temp(backup_info)
            actual = sha256_file(local_path)
            size = local_path.stat().st_size
            if not expected:
                return {
                    "ok": False,
                    "status": "missing_checksum",
                    "path": backup_info.path,
                    "expected": None,
                    "actual": actual,
                    "size": size,
                    "error": "No stored SHA-256 checksum in backup metadata",
                }
            matched = expected == actual
            return {
                "ok": matched,
                "status": "pass" if matched else "fail",
                "path": backup_info.path,
                "expected": expected,
                "actual": actual,
                "size": size,
                "error": None if matched else "SHA-256 mismatch",
            }
        except ProtonDriveNotConfiguredError as exc:
            return {
                "ok": False,
                "status": "not_configured",
                "path": backup_info.path,
                "expected": expected,
                "actual": None,
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "status": "fail",
                "path": backup_info.path,
                "expected": expected,
                "actual": None,
                "error": str(exc),
            }
        finally:
            if local_path is not None:
                local_path.unlink(missing_ok=True)
