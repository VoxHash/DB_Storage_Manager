"""PostgreSQL restore drops archived tables before pg_restore --clean."""

from db_storage_manager.db.postgres import (
    drop_table_cascade_sql,
    filter_pg_restore_list,
    parse_pg_restore_toc_entry,
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


# pg_restore 18 --list of a dump that includes a schema the session cannot
# create in, a public table owned by another role, and an extension the
# session cannot drop. Header trimmed; the entry lines are the real format.
HOSTED_LISTING = """\
;
; Selected TOC Entries:
;
6; 2615 16387 SCHEMA - auth dsm_auth
3424; 0 0 ACL - SCHEMA auth dsm_auth
5; 2615 2200 SCHEMA - public dsm_app
3425; 0 0 ACL - SCHEMA public dsm_app
2; 3079 16414 EXTENSION - pg_trgm 
3482; 0 0 COMMENT - EXTENSION pg_trgm 
216; 1259 16388 TABLE auth audit_log_entries dsm_auth
3426; 0 0 ACL auth TABLE audit_log_entries dsm_auth
217; 1259 16396 TABLE public customers dsm_app
219; 1259 16495 TABLE public owned_by_platform dsm_auth
3484; 0 0 ACL public TABLE owned_by_platform dsm_auth
3416; 0 16388 TABLE DATA auth audit_log_entries dsm_auth
3417; 0 16396 TABLE DATA public customers dsm_app
3473; 0 16495 TABLE DATA public owned_by_platform dsm_auth
3270; 2606 16395 CONSTRAINT auth audit_log_entries audit_log_entries_pkey dsm_auth
3272; 2606 16402 CONSTRAINT public customers customers_pkey dsm_app
3327; 2606 16499 CONSTRAINT public owned_by_platform owned_by_platform_pkey dsm_auth
"""


def test_toc_parser_keeps_table_and_constraint_tags():
    table = parse_pg_restore_toc_entry(
        "216; 1259 16388 TABLE auth audit_log_entries dsm_auth"
    )
    assert table == {
        "description": "TABLE",
        "schema": "auth",
        "tag": ["audit_log_entries"],
    }
    data = parse_pg_restore_toc_entry(
        "3416; 0 16388 TABLE DATA auth audit_log_entries dsm_auth"
    )
    assert data["description"] == "TABLE DATA"
    assert data["schema"] == "auth"
    constraint = parse_pg_restore_toc_entry(
        "3270; 2606 16395 CONSTRAINT auth audit_log_entries "
        "audit_log_entries_pkey dsm_auth"
    )
    assert constraint["tag"] == ["audit_log_entries", "audit_log_entries_pkey"]
    extension = parse_pg_restore_toc_entry("2; 3079 16414 EXTENSION - pg_trgm ")
    assert extension["tag"] == ["pg_trgm"]
    comment = parse_pg_restore_toc_entry(
        "3482; 0 0 COMMENT - EXTENSION pg_trgm "
    )
    assert comment["tag"] == ["EXTENSION", "pg_trgm"]


def test_filter_leaves_owned_tables_and_comments_out_the_rest():
    filtered = filter_pg_restore_list(
        HOSTED_LISTING,
        {"auth"},
        {"public": {"owned_by_platform", "owned_by_platform_pkey"}},
        {"pg_trgm"},
    )
    kept = [
        line
        for line in filtered.splitlines()
        if line.strip() and not line.startswith(";")
    ]
    commented = [line for line in filtered.splitlines() if line.startswith(";")]
    assert any("TABLE public customers " in line for line in kept)
    assert any("TABLE DATA public customers " in line for line in kept)
    assert any("CONSTRAINT public customers " in line for line in kept)
    assert any("SCHEMA - public " in line for line in kept)
    assert any("audit_log_entries" in line for line in commented)
    assert any("owned_by_platform" in line for line in commented)
    assert any("EXTENSION - pg_trgm" in line for line in commented)
    assert any("SCHEMA - auth " in line for line in commented)
    assert filter_pg_restore_list(HOSTED_LISTING, set(), {}, set()) == HOSTED_LISTING
