"""
Helpers for optional database engine drivers.

Core installs exclude Oracle, SQL Server, ClickHouse, and InfluxDB clients.
Missing drivers raise ImportError with install extras and platform notes.
"""

from __future__ import annotations

from typing import Optional

# Extra name → (PyPI project, pip install hint, short platform note)
OPTIONAL_ENGINES = {
    "oracle": (
        "oracledb",
        'pip install -e ".[oracle]"  # or: pip install oracledb',
        "Thin mode needs no Instant Client (Oracle DB 12.1+). "
        "Thick mode (11g / NNE / AC): install Instant Client and set "
        "ORACLE_CLIENT_LIB_DIR, or call oracledb.init_oracle_client(). "
        "See docs/installation.md.",
    ),
    "mssql": (
        "pyodbc",
        'pip install -e ".[mssql]"  # or: pip install pyodbc',
        "Requires a host ODBC Driver for SQL Server (prefer 18) plus "
        "unixODBC on Linux/macOS. See docs/installation.md.",
    ),
    "clickhouse": (
        "clickhouse-driver",
        'pip install -e ".[clickhouse]"  # or: pip install clickhouse-driver',
        "Pure-Python/wheels; no proprietary client libraries.",
    ),
    "influxdb": (
        "influxdb-client",
        'pip install -e ".[influxdb]"  # or: pip install influxdb-client',
        "InfluxDB 2.x HTTP API client; no native client install.",
    ),
}


def missing_driver_error(engine: str, *, detail: Optional[str] = None) -> ImportError:
    """Build a clear ImportError for a missing optional engine driver."""
    if engine not in OPTIONAL_ENGINES:
        raise ValueError(f"Unknown optional engine: {engine}")
    package, install_hint, note = OPTIONAL_ENGINES[engine]
    parts = [
        f"{package} is required for {engine} support.",
        f"Install with: {install_hint}",
        note,
    ]
    if detail:
        parts.append(detail)
    return ImportError(" ".join(parts))
