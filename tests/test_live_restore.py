"""Full-restore rehearsal against live PostgreSQL and MySQL/MariaDB servers.

SQLite is covered in ``test_full_restore.py``. These tests drive the real
``BackupManager.create_backup`` / ``full_restore`` path (pg_dump + pg_restore,
mysqldump / mariadb-dump + client) against a running server and are skipped
unless the server is described through the environment (CI sets these from its
service containers; see ``.github/workflows/live-restore.yml``):

    DSM_LIVE_PG_HOST / _PORT / _USER / _PASSWORD
    DSM_LIVE_MYSQL_HOST / _PORT / _USER / _PASSWORD

The account must be allowed to create and drop databases: every test restores
into its own throw-away database and never touches an existing one.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import pytest

from db_storage_manager import audit, config
from db_storage_manager.backups.local import LocalBackupAdapter
from db_storage_manager.backups.manager import BackupManager, RestoreRefused
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.experimental import ENV_VAR
from db_storage_manager.native import sha256_file

PASSPHRASE = "live-restore-passphrase"
SAFETY_PASSPHRASE = "live-safety-passphrase"

Rows = List[Tuple[Any, ...]]


def _live_env(prefix: str) -> Dict[str, Any] | None:
    host = os.environ.get(f"{prefix}_HOST")
    user = os.environ.get(f"{prefix}_USER")
    if not host or not user:
        return None
    return {
        "host": host,
        "port": int(os.environ[f"{prefix}_PORT"]),
        "user": user,
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
    }


# --------------------------------------------------------------------------
# Engine drivers: seed / mutate / read through the real client libraries
# --------------------------------------------------------------------------


class _Postgres:
    type = "postgresql"
    label = "postgres"

    def __init__(self, env: Dict[str, Any]):
        self.env = env

    def _connect(self, database: str):
        import psycopg2

        conn = psycopg2.connect(
            host=self.env["host"],
            port=self.env["port"],
            user=self.env["user"],
            password=self.env["password"],
            dbname=database,
        )
        conn.autocommit = True
        return conn

    def create_database(self, name: str) -> None:
        conn = self._connect("postgres")
        try:
            conn.cursor().execute(f'CREATE DATABASE "{name}"')
        finally:
            conn.close()

    def drop_database(self, name: str) -> None:
        conn = self._connect("postgres")
        try:
            conn.cursor().execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            conn.close()

    def execute(self, database: str, statements: List[str]) -> None:
        conn = self._connect(database)
        try:
            cur = conn.cursor()
            for statement in statements:
                cur.execute(statement)
        finally:
            conn.close()

    def fetch(self, database: str, sql: str) -> Rows:
        conn = self._connect(database)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            return [tuple(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def tables(self, database: str) -> List[str]:
        return [
            row[0]
            for row in self.fetch(
                database,
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name",
            )
        ]

    SEED = [
        "CREATE TABLE customers ("
        " id integer PRIMARY KEY, name text NOT NULL, notes text,"
        " balance numeric(12,2) NOT NULL DEFAULT 0)",
        "CREATE TABLE orders ("
        " id integer PRIMARY KEY,"
        " customer_id integer NOT NULL REFERENCES customers(id),"
        " total numeric(12,2) NOT NULL)",
        "CREATE INDEX orders_customer_idx ON orders(customer_id)",
        "CREATE VIEW big_orders AS SELECT id, total FROM orders WHERE total > 100",
        "INSERT INTO customers VALUES"
        " (1, 'Ada Lovelace', 'first programmer', 120.50),"
        " (2, 'Grace Hopper', NULL, 0),"
        " (3, 'Zoë Ünïcode — テスト', 'multi-byte', 9999999999.99)",
        "INSERT INTO orders VALUES (10, 1, 250.00), (11, 1, 20.00), (12, 3, 101.01)",
    ]
    DRIFT = [
        "DELETE FROM orders",
        "UPDATE customers SET name = 'changed', balance = -1",
        "INSERT INTO customers VALUES (4, 'Drifted', 'after backup', 1)",
        "DROP VIEW big_orders",
        "DROP TABLE orders",
    ]
    SNAPSHOT_QUERIES = {
        "customers": "SELECT id, name, notes, balance::text FROM customers ORDER BY id",
        "orders": "SELECT id, customer_id, total::text FROM orders ORDER BY id",
        "big_orders": "SELECT id, total::text FROM big_orders ORDER BY id",
        "indexes": (
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename IN ('customers', 'orders') ORDER BY indexname"
        ),
    }


class _MySQL:
    type = "mysql"
    label = "mysql"

    def __init__(self, env: Dict[str, Any]):
        self.env = env

    def _connect(self, database: str | None):
        import pymysql

        return pymysql.connect(
            host=self.env["host"],
            port=self.env["port"],
            user=self.env["user"],
            password=self.env["password"],
            database=database,
            autocommit=True,
            charset="utf8mb4",
        )

    def create_database(self, name: str) -> None:
        conn = self._connect(None)
        try:
            conn.cursor().execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"
            )
        finally:
            conn.close()

    def drop_database(self, name: str) -> None:
        conn = self._connect(None)
        try:
            conn.cursor().execute(f"DROP DATABASE IF EXISTS `{name}`")
        finally:
            conn.close()

    def execute(self, database: str, statements: List[str]) -> None:
        conn = self._connect(database)
        try:
            cur = conn.cursor()
            for statement in statements:
                cur.execute(statement)
        finally:
            conn.close()

    def fetch(self, database: str, sql: str) -> Rows:
        conn = self._connect(database)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            return [tuple(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def tables(self, database: str) -> List[str]:
        return sorted(
            row[0]
            for row in self.fetch(
                database,
                "SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema = '{database}' AND table_type = 'BASE TABLE'",
            )
        )

    SEED = [
        "CREATE TABLE customers ("
        " id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, notes TEXT,"
        " balance DECIMAL(12,2) NOT NULL DEFAULT 0) ENGINE=InnoDB"
        " DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE orders ("
        " id INT PRIMARY KEY, customer_id INT NOT NULL, total DECIMAL(12,2) NOT NULL,"
        " KEY orders_customer_idx (customer_id),"
        " CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id)"
        " REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE VIEW big_orders AS SELECT id, total FROM orders WHERE total > 100",
        "INSERT INTO customers VALUES"
        " (1, 'Ada Lovelace', 'first programmer', 120.50),"
        " (2, 'Grace Hopper', NULL, 0),"
        " (3, 'Zoë Ünïcode — テスト', 'multi-byte', 9999999999.99)",
        "INSERT INTO orders VALUES (10, 1, 250.00), (11, 1, 20.00), (12, 3, 101.01)",
    ]
    DRIFT = [
        "DELETE FROM orders",
        "UPDATE customers SET name = 'changed', balance = -1",
        "INSERT INTO customers VALUES (4, 'Drifted', 'after backup', 1)",
        "DROP VIEW big_orders",
        "DROP TABLE orders",
    ]
    SNAPSHOT_QUERIES = {
        "customers": "SELECT id, name, notes, CAST(balance AS CHAR) "
        "FROM customers ORDER BY id",
        "orders": "SELECT id, customer_id, CAST(total AS CHAR) FROM orders ORDER BY id",
        "big_orders": "SELECT id, CAST(total AS CHAR) FROM big_orders ORDER BY id",
        "indexes": (
            "SELECT DISTINCT index_name FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = 'orders' "
            "ORDER BY index_name"
        ),
    }


def _snapshot(driver, database: str) -> Dict[str, Rows]:
    return {
        name: driver.fetch(database, sql)
        for name, sql in driver.SNAPSHOT_QUERIES.items()
    }


def _restore_client_available(driver) -> bool:
    if driver.type == "postgresql":
        return bool(shutil.which("pg_dump") and shutil.which("pg_restore"))
    from db_storage_manager.db.mysql import resolve_mysql_cli

    return bool(
        resolve_mysql_cli(("mariadb-dump", "mysqldump"))
        and resolve_mysql_cli(("mariadb", "mysql"))
    )


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------


@pytest.fixture(params=["postgresql", "mysql"])
def live(request, tmp_path, monkeypatch, isolated_secure_store):
    if request.param == "postgresql":
        env = _live_env("DSM_LIVE_PG")
        if env is None:
            pytest.skip("DSM_LIVE_PG_HOST / DSM_LIVE_PG_USER not set")
        driver: Any = _Postgres(env)
    else:
        env = _live_env("DSM_LIVE_MYSQL")
        if env is None:
            pytest.skip("DSM_LIVE_MYSQL_HOST / DSM_LIVE_MYSQL_USER not set")
        driver = _MySQL(env)
    if not _restore_client_available(driver):
        pytest.skip(f"{driver.label} command-line client tools are not on PATH")

    store, _ = isolated_secure_store
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    monkeypatch.delenv(ENV_VAR, raising=False)
    settings = store.get_settings()
    settings["experimental"] = {"restore": True}
    store.set_settings(settings)

    database = f"dsm_live_{uuid.uuid4().hex[:12]}"
    driver.create_database(database)
    driver.execute(database, driver.SEED)

    cfg = ConnectionConfig(
        id=f"live-{database}",
        name=f"live-{driver.label}",
        type=driver.type,
        host=env["host"],
        port=env["port"],
        database=database,
        username=env["user"],
        password=env["password"],
    )
    backups = tmp_path / "backups"
    adapter = LocalBackupAdapter(base_path=backups)
    manager = BackupManager()

    def make_backup(**opts):
        return asyncio.run(manager.create_backup(adapter, cfg, opts))

    def restore(backup, **kwargs):
        kwargs.setdefault("confirmation", database)
        return asyncio.run(manager.full_restore(adapter, backup, cfg, **kwargs))

    try:
        yield {
            "driver": driver,
            "database": database,
            "cfg": cfg,
            "adapter": adapter,
            "backups": backups,
            "manager": manager,
            "make_backup": make_backup,
            "restore": restore,
        }
    finally:
        try:
            from db_storage_manager.db.pool import close_sql_engine_pool_blocking

            close_sql_engine_pool_blocking()
        except Exception:  # noqa: BLE001
            pass
        driver.drop_database(database)


# --------------------------------------------------------------------------
# Rehearsals
# --------------------------------------------------------------------------


def test_encrypted_restore_rebuilds_the_database_and_keeps_a_safety_backup(live):
    driver, database = live["driver"], live["database"]
    baseline = _snapshot(driver, database)
    assert baseline["customers"][2][1] == "Zoë Ünïcode — テスト"
    assert len(baseline["big_orders"]) == 2

    backup = live["make_backup"](
        compression="zstd", encryption=True, encryptionKey=PASSPHRASE
    )
    assert backup.metadata["encryption"] is True
    assert Path(backup.path).read_bytes()[:8] == b"DSMENC1\0"
    assert backup.metadata["sha256"] == sha256_file(Path(backup.path))

    driver.execute(database, driver.DRIFT)
    drifted = _snapshot_after_drift(driver, database)
    assert drifted["customers"][0][1] == "changed"

    stages: List[str] = []
    result = live["restore"](
        backup,
        encryption_key=PASSPHRASE,
        safety_backup_dir=live["backups"],
        safety_passphrase=SAFETY_PASSPHRASE,
        on_stage=stages.append,
    )

    assert stages == ["gate", "preflight", "safety_backup", "restore", "done"]
    assert _snapshot(driver, database) == baseline

    safety = Path(live["backups"]) / result["safetyBackup"]
    assert safety.read_bytes()[:8] == b"DSMENC1\0"
    listed = asyncio.run(live["adapter"].list_backups())
    safety_info = next(b for b in listed if b.name == result["safetyBackup"])
    dry = live["manager"].dry_run_restore(
        safety_info, encryption_key=SAFETY_PASSPHRASE
    )
    assert dry["ok"] is True

    entry = audit.read_audit()[-1]
    assert entry["action"] == "backup.restore" and entry["outcome"] == "completed"
    assert entry["targetDatabase"] == database
    assert PASSPHRASE not in audit.audit_log_path().read_text()


def _snapshot_after_drift(driver, database: str) -> Dict[str, Rows]:
    """Snapshot of the tables that survive the drift (orders/view are dropped)."""
    return {
        "customers": driver.fetch(
            database, driver.SNAPSHOT_QUERIES["customers"]
        ),
        "tables": driver.tables(database),
    }


def test_safety_backup_holds_the_pre_restore_state(live):
    driver, database = live["driver"], live["database"]
    backup = live["make_backup"](compression="gzip")
    driver.execute(database, driver.DRIFT)
    drifted_customers = driver.fetch(database, driver.SNAPSHOT_QUERIES["customers"])

    result = live["restore"](
        backup,
        safety_backup_dir=live["backups"],
        safety_passphrase=SAFETY_PASSPHRASE,
    )
    assert driver.fetch(database, driver.SNAPSHOT_QUERIES["customers"]) != (
        drifted_customers
    )

    restored_customers = driver.fetch(database, driver.SNAPSHOT_QUERIES["customers"])
    listed = asyncio.run(live["adapter"].list_backups())
    safety_info = next(b for b in listed if b.name == result["safetyBackup"])

    if driver.type == "postgresql":
        # The safety backup has no ``orders`` table, but the restore above
        # recreated it with a foreign key to ``customers``. pg_restore --clean
        # cannot drop ``customers`` while that dependent object exists, so the
        # roll-back fails loudly instead of replacing anything. Rehearsing
        # into a scratch database (ROADMAP) is the supported way around this.
        with pytest.raises(RuntimeError, match="pg_restore failed"):
            live["restore"](safety_info, encryption_key=SAFETY_PASSPHRASE)
        assert audit.read_audit()[-1]["outcome"] == "failed"
        assert audit.read_audit()[-1]["stage"] == "restore"
        assert (
            driver.fetch(database, driver.SNAPSHOT_QUERIES["customers"])
            == restored_customers
        )
        return

    # MySQL dumps drop and recreate each table with foreign key checks off, so
    # rolling forward from the safety backup returns the drifted customers.
    live["restore"](safety_info, encryption_key=SAFETY_PASSPHRASE)
    assert (
        driver.fetch(database, driver.SNAPSHOT_QUERIES["customers"])
        == drifted_customers
    )


def test_objects_created_after_the_backup_survive_a_restore(live):
    """Documented behaviour: restore replaces backed-up objects, it does not
    drop tables that only exist on the target (that is what a scratch database
    is for)."""
    driver, database = live["driver"], live["database"]
    baseline = _snapshot(driver, database)
    backup = live["make_backup"](compression="gzip")
    driver.execute(
        database,
        ["CREATE TABLE created_later (id integer PRIMARY KEY)",
         "INSERT INTO created_later VALUES (1)",
         "UPDATE customers SET name = 'changed'"],
    )
    live["restore"](backup)
    assert _snapshot(driver, database) == baseline
    assert "created_later" in driver.tables(database)


def test_wrong_confirmation_and_wrong_passphrase_never_touch_the_server(live):
    driver, database = live["driver"], live["database"]
    backup = live["make_backup"](
        compression="gzip", encryption=True, encryptionKey=PASSPHRASE
    )
    driver.execute(database, ["UPDATE customers SET name = 'changed'"])
    changed = _snapshot_after_drift(driver, database)

    with pytest.raises(RestoreRefused, match="Confirmation"):
        live["restore"](backup, confirmation="not-the-database",
                        encryption_key=PASSPHRASE)
    with pytest.raises(RestoreRefused, match="Pre-flight"):
        live["restore"](backup, encryption_key="not-the-passphrase")

    assert _snapshot_after_drift(driver, database) == changed
    stages = [e.get("stage") for e in audit.read_audit()]
    assert stages[-2:] == ["gate", "preflight"]


def test_engine_mismatch_is_refused_before_connecting(live):
    backup = live["make_backup"](compression="gzip")
    other_type = "mysql" if live["driver"].type == "postgresql" else "postgresql"
    other = ConnectionConfig(
        id="mismatch",
        name="other",
        type=other_type,
        host="127.0.0.1",
        port=1,
        database="nowhere",
    )
    with pytest.raises(RestoreRefused, match=live["driver"].label):
        asyncio.run(
            live["manager"].full_restore(
                live["adapter"], backup, other, confirmation="nowhere"
            )
        )


# --------------------------------------------------------------------------
# pg_restore version-skew handling (needs no server)
# --------------------------------------------------------------------------

_SKEW = (
    "pg_restore: error: could not execute query: ERROR:  unrecognized "
    'configuration parameter "transaction_timeout"\n'
    "Command was: SET transaction_timeout = 0;\n"
    "pg_restore: warning: errors ignored on restore: 1\n"
)


def test_pg_restore_version_skew_is_recognised():
    from db_storage_manager.db.postgres import pg_restore_only_version_skew

    assert pg_restore_only_version_skew(_SKEW) is True


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "pg_restore: error: connection to server failed\n",
        # A real failure next to the harmless one must still fail.
        _SKEW
        + "pg_restore: error: could not execute query: ERROR:  permission denied\n"
        "Command was: CREATE TABLE public.t (id integer);\n",
        # Unknown parameter, but not a SET statement.
        "pg_restore: error: could not execute query: ERROR:  unrecognized "
        'configuration parameter "x"\nCommand was: ALTER SYSTEM RESET x;\n',
    ],
)
def test_pg_restore_real_errors_are_not_treated_as_version_skew(stderr):
    from db_storage_manager.db.postgres import pg_restore_only_version_skew

    assert pg_restore_only_version_skew(stderr) is False
