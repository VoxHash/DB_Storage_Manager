"""
Native performance helpers (Rust/PyO3) with pure-Python fallbacks.

Build the extension from the repo root::

    pip install maturin
    cd native/db_storage_native && maturin develop --release

Or::

    pip install -e ".[native]"

When the compiled module is unavailable, callers transparently use Python
implementations so the desktop app keeps working.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_NATIVE = None
_NATIVE_ERROR: Optional[str] = None

try:
    import db_storage_native as _NATIVE  # type: ignore
except Exception as exc:  # pragma: no cover - import path varies by build
    _NATIVE_ERROR = str(exc)
    _NATIVE = None


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
    "aggregate_f64",
    "backend_info",
    "gzip_compress_file",
    "gzip_decompress_file",
    "hash_rows_parallel",
    "is_available",
    "sha256_file",
    "sha256_files_parallel",
]
