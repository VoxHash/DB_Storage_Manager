"""PostgreSQL restore drops archived tables before pg_restore --clean."""

from db_storage_manager.db.postgres import (
    drop_table_cascade_sql,
    pg_restore_table_idents,
)


LISTING = """
;
; Archive created at 2026-11-04
;
204; 1259 16390 TABLE public customers postgres
205; 1259 16391 TABLE DATA public customers postgres
206; 1259 16392 TABLE public orders postgres
207; 1259 16393 TABLE "public" "odd name" postgres
208; 1259 16394 TABLE pg_catalog pg_type postgres
"""


def test_list_keeps_tables_and_skips_catalog_and_data():
    assert pg_restore_table_idents(LISTING) == [
        ("public", "customers"),
        ("public", "orders"),
        ("public", "odd name"),
    ]


def test_drop_quotes_identifiers():
    sql = drop_table_cascade_sql('public', 'odd "name"')
    assert sql == 'DROP TABLE IF EXISTS "public"."odd ""name""" CASCADE'
