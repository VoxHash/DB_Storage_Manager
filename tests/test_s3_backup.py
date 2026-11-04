"""S3 backup adapter against a real S3 HTTP endpoint (moto server, no mocks)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

from moto.server import ThreadedMotoServer  # noqa: E402

from db_storage_manager import config  # noqa: E402
from db_storage_manager.backups.base import BackupOptions  # noqa: E402
from db_storage_manager.backups.manager import BackupManager  # noqa: E402
from db_storage_manager.backups.s3 import (  # noqa: E402
    S3BackupAdapter,
    S3NotConfiguredError,
    configuration_status,
    resolve_s3_config,
    save_s3_settings,
)
from db_storage_manager.db.base import ConnectionConfig  # noqa: E402
from db_storage_manager.experimental import ENV_VAR  # noqa: E402

PASSPHRASE = "s3-test-passphrase"
BUCKET = "dsm-backups"


@pytest.fixture(scope="module")
def s3_endpoint():
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    url = f"http://{host}:{port}"
    client = boto3.client(
        "s3",
        endpoint_url=url,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    client.create_bucket(Bucket=BUCKET)
    try:
        yield url
    finally:
        server.stop()


def _adapter(url: str, prefix: str, **extra) -> S3BackupAdapter:
    return S3BackupAdapter(
        {
            "bucket": BUCKET,
            "bucketPrefix": prefix,
            "endpoint": url,
            "region": "us-east-1",
            "accessKeyId": "testing",
            "secretAccessKey": "testing",
            **extra,
        }
    )


def _dump(path: Path, rows) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("DELETE FROM items")
        conn.executemany("INSERT INTO items(name) VALUES (?)", [(r,) for r in rows])
        conn.commit()
    finally:
        conn.close()
    return path


def _options(path: Path, **kw) -> BackupOptions:
    base = dict(
        connectionId="conn-s3",
        connectionName="Prod DB",
        databaseType="sqlite",
        backupPath=str(path),
        compression="zstd",
        encryption=True,
        encryptionKey=PASSPHRASE,
        metadata={"sourceStorageBytes": 123456},
    )
    base.update(kw)
    return BackupOptions(**base)


def test_create_list_verify_and_delete_roundtrip(s3_endpoint, tmp_path):
    adapter = _adapter(s3_endpoint, "roundtrip/")
    source = _dump(tmp_path / "src.db", ["a", "b"])

    info = asyncio.run(adapter.create_backup(_options(source)))
    assert info.metadata["destination"] == "s3"
    assert info.metadata["encryption"] is True
    assert info.metadata["compression"] == "zstd"
    assert info.metadata["dumpSize"] == source.stat().st_size
    assert info.metadata["sourceStorageBytes"] == 123456
    assert info.metadata["connectionName"] == "Prod DB"

    # Object is really in the bucket, under the prefix, as ciphertext.
    client = adapter.s3_client
    objects = client.list_objects_v2(Bucket=BUCKET, Prefix="roundtrip/")["Contents"]
    keys = [o["Key"] for o in objects]
    assert any(k.endswith(".zst.enc") for k in keys)
    body = client.get_object(Bucket=BUCKET, Key=info.metadata["key"])["Body"].read()
    assert body[:8] == b"DSMENC1\0"

    listed = asyncio.run(adapter.list_backups())
    assert [b.name for b in listed] == [info.name]
    assert listed[0].metadata["sha256"] == info.metadata["sha256"]
    assert listed[0].metadata["sourceStorageBytes"] == 123456

    ok = adapter.verify_remote_checksum(listed[0])
    assert ok["ok"] is True

    asyncio.run(adapter.delete_backup(listed[0].id))
    assert asyncio.run(adapter.list_backups()) == []


def test_plaintext_uploads_are_refused(s3_endpoint, tmp_path):
    adapter = _adapter(s3_endpoint, "plain/")
    source = _dump(tmp_path / "src.db", ["a"])
    with pytest.raises(ValueError, match="requires DSMENC1"):
        asyncio.run(
            adapter.create_backup(
                _options(source, encryption=False, encryptionKey=None)
            )
        )
    assert asyncio.run(adapter.list_backups()) == []


def test_corrupted_object_fails_checksum(s3_endpoint, tmp_path):
    adapter = _adapter(s3_endpoint, "corrupt/")
    source = _dump(tmp_path / "src.db", ["a"])
    info = asyncio.run(adapter.create_backup(_options(source)))
    adapter.s3_client.put_object(
        Bucket=BUCKET, Key=info.metadata["key"], Body=b"tampered-bytes"
    )
    result = adapter.verify_remote_checksum(info)
    assert result["ok"] is False and result["status"] == "fail"


def test_unconfigured_adapter_is_explicit():
    adapter = S3BackupAdapter({})
    with pytest.raises(S3NotConfiguredError):
        adapter.s3_client  # noqa: B018


def test_validate_options_checks_the_bucket(s3_endpoint, tmp_path):
    source = _dump(tmp_path / "src.db", ["a"])
    assert asyncio.run(_adapter(s3_endpoint, "v/").validate_options(_options(source)))
    missing = S3BackupAdapter(
        {**_adapter(s3_endpoint, "v/").config, "bucket": "no-such-bucket"}
    )
    assert not asyncio.run(missing.validate_options(_options(source)))


def test_settings_store_env_override_and_status(
    isolated_secure_store, monkeypatch
):
    store, _ = isolated_secure_store
    for name in ("DSM_S3_BUCKET", "DSM_S3_ENDPOINT", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    assert configuration_status()["configured"] is False

    save_s3_settings(
        bucket="from-store",
        prefix="dsm",
        endpoint="http://127.0.0.1:9",
        access_key_id="AKIDSTORE",
        secret_access_key="storesecret",
    )
    cfg = resolve_s3_config()
    assert cfg["bucket"] == "from-store"
    assert cfg["bucketPrefix"] == "dsm/"
    assert cfg["accessKeyId"] == "AKIDSTORE"
    assert configuration_status()["credentials"] == "key pair"

    # Blank keys on a second save keep the stored pair.
    save_s3_settings(bucket="from-store", prefix="dsm", access_key_id="", secret_access_key="")
    assert resolve_s3_config()["secretAccessKey"] == "storesecret"

    monkeypatch.setenv("DSM_S3_BUCKET", "from-env")
    assert resolve_s3_config()["bucket"] == "from-env"

    # Credentials live in the encrypted store, not in plain text on disk.
    for path in store_files(store):
        assert b"storesecret" not in path.read_bytes()


def store_files(store):
    import db_storage_manager.security.store as store_mod

    return [p for p in (store_mod.SETTINGS_FILE,) if p.exists()]


def test_manager_resolves_s3_adapter_only_when_configured(
    isolated_secure_store, monkeypatch
):
    for name in ("DSM_S3_BUCKET", "DSM_S3_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    manager = BackupManager()
    assert manager.get_adapter("s3") is None
    save_s3_settings(bucket="configured", endpoint="http://127.0.0.1:9")
    assert isinstance(BackupManager().get_adapter("s3"), S3BackupAdapter)


def test_full_restore_from_s3_into_a_database(
    s3_endpoint, tmp_path, monkeypatch, isolated_secure_store
):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    monkeypatch.setenv(ENV_VAR, "1")
    db = _dump(tmp_path / "live.db", ["alpha", "beta"])
    cfg = ConnectionConfig(
        id=f"s3-restore-{tmp_path.name}", name="live", type="sqlite", database=str(db)
    )
    adapter = _adapter(s3_endpoint, "e2e/")
    manager = BackupManager()

    info = asyncio.run(
        manager.create_backup(
            adapter,
            cfg,
            {"compression": "zstd", "encryption": True, "encryptionKey": PASSPHRASE},
        )
    )
    assert info.metadata["destination"] == "s3"
    assert info.metadata["sourceStorageBytes"] > 0
    assert manager.is_remote_backup(info)
    assert manager.backup_destination(info) == "s3"

    _dump(db, ["drifted"])
    manager.register_adapter("s3", adapter)

    with pytest.raises(Exception, match="Pre-flight"):
        asyncio.run(
            manager.full_restore(
                adapter, info, cfg, confirmation="live.db", encryption_key="wrong"
            )
        )
    conn = sqlite3.connect(str(db))
    assert [r[0] for r in conn.execute("SELECT name FROM items")] == ["drifted"]
    conn.close()

    asyncio.run(
        manager.full_restore(
            adapter, info, cfg, confirmation="live.db", encryption_key=PASSPHRASE
        )
    )
    conn = sqlite3.connect(str(db))
    assert sorted(r[0] for r in conn.execute("SELECT name FROM items")) == ["alpha", "beta"]
    conn.close()
