"""Query optimization suggestions: heuristics, real SQLite EXPLAIN, Qt smoke."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from db_storage_manager.analysis.query_suggestions import (
    analyze_explain_plan,
    analyze_sql_heuristics,
    fetch_explain_plan,
    is_read_query,
    suggest_for_query,
)
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.factory import DatabaseConnectionFactory


def _sqlite(tmp_path: Path, name: str = "suggest.db"):
    cfg = ConnectionConfig(
        id="suggest-1",
        name="suggest-sqlite",
        type="sqlite",
        database=str(tmp_path / name),
    )
    return DatabaseConnectionFactory.create_connection(cfg)


def test_is_read_query():
    assert is_read_query("SELECT 1")
    assert is_read_query("  select id from t")
    assert not is_read_query("INSERT INTO t VALUES (1)")
    assert not is_read_query("EXPLAIN QUERY PLAN SELECT 1")


def test_heuristics_select_star_and_leading_like():
    sql = "SELECT * FROM users WHERE name LIKE '%smith' ORDER BY name"
    codes = {s.code for s in analyze_sql_heuristics(sql)}
    assert "select_star" in codes
    assert "leading_wildcard_like" in codes
    assert "order_without_limit" in codes
    assert "missing_where" not in codes


def test_heuristics_missing_where():
    codes = {s.code for s in analyze_sql_heuristics("SELECT id FROM items")}
    assert "missing_where" in codes


def test_analyze_sqlite_explain_scan_text():
    plan = [[0, 0, 0, "SCAN items"]]
    codes = {s.code for s in analyze_explain_plan(plan, "sqlite")}
    assert "sqlite_table_scan" in codes


def test_analyze_sqlite_explain_temp_btree_and_auto_index():
    plan = [
        [0, 0, 0, "SCAN t1"],
        [0, 0, 0, "USE TEMP B-TREE FOR ORDER BY"],
        [0, 0, 0, "SEARCH t2 USING AUTOMATIC COVERING INDEX (id=?)"],
    ]
    codes = {s.code for s in analyze_explain_plan(plan, "sqlite")}
    assert "sqlite_temp_btree" in codes
    assert "sqlite_auto_index" in codes


def test_fetch_explain_and_suggest_real_sqlite(tmp_path: Path):
    async def run() -> None:
        conn = _sqlite(tmp_path)
        await conn.connect()
        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('a'), ('b'), ('c')",
            safe_mode=False,
        )
        await conn.connection.commit()

        # No index on name → SCAN expected for filtered SELECT *
        sql = "SELECT * FROM items WHERE name = 'a'"
        plan = await fetch_explain_plan(conn, sql, safe_mode=True)
        assert plan is not None
        assert len(plan) >= 1
        detail = str(plan[0][-1]).upper()
        assert "SCAN" in detail or "SEARCH" in detail

        advice = await suggest_for_query(
            sql, connection=conn, safe_mode=True, db_type="sqlite"
        )
        codes = {s["code"] for s in advice["suggestions"]}
        assert "select_star" in codes
        # Live plan should surface a scan/search-based hint when applicable
        assert advice["explainPlan"] is not None
        assert advice["explainSkippedSafeMode"] is False
        assert advice["counts"]["total"] >= 1

        # Safe Mode must not run EXPLAIN for non-SELECT
        skipped = await suggest_for_query(
            "DELETE FROM items",
            connection=conn,
            safe_mode=True,
            db_type="sqlite",
        )
        assert skipped["explainSkippedSafeMode"] is True
        assert skipped["explainPlan"] is None

        # Indexed lookup should not flag table-scan-without-index
        await conn.execute_query(
            "CREATE INDEX idx_items_name ON items(name)",
            safe_mode=False,
        )
        indexed_sql = "SELECT id FROM items WHERE name = 'a'"
        indexed = await suggest_for_query(
            indexed_sql, connection=conn, safe_mode=True, db_type="sqlite"
        )
        indexed_codes = {s["code"] for s in indexed["suggestions"]}
        assert "sqlite_table_scan" not in indexed_codes

        await conn.disconnect()

    asyncio.run(run())


def test_suggest_uses_provided_explain_plan_without_connection():
    async def run() -> None:
        advice = await suggest_for_query(
            "SELECT id FROM t WHERE x = 1",
            explain_plan=[[0, 0, 0, "SCAN t"]],
            db_type="sqlite",
        )
        codes = {s["code"] for s in advice["suggestions"]}
        assert "sqlite_table_scan" in codes

    asyncio.run(run())


def test_query_widget_offscreen_smoke(tmp_path: Path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from db_storage_manager.gui.query import QueryWidget

    app = QApplication.instance() or QApplication([])
    db_path = tmp_path / "ui.db"

    async def seed() -> None:
        conn = _sqlite(tmp_path, "ui.db")
        await conn.connect()
        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('x')",
            safe_mode=False,
        )
        await conn.connection.commit()
        await conn.disconnect()

    asyncio.run(seed())

    profile = {
        "id": "ui-1",
        "name": "ui-sqlite",
        "type": "sqlite",
        "database": str(db_path),
    }
    widget = QueryWidget([profile])
    assert widget.suggestions_table.columnCount() == 4
    assert widget.analyze_button.text()
    assert widget.safe_mode_check.isChecked() is True

    widget.connection_combo.setCurrentIndex(1)
    widget.query_edit.setPlainText("SELECT * FROM items WHERE name LIKE '%x'")
    widget._analyze_query()
    assert widget.suggestions_table.rowCount() >= 1
    # Heuristic codes should appear in the table
    titles = [
        widget.suggestions_table.item(r, 1).text()
        for r in range(widget.suggestions_table.rowCount())
    ]
    assert any("SELECT *" in t or "wildcard" in t.lower() or "LIKE" in t for t in titles)

    widget._execute_query()
    assert widget.results_table.rowCount() >= 1
    assert widget.suggestions_table.rowCount() >= 1

    widget.update_connections([])
    assert widget.connection_combo.count() == 1
    widget.close()
    app.processEvents()
