"""Unit tests for .env / SSH importers (fixture secrets only — no live network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from db_storage_manager.importers import (
    detect_platform_from_env_keys,
    import_env_file,
    import_ssh_key_path,
    list_platform_guides,
    merge_connections,
    parse_database_url,
    parse_dotenv,
    redact_connection,
    summarize_profile,
)
from db_storage_manager.importers.env_file import load_dotenv_file
from db_storage_manager.importers.ssh_keys import parse_db_sidecar, parse_vps_sidecar

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SUPABASE_ENV = FIXTURES / "sample.supabase.env"
LARAVEL_ENV = FIXTURES / "sample.laravel.env"
SSH_FOLDER = FIXTURES / "sample.ssh_folder"


def test_parse_database_url_postgres_supabase():
    url = (
        "postgresql://u:p@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
        "?pgbouncer=true&sslmode=require"
    )
    fields = parse_database_url(url)
    assert fields is not None
    assert fields["type"] == "postgresql"
    assert fields["host"] == "aws-0-us-east-2.pooler.supabase.com"
    assert fields["port"] == 6543
    assert fields["database"] == "postgres"
    assert fields["username"] == "u"
    assert fields["password"] == "p"
    assert fields["extra"]["sslmode"] == "require"
    assert fields["extra"]["pgbouncer"] is True


def test_parse_dotenv_strips_quotes():
    env = parse_dotenv('FOO="bar"\nBAZ=qux\n# c\nexport HELLO=world\n')
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "qux"
    assert env["HELLO"] == "world"


def test_import_supabase_env_prefers_direct_first():
    profiles = import_env_file(SUPABASE_ENV)
    assert len(profiles) >= 2
    # DIRECT_URL / UNPOOLED share host — dedupe leaves DIRECT + pooler
    types = {p["type"] for p in profiles}
    assert types == {"postgresql"}
    assert profiles[0]["extra"]["env_key"] in {
        "DIRECT_URL",
        "DATABASE_URL_UNPOOLED",
    }
    hosts = {p["host"] for p in profiles}
    assert "aws-0-us-east-2.pooler.supabase.com" in hosts
    # No service role key leaked as password
    for p in profiles:
        assert p["password"] == "s3cret-pass"
        assert "eyJ" not in (p["password"] or "")
        red = redact_connection(p)
        assert red["password"] == "***"
        assert "s3cret" not in str(red)


def test_import_laravel_discrete_env():
    profiles = import_env_file(LARAVEL_ENV)
    assert len(profiles) == 1
    p = profiles[0]
    assert p["type"] == "mysql"
    assert p["host"] == "127.0.0.1"
    assert p["port"] == 3306
    assert p["database"] == "laravel_app"
    assert p["username"] == "laravel"
    assert p["password"] == "laravel-secret"


def test_detect_platform_and_guides():
    env = load_dotenv_file(SUPABASE_ENV)
    assert detect_platform_from_env_keys(env.keys()) == "supabase"
    guides = list_platform_guides()
    assert any(g["id"] == "supabase" and g["oauth_automatable"] is False for g in guides)


def test_ssh_sidecar_parsers():
    vps = parse_vps_sidecar(SSH_FOLDER / "VPS.txt")
    assert vps["ssh_host"] == "203.0.113.10"
    assert vps["ssh_username"] == "bastionuser"
    assert vps["ssh_password"] == "not-a-real-password"

    db = parse_db_sidecar(SSH_FOLDER / "DB.txt", site_hint="sample.ssh_folder")
    assert db["database"] == "demo_web"
    assert db["username"] == "demo_db"
    assert db["type"] == "mysql"


def test_import_ssh_folder_references_key_path():
    profile = import_ssh_key_path(SSH_FOLDER)
    assert profile["type"] == "mysql"
    assert profile["database"] == "demo_web"
    assert profile["username"] == "demo_db"
    ssh = profile["ssh_config"]
    assert ssh["enabled"] is True
    assert ssh["ssh_host"] == "203.0.113.10"
    assert ssh["ssh_username"] == "bastionuser"
    assert ssh["ssh_key_path"] == str((SSH_FOLDER / "KEY").resolve())
    assert ssh["remote_port"] == 3306
    assert profile["extra"].get("ssh_private_key_pem") is None
    summary = summarize_profile(profile)
    assert summary["has_password"] is True
    assert "not-a-real" not in str(summary)


def test_merge_connections_dedupes_by_signature():
    a = {
        "id": "1",
        "name": "a",
        "type": "mysql",
        "host": "localhost",
        "port": 3306,
        "database": "demo_web",
        "username": "demo_db",
        "ssh_config": {"enabled": True, "ssh_host": "203.0.113.10"},
    }
    b = dict(a)
    b["id"] = "2"
    b["name"] = "b-renamed"
    merged, changed = merge_connections([a], [b])
    assert len(merged) == 1
    assert merged[0]["name"] == "b-renamed"
    assert merged[0]["id"] == "1"
    assert len(changed) == 1


@pytest.mark.parametrize(
    "path",
    [
        Path("/run/media/raider/Gaming_Images/Clients/BrightAds/connections/escortgirlsexy.com"),
        Path("/run/media/raider/Gaming_Images/Clients/BrightAds/connections/transsexualdivas.com"),
        Path("/run/media/raider/Gaming_Images/Clients/JosaCore/local/asesoresyasociados.org/.env"),
    ],
)
def test_live_paths_parse_when_present(path: Path):
    """Optional: parse real local ops paths when present (skip if missing)."""
    if not path.exists():
        pytest.skip(f"Live path missing: {path}")
    if path.is_dir() or path.name == "KEY":
        profile = import_ssh_key_path(path)
        assert profile["ssh_config"]["enabled"] is True
        assert profile["ssh_config"]["ssh_key_path"]
        red = redact_connection(profile)
        assert red["password"] in ("***", None, "")
        assert "BEGIN OPENSSH" not in str(red)
    else:
        profiles = import_env_file(path)
        assert profiles
        for p in profiles:
            assert p["type"] in ("postgresql", "mysql", "mongodb", "redis")
            red = redact_connection(p)
            assert red.get("password") in ("***", None, "")
