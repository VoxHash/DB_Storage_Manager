"""
Native performance helpers (Rust/PyO3) with pure-Python fallbacks.

Build the extension from the repo root::

    pip install maturin
    cd native/db_storage_native && maturin develop --release

Or::

    pip install -e ".[native]"

When the compiled module is unavailable, callers transparently use Python
implementations so the desktop app keeps working.

Backup-file encryption uses the ``DSMENC1`` format (AES-256-GCM, chunked,
PBKDF2-HMAC-SHA256 key derivation). Native and Python paths are wire-compatible.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_NATIVE = None
_NATIVE_ERROR: Optional[str] = None

try:
    import db_storage_native as _NATIVE  # type: ignore
except Exception as exc:  # pragma: no cover - import path varies by build
    _NATIVE_ERROR = str(exc)
    _NATIVE = None

# On-disk encryption format (must match native/db_storage_native)
ENCRYPTION_FORMAT = "DSMENC1"
ENCRYPTION_SCHEME = "aes-256-gcm-pbkdf2"
_ENC_MAGIC = b"DSMENC1\0"
_ENC_SALT_LEN = 16
_ENC_NONCE_LEN = 12
_ENC_TAG_LEN = 16
_ENC_PBKDF2_ITERS = 200_000
_ENC_CHUNK = 1024 * 1024


def is_available() -> bool:
    """Return True when the Rust extension is importable."""
    return _NATIVE is not None


def backend_info() -> Dict[str, Any]:
    """Describe the active backend for diagnostics / About UI."""
    if _NATIVE is not None:
        try:
            lang, version = _NATIVE.backend_info()
            return {
                "available": True,
                "language": lang,
                "version": version,
                "module": "db_storage_native",
                "encryption_format": ENCRYPTION_FORMAT,
                "encryption_scheme": ENCRYPTION_SCHEME,
            }
        except Exception as exc:  # pragma: no cover
            return {
                "available": False,
                "language": "python",
                "version": None,
                "error": str(exc),
            }
    return {
        "available": False,
        "language": "python",
        "version": None,
        "error": _NATIVE_ERROR,
        "encryption_format": ENCRYPTION_FORMAT,
        "encryption_scheme": ENCRYPTION_SCHEME,
    }


def gzip_compress_file(
    src: str | Path, dst: str | Path, level: int = 6
) -> int:
    """Compress ``src`` to gzip ``dst``. Returns destination size in bytes."""
    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None:
        return int(_NATIVE.gzip_compress_file(src_s, dst_s, level))

    with open(src_s, "rb") as f_in:
        with gzip.open(dst_s, "wb", compresslevel=level) as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
    return Path(dst_s).stat().st_size


def gzip_decompress_file(src: str | Path, dst: str | Path) -> int:
    """Decompress gzip ``src`` to ``dst``. Returns bytes written."""
    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None:
        return int(_NATIVE.gzip_decompress_file(src_s, dst_s))

    written = 0
    with gzip.open(src_s, "rb") as f_in:
        with open(dst_s, "wb") as f_out:
            while True:
                chunk = f_in.read(1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
                written += len(chunk)
    return written


def zstd_compress_file(
    src: str | Path, dst: str | Path, level: int = 3
) -> int:
    """Compress ``src`` to zstd ``dst``. Returns destination size in bytes."""
    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None and hasattr(_NATIVE, "zstd_compress_file"):
        return int(_NATIVE.zstd_compress_file(src_s, dst_s, level))

    try:
        import zstandard as zstd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "zstd compression requires the 'zstandard' package "
            "(pip install zstandard) or the db_storage_native extension"
        ) from exc

    level = max(1, min(int(level), 22))
    cctx = zstd.ZstdCompressor(level=level)
    with open(src_s, "rb") as f_in, open(dst_s, "wb") as f_out:
        cctx.copy_stream(f_in, f_out)
    return Path(dst_s).stat().st_size


def zstd_decompress_file(src: str | Path, dst: str | Path) -> int:
    """Decompress zstd ``src`` to ``dst``. Returns bytes written."""
    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None and hasattr(_NATIVE, "zstd_decompress_file"):
        return int(_NATIVE.zstd_decompress_file(src_s, dst_s))

    try:
        import zstandard as zstd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "zstd decompression requires the 'zstandard' package "
            "(pip install zstandard) or the db_storage_native extension"
        ) from exc

    dctx = zstd.ZstdDecompressor()
    written = 0
    with open(src_s, "rb") as f_in, open(dst_s, "wb") as f_out:
        with dctx.stream_reader(f_in) as reader:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
                written += len(chunk)
    return written


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ENC_PBKDF2_ITERS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_file(src: str | Path, dst: str | Path, passphrase: str) -> int:
    """Encrypt ``src`` to ``dst`` using DSMENC1 (AES-256-GCM + PBKDF2).

    Returns destination size in bytes. Native Rust offload when available;
    otherwise cryptography AESGCM (same on-disk format).
    """
    if not passphrase:
        raise ValueError("encryption passphrase must not be empty")

    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None and hasattr(_NATIVE, "encrypt_file"):
        return int(_NATIVE.encrypt_file(src_s, dst_s, passphrase))

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(_ENC_SALT_LEN)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)

    with open(src_s, "rb") as f_in, open(dst_s, "wb") as f_out:
        f_out.write(_ENC_MAGIC)
        f_out.write(salt)
        while True:
            chunk = f_in.read(_ENC_CHUNK)
            if not chunk:
                break
            nonce = os.urandom(_ENC_NONCE_LEN)
            ciphertext = aesgcm.encrypt(nonce, chunk, None)
            f_out.write(struct.pack(">I", len(chunk)))
            f_out.write(nonce)
            f_out.write(ciphertext)
        f_out.write(struct.pack(">I", 0))
    return Path(dst_s).stat().st_size


def decrypt_file(src: str | Path, dst: str | Path, passphrase: str) -> int:
    """Decrypt a DSMENC1 file to ``dst``. Returns bytes written."""
    if not passphrase:
        raise ValueError("encryption passphrase must not be empty")

    src_s, dst_s = str(src), str(dst)
    if _NATIVE is not None and hasattr(_NATIVE, "decrypt_file"):
        return int(_NATIVE.decrypt_file(src_s, dst_s, passphrase))

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    written = 0
    with open(src_s, "rb") as f_in, open(dst_s, "wb") as f_out:
        magic = f_in.read(8)
        if magic != _ENC_MAGIC:
            raise ValueError(
                "not a DSMENC1 encrypted backup (bad magic header)"
            )
        salt = f_in.read(_ENC_SALT_LEN)
        if len(salt) != _ENC_SALT_LEN:
            raise ValueError("truncated DSMENC1 header (salt)")
        key = _derive_key(passphrase, salt)
        aesgcm = AESGCM(key)
        while True:
            len_bytes = f_in.read(4)
            if len(len_bytes) != 4:
                raise ValueError("truncated DSMENC1 stream (chunk length)")
            plain_len = struct.unpack(">I", len_bytes)[0]
            if plain_len == 0:
                break
            if plain_len > _ENC_CHUNK:
                raise ValueError("encrypted chunk length exceeds frame limit")
            nonce = f_in.read(_ENC_NONCE_LEN)
            if len(nonce) != _ENC_NONCE_LEN:
                raise ValueError("truncated DSMENC1 stream (nonce)")
            ciphertext = f_in.read(plain_len + _ENC_TAG_LEN)
            if len(ciphertext) != plain_len + _ENC_TAG_LEN:
                raise ValueError("truncated DSMENC1 stream (ciphertext)")
            try:
                plain = aesgcm.decrypt(nonce, ciphertext, None)
            except InvalidTag as exc:
                raise ValueError(
                    "AES-GCM decrypt failed (wrong key or corrupt file)"
                ) from exc
            if len(plain) != plain_len:
                raise ValueError("decrypted chunk length mismatch")
            f_out.write(plain)
            written += len(plain)
    return written


def sha256_file(path: str | Path) -> str:
    """Return hex SHA-256 of a file (streaming)."""
    path_s = str(path)
    if _NATIVE is not None:
        return str(_NATIVE.sha256_file(path_s))

    hasher = hashlib.sha256()
    with open(path_s, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_files_parallel(paths: Sequence[str | Path]) -> List[Tuple[str, str]]:
    """Hash many files; uses Rayon when native is available."""
    path_strs = [str(p) for p in paths]
    if _NATIVE is not None:
        return [(str(a), str(b)) for a, b in _NATIVE.sha256_files_parallel(path_strs)]

    return [(p, sha256_file(p)) for p in path_strs]


def aggregate_f64(
    values: Sequence[float],
) -> Tuple[int, float, float, float, float]:
    """Return ``(count, sum, min, max, mean)`` for a numeric series."""
    if _NATIVE is not None:
        return tuple(_NATIVE.aggregate_f64(list(values)))  # type: ignore[return-value]

    vals = list(values)
    if not vals:
        return (0, 0.0, 0.0, 0.0, 0.0)
    total = sum(vals)
    return (len(vals), total, min(vals), max(vals), total / len(vals))


def hash_rows_parallel(rows: Sequence[Sequence[Any]]) -> List[str]:
    """Fingerprint rows as SHA-256 hex digests (for data comparison)."""
    str_rows: List[List[str]] = [
        ["" if cell is None else str(cell) for cell in row] for row in rows
    ]
    if _NATIVE is not None:
        return [str(d) for d in _NATIVE.hash_rows_parallel(str_rows)]

    digests: List[str] = []
    for row in str_rows:
        hasher = hashlib.sha256()
        for i, cell in enumerate(row):
            if i:
                hasher.update(b"\0")
            hasher.update(cell.encode("utf-8", errors="replace"))
        digests.append(hasher.hexdigest())
    return digests


__all__ = [
    "ENCRYPTION_FORMAT",
    "ENCRYPTION_SCHEME",
    "aggregate_f64",
    "backend_info",
    "decrypt_file",
    "encrypt_file",
    "gzip_compress_file",
    "gzip_decompress_file",
    "hash_rows_parallel",
    "is_available",
    "sha256_file",
    "sha256_files_parallel",
    "zstd_compress_file",
    "zstd_decompress_file",
]
