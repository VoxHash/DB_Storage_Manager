"""MySQL dump CLI resolution: prefer mariadb-dump, fall back to mysqldump."""

from pathlib import Path

import pytest

from db_storage_manager.db.mysql import (
    require_mysql_cli,
    resolve_mysql_cli,
)


def test_resolve_prefers_mariadb_dump(monkeypatch, tmp_path: Path):
    dump = tmp_path / "mysqldump"
    dump.write_text("#!/bin/sh\n", encoding="utf-8")
    dump.chmod(0o755)
    maria = tmp_path / "mariadb-dump"
    maria.write_text("#!/bin/sh\n", encoding="utf-8")
    maria.chmod(0o755)

    def fake_which(name: str):
        if name == "mysqldump":
            return str(dump)
        if name == "mariadb-dump":
            return str(maria)
        return None

    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", fake_which)
    assert resolve_mysql_cli() == str(maria)
    assert require_mysql_cli() == str(maria)


def test_resolve_falls_back_to_mysqldump(monkeypatch, tmp_path: Path):
    dump = tmp_path / "mysqldump"
    dump.write_text("#!/bin/sh\n", encoding="utf-8")
    dump.chmod(0o755)

    def fake_which(name: str):
        if name == "mysqldump":
            return str(dump)
        return None

    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", fake_which)
    assert resolve_mysql_cli() == str(dump)


def _script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_resolve_skips_mariadb_that_cannot_load_libedit(monkeypatch, tmp_path: Path):
    broken = tmp_path / "mariadb"
    good = tmp_path / "mysql"
    _script(
        broken,
        "#!/bin/sh\n"
        "echo 'mariadb: error while loading shared libraries: "
        "libedit.so.2: cannot open shared object file: No such file or directory' >&2\n"
        "exit 127\n",
    )
    _script(good, "#!/bin/sh\necho 'mysql  Ver 8.0.0'\nexit 0\n")

    def fake_which(name: str):
        if name == "mariadb":
            return str(broken)
        if name == "mysql":
            return str(good)
        return None

    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", fake_which)
    assert resolve_mysql_cli(("mariadb", "mysql")) == str(good)


def test_require_broken_clients_names_libedit(monkeypatch, tmp_path: Path):
    broken = tmp_path / "mariadb"
    _script(
        broken,
        "#!/bin/sh\n"
        "echo 'error while loading shared libraries: libedit.so.2: "
        "cannot open shared object file' >&2\n"
        "exit 127\n",
    )

    def fake_which(name: str):
        if name == "mariadb":
            return str(broken)
        return None

    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", fake_which)
    with pytest.raises(RuntimeError, match="libedit.so.2") as excinfo:
        require_mysql_cli(("mariadb", "mysql"), purpose="restore")
    message = str(excinfo.value)
    assert "mariadb-clients" in message
    assert "cannot start" in message


def test_restore_uses_mysql_when_mariadb_cannot_start(monkeypatch, tmp_path: Path):
    import asyncio

    broken = tmp_path / "mariadb"
    good = tmp_path / "mysql"
    _script(
        broken,
        "#!/bin/sh\n"
        "echo 'mariadb: error while loading shared libraries: libedit.so.2: "
        "cannot open shared object file' >&2\n"
        "exit 127\n",
    )
    _script(good, "#!/bin/sh\necho 'mysql  Ver 8.0.0'\nexit 0\n")
    dump = tmp_path / "dump.sql"
    dump.write_text("SELECT 1;\n", encoding="utf-8")

    def fake_which(name: str):
        if name == "mariadb":
            return str(broken)
        if name == "mysql":
            return str(good)
        return None

    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", fake_which)
    started = []

    class _Proc:
        returncode = 0

        async def communicate(self, input=None):
            return b"", b""

    async def fake_exec(*cmd, **kwargs):
        started.append(cmd[0])
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    from db_storage_manager.db.base import ConnectionConfig
    from db_storage_manager.db.mysql import MySQLConnection

    connection = MySQLConnection(
        ConnectionConfig(
            id="c1",
            name="lab",
            type="mysql",
            host="127.0.0.1",
            port=3306,
            database="app",
            username="app",
            password="secret",
        )
    )
    connection.connection = object()

    async def _run():
        await connection.restore_backup(str(dump))

    asyncio.run(_run())
    assert started == [str(good)]
    assert "secret" not in " ".join(started)


def test_require_missing_mentions_install_hint(monkeypatch):
    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="mariadb-clients") as excinfo:
        require_mysql_cli()
    msg = str(excinfo.value)
    assert "mysqldump" in msg
    assert "mariadb-dump" in msg
    assert "not found on PATH" in msg
