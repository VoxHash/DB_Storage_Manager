"""
MySQL/MariaDB database connection
"""

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import pymysql
from pymysql.cursors import DictCursor

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)

# Prefer MariaDB names first: invoking the binary as "mysqldump" on MariaDB 11+
# prints a deprecation warning and can fail the backup with a non-zero exit.
_DUMP_CLIENT_CANDIDATES = ("mariadb-dump", "mysqldump")
_CLIENT_CANDIDATES = ("mariadb", "mysql")
_ARCH_CLIENTS_HINT = (
    "Install MariaDB/MySQL client tools "
    "(Arch/Garuda: sudo pacman -S --needed mariadb-clients libedit) "
    "and ensure mariadb-dump or mysqldump is on PATH. "
    "A user-local mariadb binary that cannot load libedit.so.2 is skipped; "
    "a working mysql client on PATH is used instead."
)

# Dynamic linker failures. The binary is on PATH but cannot run; do not
# bundle a copy of the missing library into the app.
_LOADER_MARKERS = (
    "error while loading shared libraries",
    "cannot open shared object file",
)


def _loader_failure_text(text: str) -> Optional[str]:
    """The linker line when ``text`` says a shared library could not be loaded."""
    lowered = text.lower()
    if not any(marker in lowered for marker in _LOADER_MARKERS):
        return None
    for line in text.splitlines():
        if any(marker in line.lower() for marker in _LOADER_MARKERS):
            return line.strip()[:500]
    return text.strip()[:500]


def _cli_starts(path: str) -> tuple[bool, str]:
    """True when ``path --version`` actually starts.

    A MariaDB client built against a missing ``libedit.so.2`` is on PATH and
    still exits before it can read a dump. That binary is not usable.
    """
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    broken = _loader_failure_text(detail)
    if broken:
        return False, broken
    return True, ""


def resolve_mysql_cli(candidates: Sequence[str] = _DUMP_CLIENT_CANDIDATES) -> Optional[str]:
    """Return the first dump/client binary that starts, or None.

    Names earlier in ``candidates`` win. A binary that cannot load its
    shared libraries is skipped so the next name (``mysql`` after a broken
    ``mariadb``) can be used.
    """
    for name in candidates:
        path = shutil.which(name)
        if path and _cli_starts(path)[0]:
            return path
    return None


def _mysql_client_start_problems(candidates: Sequence[str]) -> List[str]:
    """Binaries that were found but cannot start. Empty when none are on PATH."""
    problems: List[str] = []
    found = False
    for name in candidates:
        path = shutil.which(name)
        if not path:
            continue
        found = True
        ok, detail = _cli_starts(path)
        if not ok:
            problems.append(f"{name} ({path}): {detail}")
    if not found:
        return []
    return problems


def require_mysql_cli(
    candidates: Sequence[str] = _DUMP_CLIENT_CANDIDATES,
    *,
    purpose: str = "backup",
) -> str:
    """Resolve a MySQL/MariaDB CLI tool or raise with an install hint."""
    path = resolve_mysql_cli(candidates)
    if path:
        return path
    problems = _mysql_client_start_problems(candidates)
    if problems:
        raise RuntimeError(
            "MySQL/MariaDB client cannot start "
            f"(required for {purpose}). " + " ".join(problems) + " " + _ARCH_CLIENTS_HINT
        )
    names = " or ".join(candidates)
    raise FileNotFoundError(
        f"{names} not found on PATH (required for MySQL/MariaDB {purpose}). "
        f"{_ARCH_CLIENTS_HINT}"
    )


