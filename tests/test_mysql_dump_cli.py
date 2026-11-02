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


def test_require_missing_mentions_install_hint(monkeypatch):
    monkeypatch.setattr("db_storage_manager.db.mysql.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="mariadb-clients") as excinfo:
        require_mysql_cli()
    msg = str(excinfo.value)
    assert "mysqldump" in msg
    assert "mariadb-dump" in msg
    assert "not found on PATH" in msg
