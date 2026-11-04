"""The four premium plugins after encrypted-export."""

import sqlite3

from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.pricing import PREMIUM_PRODUCT_IDS, PRICING_TIERS
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import AuthenticationManager


def _module(plugin_id, module_name):
    import importlib.util

    directory = bundled_plugin_dir(plugin_id)
    spec = importlib.util.spec_from_file_location(module_name, directory / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _auth(isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_auth_manager", AuthenticationManager(store=store))


def test_manifests_use_monthly_products():
    for plugin_id in (
        "extension-inventory",
        "multi-cloud-discovery",
        "trusted-sources-check",
        "maintenance-window-watch",
    ):
        manifest = load_manifest(bundled_plugin_dir(plugin_id))
        monthly = PREMIUM_PRODUCT_IDS[plugin_id]["monthly"]
        assert manifest.license is not None
        assert manifest.license.product_id == monthly
        assert manifest.license.pricing["monthly"] == PRICING_TIERS["plugin"]["monthly"]
        assert manifest.license.pricing["yearly"] == PRICING_TIERS["plugin"]["yearly"]
        assert manifest.license.pricing["one_time"] == PRICING_TIERS["plugin"]["one_time"]


def test_extension_inventory_flags_deprecated_and_outdated():
    module = _module("extension-inventory", "extension_inventory_under_test")
    report = module.classify_extensions(
        [
            {
                "name": "plpgsql",
                "default_version": "1.0",
                "installed_version": "1.0",
            },
            {
                "name": "xml2",
                "default_version": "1.1",
                "installed_version": "1.1",
            },
            {
                "name": "pg_stat_statements",
                "default_version": "1.10",
                "installed_version": "1.9",
            },
            {
                "name": "postgis",
                "default_version": "3.4.0",
                "installed_version": None,
            },
        ]
    )
    assert report["status"] == "fail"
    assert report["deprecated"] == [
        {"name": "xml2", "default_version": "1.1", "installed_version": "1.1"}
    ]
    assert report["outdated"][0]["name"] == "pg_stat_statements"
    assert report["available_count"] == 4


def test_extension_inventory_sqlite_is_not_available(
    tmp_path, isolated_secure_store, monkeypatch
):
    _auth(isolated_secure_store, monkeypatch)
    path = tmp_path / "app.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER)")
    connection = type(
        "Conn",
        (),
        {"config": type("Cfg", (), {"type": "sqlite", "database": str(path)})()},
    )()
    plugin = load_plugin_from_directory(bundled_plugin_dir("extension-inventory"))
    report = plugin.execute(connection)
    assert report["status"] == "not_available"


def test_multi_cloud_strips_passwords_and_uses_documented_hosts():
    module = _module("multi-cloud-discovery", "multi_cloud_under_test")
    report = module.discover(
        payloads={
            "digitalocean": {
                "databases": [
                    {
                        "id": "9cc10173-e9ea-4176-9dbc-a4cee4c4ff30",
                        "name": "backend",
                        "engine": "pg",
                        "status": "online",
                        "region": "nyc3",
                        "version": "16",
                        "db_names": ["defaultdb"],
                        "connection": {
                            "host": "backend.db.ondigitalocean.com",
                            "port": 25060,
                            "user": "doadmin",
                            "password": "do-secret",
                            "uri": "postgres://doadmin:do-secret@backend.db.ondigitalocean.com:25060/defaultdb",
                            "database": "defaultdb",
                        },
                        "users": [{"name": "doadmin", "password": "do-secret"}],
                    }
                ]
            },
            "supabase": [{"id": "abcdefghijklmnopqrst", "name": "app", "region": "us-east-1", "status": "ACTIVE_HEALTHY"}],
            "neon": {
                "projects": [
                    {
                        "id": "frosty-tree-1",
                        "name": "personal",
                        "region_id": "aws-us-east-2",
                        "pg_version": 17,
                    }
                ]
            },
            "neon_endpoints": {
                "frosty-tree-1": {
                    "endpoints": [
                        {
                            "id": "ep-cool",
                            "host": "ep-cool.us-east-2.aws.neon.tech",
                            "type": "read_write",
                        }
                    ]
                }
            },
            "aiven": {
                "services": [
                    {
                        "service_name": "pg-main",
                        "service_type": "pg",
                        "state": "RUNNING",
                        "service_uri": "postgres://avnadmin:secret@pg-main.aivencloud.com:12691/defaultdb",
                        "service_uri_params": {
                            "host": "pg-main.aivencloud.com",
                            "port": "12691",
                            "dbname": "defaultdb",
                            "password": "secret",
                        },
                    }
                ]
            },
        }
    )
    blob = str(report)
    assert "do-secret" not in blob
    assert "avnadmin:secret" not in blob
    hosts = {row["provider"]: row.get("host") for row in report["databases"]}
    assert hosts["digitalocean"] == "backend.db.ondigitalocean.com"
    assert hosts["supabase"] == "db.abcdefghijklmnopqrst.supabase.co"
    assert hosts["neon"] == "ep-cool.us-east-2.aws.neon.tech"
    assert hosts["aiven"] == "pg-main.aivencloud.com"
    assert report["status"] == "ok"


def test_missing_provider_token_is_not_available(isolated_secure_store, monkeypatch):
    _auth(isolated_secure_store, monkeypatch)
    for name in (
        "DSM_DIGITALOCEAN_TOKEN",
        "DIGITALOCEAN_ACCESS_TOKEN",
        "DSM_SUPABASE_ACCESS_TOKEN",
        "SUPABASE_ACCESS_TOKEN",
        "DSM_NEON_API_KEY",
        "NEON_API_KEY",
        "DSM_AIVEN_TOKEN",
        "AIVEN_API_TOKEN",
        "DSM_AIVEN_PROJECT",
    ):
        monkeypatch.delenv(name, raising=False)
    plugin = load_plugin_from_directory(bundled_plugin_dir("multi-cloud-discovery"))
    report = plugin.execute(providers=["digitalocean"])
    assert report["status"] == "not_available"
    assert report["databases"] == []
    assert "not configured" in report["providers"][0]["reason"]


def test_trusted_sources_neon_empty_is_open_and_a_cidr_can_match():
    module = _module("trusted-sources-check", "trusted_sources_under_test")
    open_neon = module.interpret_neon_project(
        {"settings": {"allowed_ips": {"ips": [], "protected_branches_only": False}}},
        "203.0.113.10",
    )
    assert open_neon["status"] == "fail"
    matched = module.interpret_supabase_restrictions(
        {
            "entitlement": "allowed",
            "config": {"dbAllowedCidrs": ["203.0.113.0/24"], "dbAllowedCidrsV6": []},
        },
        "203.0.113.10",
    )
    assert matched["status"] == "ok"
    plan = module.interpret_supabase_restrictions(
        {"entitlement": "disallowed", "config": {}},
        "203.0.113.10",
    )
    assert plan["status"] == "not_available"
    do_rules = module.interpret_digitalocean_firewall(
        {"rules": [{"type": "ip_addr", "value": "198.51.100.8"}]},
        "203.0.113.10",
    )
    assert do_rules["status"] == "fail"
    empty = module.interpret_digitalocean_firewall({"rules": []}, "203.0.113.10")
    assert empty["status"] == "partial"


def test_maintenance_uses_published_dates_and_pending_windows():
    module = _module("maintenance-window-watch", "maintenance_under_test")
    from datetime import date

    eol = module.classify_eol("postgresql", "13.23", date(2026, 11, 4))
    assert eol["eol_status"] == "eol"
    assert eol["eol_date"] == "2025-11-13"
    ending = module.classify_eol("postgresql", "14.24 (Ubuntu)", date(2026, 11, 4))
    assert ending["eol_status"] == "ending"
    assert ending["eol_date"] == "2026-11-12"
    supported = module.classify_eol("mysql", "8.4.13", date(2026, 11, 4))
    assert supported["eol_status"] == "supported"
    unknown = module.classify_eol("postgresql", "19.0", date(2026, 11, 4))
    assert unknown["status"] == "not_available"
    report = module.build_report(
        engine="postgresql",
        version="16.15",
        today=date(2026, 11, 4),
        digitalocean={
            "maintenance_window": {
                "day": "saturday",
                "hour": "08:45:12",
                "pending": True,
                "description": ["Upgrade to PostgreSQL 16.15"],
            }
        },
        aws_pending={
            "PendingMaintenanceActions": [
                {
                    "PendingMaintenanceActionDetails": [
                        {"Action": "system-update", "Description": "OS patch"}
                    ]
                }
            ]
        },
    )
    titles = [item["title"] for item in report["alerts"]]
    assert "DigitalOcean maintenance is pending" in titles
    assert "RDS maintenance is pending" in titles
    assert report["eol"]["eol_status"] == "supported"
