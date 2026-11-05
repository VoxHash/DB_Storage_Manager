"""PostgreSQL restore drops archived tables before pg_restore --clean."""

from db_storage_manager.db.postgres import (
    drop_table_cascade_sql,
    filter_pg_restore_list,
    parse_pg_restore_toc_entry,
    pg_restore_errors_tolerated,
    pg_restore_table_idents,
    platform_skip_notice,
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
        "owner": "dsm_auth",
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
    assert extension["owner"] == ""
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


# pg_restore 18 --list of a PostgreSQL 16 dump. The extensions schema is
# visible to the session (it has CREATE there) but the session does not own
# the schema, its event-trigger functions, or the event triggers.
PLATFORM_LISTING = """\
;
; Selected TOC Entries:
;
6; 2615 16387 SCHEMA - extensions dsm_platform
3421; 0 0 ACL - SCHEMA extensions dsm_platform
218; 1255 16388 FUNCTION extensions grant_pg_cron_access() dsm_platform
3422; 0 0 COMMENT extensions FUNCTION grant_pg_cron_access() dsm_platform
3423; 0 0 ACL extensions FUNCTION grant_pg_cron_access() dsm_platform
219; 1255 16389 FUNCTION extensions set_graphql_placeholder() dsm_platform
217; 1255 16392 FUNCTION public app_label() dsm_app
216; 1259 16393 TABLE public customers dsm_app
3414; 0 16393 TABLE DATA public customers dsm_app
3270; 2606 16399 CONSTRAINT public customers customers_pkey dsm_app
3268; 3466 16391 EVENT TRIGGER - issue_graphql_placeholder postgres
3267; 3466 16390 EVENT TRIGGER - issue_pg_cron_access postgres
3425; 0 0 COMMENT - EVENT TRIGGER issue_pg_cron_access postgres
"""


def test_filter_skips_event_triggers_extensions_schema_and_functions():
    event_triggers = {"issue_pg_cron_access", "issue_graphql_placeholder"}
    routines = {
        "extensions": {"grant_pg_cron_access", "set_graphql_placeholder"}
    }
    schema_defs = {"extensions"}
    filtered = filter_pg_restore_list(
        PLATFORM_LISTING,
        set(),
        {},
        set(),
        event_triggers,
        routines,
        schema_defs,
    )
    kept = [
        line
        for line in filtered.splitlines()
        if line.strip() and not line.startswith(";")
    ]
    commented = [line for line in filtered.splitlines() if line.startswith(";")]
    assert any("FUNCTION public app_label()" in line for line in kept)
    assert any("TABLE public customers " in line for line in kept)
    assert any("TABLE DATA public customers " in line for line in kept)
    assert any("CONSTRAINT public customers " in line for line in kept)
    assert any("EVENT TRIGGER - issue_pg_cron_access" in line for line in commented)
    assert any(
        "EVENT TRIGGER - issue_graphql_placeholder" in line for line in commented
    )
    assert any("COMMENT - EVENT TRIGGER issue_pg_cron_access" in line for line in commented)
    assert any("SCHEMA - extensions " in line for line in commented)
    assert any("ACL - SCHEMA extensions " in line for line in commented)
    assert any(
        "FUNCTION extensions grant_pg_cron_access()" in line for line in commented
    )
    assert any(
        "FUNCTION extensions set_graphql_placeholder()" in line for line in commented
    )
    assert any(
        "COMMENT extensions FUNCTION grant_pg_cron_access()" in line
        for line in commented
    )
    notice = platform_skip_notice(
        PLATFORM_LISTING,
        set(),
        {},
        set(),
        event_triggers,
        routines,
        schema_defs,
    )
    assert notice is not None
    assert "issue_graphql_placeholder" in notice
    assert "issue_pg_cron_access" in notice
    assert "schemas extensions" in notice
    assert "extensions.grant_pg_cron_access" in notice
    assert "extensions.set_graphql_placeholder" in notice
    assert "app_label" not in notice
    assert "customers" not in notice


_PLATFORM_STDERR = """\
pg_restore: error: could not execute query: ERROR:  must be owner of event trigger issue_pg_cron_access
Command was: DROP EVENT TRIGGER IF EXISTS issue_pg_cron_access;
pg_restore: error: could not execute query: ERROR:  cannot drop function extensions.grant_pg_cron_access() because other objects depend on it
Command was: DROP FUNCTION extensions.grant_pg_cron_access();
pg_restore: error: could not execute query: ERROR:  cannot drop schema extensions because other objects depend on it
Command was: DROP SCHEMA extensions;
pg_restore: error: could not execute query: ERROR:  schema "extensions" already exists
Command was: CREATE SCHEMA extensions;
pg_restore: error: could not execute query: ERROR:  function "grant_pg_cron_access" already exists with same argument types
Command was: CREATE FUNCTION extensions.grant_pg_cron_access() RETURNS event_trigger LANGUAGE plpgsql AS $$ BEGIN END $$;
"""


def test_platform_object_errors_are_not_a_hard_failure():
    assert pg_restore_errors_tolerated(_PLATFORM_STDERR) is True


# Supabase-style dump: default privileges for supabase_admin, a catalog
# GRANT ... WITH GRANT OPTION, and the table the session owns.
ACL_LISTING = """\
;
; Selected TOC Entries:
;
217; 1255 16392 FUNCTION public app_label() dsm_app
216; 1259 16393 TABLE public customers dsm_app
3414; 0 16393 TABLE DATA public customers dsm_app
5001; 826 16410 DEFAULT ACL public TABLE dsm_app
5002; 826 16411 DEFAULT ACL public SEQUENCE supabase_admin
5003; 826 16412 DEFAULT ACL extensions FUNCTION supabase_admin
5004; 0 0 ACL public TABLE customers dsm_app
5005; 0 0 ACL pg_catalog FUNCTION pg_reload_conf() postgres
"""


def test_filter_skips_foreign_default_acl_and_catalog_grants():
    filtered = filter_pg_restore_list(
        ACL_LISTING,
        set(),
        {},
        set(),
        None,
        None,
        None,
        {"supabase_admin"},
        True,
    )
    kept = [
        line
        for line in filtered.splitlines()
        if line.strip() and not line.startswith(";")
    ]
    commented = [line for line in filtered.splitlines() if line.startswith(";")]
    assert any("TABLE public customers " in line for line in kept)
    assert any("TABLE DATA public customers " in line for line in kept)
    assert any("FUNCTION public app_label()" in line for line in kept)
    assert any("DEFAULT ACL public TABLE dsm_app" in line for line in kept)
    assert any("ACL public TABLE customers " in line for line in kept)
    assert any(
        "DEFAULT ACL public SEQUENCE supabase_admin" in line for line in commented
    )
    assert any(
        "DEFAULT ACL extensions FUNCTION supabase_admin" in line for line in commented
    )
    assert any(
        "ACL pg_catalog FUNCTION pg_reload_conf()" in line for line in commented
    )
    notice = platform_skip_notice(
        ACL_LISTING,
        set(),
        {},
        set(),
        None,
        None,
        None,
        {"supabase_admin"},
        True,
    )
    assert notice is not None
    assert "Skipped ACLs" in notice
    assert "supabase_admin" in notice
    assert "catalog grants" in notice
    assert "customers" not in notice
    assert "app_label" not in notice


_SUPABASE_ACL_STDERR = """\
pg_restore: error: could not execute query: ERROR:  grant options cannot be granted back to your own grantor
Command was: GRANT ALL ON FUNCTION pg_catalog.pg_reload_conf() TO postgres WITH GRANT OPTION;
pg_restore: error: could not execute query: ERROR:  permission denied to change default privileges
Command was: ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA extensions GRANT ALL ON FUNCTIONS TO postgres WITH GRANT OPTION;
pg_restore: error: could not execute query: ERROR:  permission denied to change default privileges
Command was: ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
"""


def test_grant_option_and_default_privilege_errors_do_not_fail_restore():
    assert pg_restore_errors_tolerated(_SUPABASE_ACL_STDERR) is True


def test_table_and_permission_errors_still_fail_the_restore():
    assert (
        pg_restore_errors_tolerated(
            "pg_restore: error: could not execute query: ERROR:  must be owner of table audit_log_entries\n"
            "Command was: DROP TABLE public.audit_log_entries;\n"
        )
        is False
    )
    assert (
        pg_restore_errors_tolerated(
            'pg_restore: error: could not execute query: ERROR:  relation "customers" already exists\n'
            "Command was: CREATE TABLE public.customers (id integer);\n"
        )
        is False
    )
    assert (
        pg_restore_errors_tolerated(
            _PLATFORM_STDERR
            + "pg_restore: error: could not execute query: ERROR:  permission denied for table customers\n"
            "Command was: COPY public.customers (id, name) FROM stdin;\n"
        )
        is False
    )