class MySQLConnection(DatabaseConnection):
    """MySQL/MariaDB database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None

    async def connect(self) -> None:
        """Connect to MySQL database"""
        from ..cloud.connect_auth import resolve_password_and_ssl

        password, ssl_kwargs = resolve_password_and_ssl(self.config)
        connect_kwargs = {
            "host": self.config.host or "localhost",
            "port": self.config.port or 3306,
            "database": self.config.database,
            "user": self.config.username,
            "password": password if password is not None else self.config.password,
        }
        # RDS IAM auth requires the cleartext plugin (AWS docs)
        extra = self.config.extra or {}
        if (extra.get("auth_mode") or "").lower() == "iam":
            connect_kwargs["auth_plugin_map"] = {"mysql_clear_password": None}
        ssl_ca = ssl_kwargs.get("ssl_ca") or ssl_kwargs.get("sslrootcert")
        if ssl_ca:
            connect_kwargs["ssl"] = {
                "ca": ssl_ca,
                "check_hostname": True,
            }
        self.connection = pymysql.connect(**connect_kwargs)
        self.connected = True

    async def _ensure_alive(self) -> None:
        """Connect, or transparently re-connect a dropped session.

        pymysql keeps ``self.connection`` set after the socket dies (idle
        timeout, SSH tunnel blip, server restart). Every later call then raises
        ``InterfaceError (0, '')`` and monitoring reported a permanent false
        critical. ``ping(reconnect=True)`` revives the socket; if that fails we
        rebuild the session from the stored config (fresh IAM token / tunnel).
        """
        if self.connection is None:
            await self.connect()
            return
        try:
            self.connection.ping(reconnect=True)
        except Exception:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.connected = False
            await self.connect()

    async def disconnect(self) -> None:
        """Disconnect from MySQL database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze MySQL/MariaDB storage via information_schema.

        Table sizes use ``TABLES.DATA_LENGTH`` / ``INDEX_LENGTH``. Index listing
        uses ``STATISTICS`` only (that view has no ``index_length`` column).
        """
        await self._ensure_alive()

        cursor = self.connection.cursor(DictCursor)

        # BASE TABLE only — skip views. Uppercase info_schema identifiers are
        # portable across MySQL and MariaDB; aliases normalize DictCursor keys.
        cursor.execute(
            """
            SELECT
                TABLE_SCHEMA AS table_schema,
                TABLE_NAME AS table_name,
                COALESCE(DATA_LENGTH, 0) + COALESCE(INDEX_LENGTH, 0) AS total_size,
                COALESCE(DATA_LENGTH, 0) AS table_size,
                COALESCE(INDEX_LENGTH, 0) AS index_size,
                COALESCE(TABLE_ROWS, 0) AS row_count
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY total_size DESC
            """,
            (self.config.database,),
        )

        tables = []
        total_size = 0
        table_index_sizes: Dict[str, int] = {}
        for row in cursor.fetchall():
            schema = row["table_schema"]
            name = row["table_name"]
            table_size = int(row["table_size"] or 0)
            index_size = int(row["index_size"] or 0)
            row_count = int(row["row_count"] or 0)
            relation_total = int(row["total_size"] or 0)
            table_index_sizes[str(name)] = index_size

            tables.append(
                {
                    "name": f"{schema}.{name}",
                    "size": table_size,
                    "rowCount": row_count,
                    "indexSize": index_size,
                    "bloat": 0.0,
                }
            )
            total_size += relation_total

        # STATISTICS has no INDEX_LENGTH — list indexes and attribute the
        # table-level INDEX_LENGTH to PRIMARY (or first index) for display.
        cursor.execute(
            """
            SELECT
                INDEX_NAME AS index_name,
                TABLE_NAME AS table_name,
                MIN(SEQ_IN_INDEX) AS seq_in_index
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
            GROUP BY INDEX_NAME, TABLE_NAME
            ORDER BY TABLE_NAME, seq_in_index, INDEX_NAME
            """,
            (self.config.database,),
        )

        indexes = []
        claimed_tables: set = set()
        for row in cursor.fetchall():
            table_name = row["table_name"]
            index_name = row["index_name"]
            if table_name not in claimed_tables:
                size = int(table_index_sizes.get(str(table_name), 0))
                claimed_tables.add(table_name)
            else:
                size = 0
            indexes.append(
                {
                    "name": index_name,
                    "tableName": table_name,
                    "size": size,
                    "bloat": 0.0,
                }
            )

        largest_table = (
            tables[0] if tables else {"name": "N/A", "size": 0, "rowCount": 0}
        )

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": len(indexes),
            "largestTable": largest_table,
            "tables": tables,
            "indexes": indexes,
            "lastAnalyzed": __import__("datetime").datetime.now().isoformat(),
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute a MySQL query"""
        await self._ensure_alive()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        cursor = self.connection.cursor(DictCursor)
        import time

        start_time = time.time()

        try:
            cursor.execute(query)
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                columns = ["affected_rows"]
                rows = [{"affected_rows": cursor.rowcount}]

            execution_time = int((time.time() - start_time) * 1000)

            # Get explain plan for SELECT queries
            explain_plan = None
            if query.strip().upper().startswith("SELECT"):
                try:
                    cursor.execute(f"EXPLAIN {query}")
                    explain_plan = [dict(row) for row in cursor.fetchall()]
                except Exception:
                    pass

            return {
                "columns": columns,
                "rows": rows,
                "rowCount": len(rows),
                "executionTime": execution_time,
                "explainPlan": explain_plan,
            }
        finally:
            cursor.close()

    async def get_schema(self) -> SchemaInfo:
        """Get MySQL schema"""
        await self._ensure_alive()

        cursor = self.connection.cursor(DictCursor)

        # Get tables
        cursor.execute(
            """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """,
            (self.config.database,),
        )

        tables = []
        for table_row in cursor.fetchall():
            table_name = table_row["table_name"]

            # Get columns
            cursor.execute(
                """
                SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """,
                (self.config.database, table_name),
            )

            columns = []
            for col in cursor.fetchall():
                columns.append(
                    {
                        "name": col["column_name"],
                        "type": col["data_type"],
                        "nullable": col["is_nullable"] == "YES",
                        "defaultValue": col["column_default"],
                    }
                )

            # Get indexes
            cursor.execute(
                """
                SELECT 
                    index_name,
                    non_unique,
                    column_name
                FROM information_schema.statistics
                WHERE table_schema = %s AND table_name = %s
            """,
                (self.config.database, table_name),
            )

            indexes_dict = {}
            for idx in cursor.fetchall():
                idx_name = idx["index_name"]
                if idx_name not in indexes_dict:
                    indexes_dict[idx_name] = {
                        "name": idx_name,
                        "columns": [],
                        "unique": idx["non_unique"] == 0,
                    }
                indexes_dict[idx_name]["columns"].append(idx["column_name"])

            indexes = list(indexes_dict.values())

            tables.append(
                {
                    "name": table_name,
                    "columns": columns,
                    "indexes": indexes,
                }
            )

        return {
            "schemas": [
                {
                    "name": self.config.database or "default",
                    "tables": tables,
                }
            ]
        }

    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create MySQL backup using mysqldump or mariadb-dump"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        dump_bin = require_mysql_cli(_DUMP_CLIENT_CANDIDATES, purpose="backup")
        cmd = [
            dump_bin,
            f"--host={self.config.host or 'localhost'}",
            f"--port={self.config.port or 3306}",
            f"--user={self.config.username}",
            f"--password={self.config.password}",
            self.config.database,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{dump_bin} disappeared from PATH during backup. {_ARCH_CLIENTS_HINT}"
            ) from exc

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"{Path(dump_bin).name} failed: {stderr.decode()}")

        backup_file.write_bytes(stdout)
        size = backup_file.stat().st_size
        return {"path": str(backup_file), "size": size}

    async def restore_backup(self, backup_path: str) -> None:
        """Restore MySQL backup"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        backup_data = backup_file.read_bytes()

        failures: List[str] = []
        tried: set[str] = set()
        for name in _CLIENT_CANDIDATES:
            client_bin = shutil.which(name)
            if not client_bin or client_bin in tried:
                continue
            tried.add(client_bin)
            ok, detail = _cli_starts(client_bin)
            if not ok:
                failures.append(f"{name} ({client_bin}): {detail}")
                continue
            cmd = [
                client_bin,
                f"--host={self.config.host or 'localhost'}",
                f"--port={self.config.port or 3306}",
                f"--user={self.config.username}",
                f"--password={self.config.password}",
                self.config.database,
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                failures.append(f"{name} ({client_bin}): {exc}")
                continue

            _stdout, stderr = await process.communicate(input=backup_data)
            if process.returncode == 0:
                return
            text = stderr.decode(errors="replace")
            broken = _loader_failure_text(text)
            if broken:
                failures.append(f"{name} ({client_bin}): {broken}")
                continue
            raise RuntimeError(f"{Path(client_bin).name} restore failed: {text}")

        if not tried:
            names = " or ".join(_CLIENT_CANDIDATES)
            raise FileNotFoundError(
                f"{names} not found on PATH (required for MySQL/MariaDB restore). "
                f"{_ARCH_CLIENTS_HINT}"
            )
        raise RuntimeError(
            "MySQL/MariaDB restore failed. "
            + " ".join(failures)
            + " "
            + _ARCH_CLIENTS_HINT
        )
