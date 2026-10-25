"""Tests for native performance helpers (Rust path or Python fallback)."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

from db_storage_manager.native import (
    aggregate_f64,
    backend_info,
    decrypt_file,
    encrypt_file,
    gzip_compress_file,
    gzip_decompress_file,
    hash_rows_parallel,
    is_available,
    sha256_file,
    sha256_files_parallel,
    zstd_compress_file,
    zstd_decompress_file,
)


def test_backend_info_shape():
    info = backend_info()
    assert "available" in info
    assert info["language"] in ("rust", "python")
    assert info["available"] is is_available()


def test_gzip_roundtrip(tmp_path: Path):
    src = tmp_path / "payload.bin"
    gz = tmp_path / "payload.bin.gz"
    out = tmp_path / "payload.out"
    payload = b"db-storage-manager-native-test\n" * 4000
    src.write_bytes(payload)

    size = gzip_compress_file(src, gz)
    assert size > 0
    assert gz.exists()

    written = gzip_decompress_file(gz, out)
    assert written == len(payload)
    assert out.read_bytes() == payload


def test_sha256_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "hash-me.txt"
    data = b"checksum-validation\n" * 200
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_file(path) == expected


def test_sha256_files_parallel(tmp_path: Path):
    paths = []
    for i in range(4):
        p = tmp_path / f"f{i}.bin"
        p.write_bytes(f"file-{i}".encode() * 100)
        paths.append(str(p))
    results = sha256_files_parallel(paths)
    assert len(results) == 4
    for path, digest in results:
        assert digest == sha256_file(path)


def test_aggregate_f64():
    count, total, mn, mx, mean = aggregate_f64([1.0, 2.0, 3.0, 4.0])
    assert count == 4
    assert total == 10.0
    assert mn == 1.0
    assert mx == 4.0
    assert mean == 2.5
    assert aggregate_f64([]) == (0, 0.0, 0.0, 0.0, 0.0)


def test_hash_rows_parallel_stable():
    rows = [["a", "1"], ["b", "2"], ["a", "1"]]
    digests = hash_rows_parallel(rows)
    assert len(digests) == 3
    assert digests[0] == digests[2]
    assert digests[0] != digests[1]


def test_gzip_compatible_with_stdlib(tmp_path: Path):
    """Native compress must be readable by Python gzip."""
    src = tmp_path / "std.bin"
    gz = tmp_path / "std.bin.gz"
    src.write_bytes(b"stdlib-compat\n" * 500)
    gzip_compress_file(src, gz)
    with gzip.open(gz, "rb") as fh:
        assert fh.read() == src.read_bytes()


def test_zstd_roundtrip_native_api(tmp_path: Path):
    src = tmp_path / "z.bin"
    zst = tmp_path / "z.bin.zst"
    out = tmp_path / "z.out"
    payload = b"zstd-native-api\n" * 800
    src.write_bytes(payload)
    assert zstd_compress_file(src, zst) > 0
    assert zstd_decompress_file(zst, out) == len(payload)
    assert out.read_bytes() == payload


def test_encrypt_decrypt_native_api(tmp_path: Path):
    src = tmp_path / "e.bin"
    enc = tmp_path / "e.bin.enc"
    out = tmp_path / "e.out"
    payload = b"enc-native-api\n" * 600
    src.write_bytes(payload)
    assert encrypt_file(src, enc, "api-pass") > 0
    assert decrypt_file(enc, out, "api-pass") == len(payload)
    assert out.read_bytes() == payload
    info = backend_info()
    assert info.get("encryption_format") == "DSMENC1"
    assert info.get("encryption_scheme") == "aes-256-gcm-pbkdf2"
