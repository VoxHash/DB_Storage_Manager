"""Map cloud engine identifiers to ConnectionConfig.type values."""

from __future__ import annotations

from typing import Optional

# RDS Engine → app type
_RDS_ENGINE_MAP = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "aurora-postgresql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "aurora": "mysql",
    "aurora-mysql": "mysql",
    "sqlserver-ee": "sqlserver",
    "sqlserver-se": "sqlserver",
    "sqlserver-ex": "sqlserver",
    "sqlserver-web": "sqlserver",
    "oracle-ee": "oracle",
    "oracle-se2": "oracle",
    "oracle-se2-cdb": "oracle",
    "oracle-ee-cdb": "oracle",
}

_DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "sqlserver": 1433,
    "oracle": 1521,
}


def map_rds_engine(engine: Optional[str]) -> Optional[str]:
    if not engine:
        return None
    return _RDS_ENGINE_MAP.get(engine.lower().strip())


def map_cloudsql_version(database_version: Optional[str]) -> Optional[str]:
    """Map Cloud SQL databaseVersion (e.g. POSTGRES_15) to app type."""
    if not database_version:
        return None
    upper = database_version.upper()
    if upper.startswith("POSTGRES"):
        return "postgresql"
    if upper.startswith("MYSQL"):
        return "mysql"
    if upper.startswith("SQLSERVER"):
        return "sqlserver"
    return None


def default_port_for(db_type: Optional[str]) -> Optional[int]:
    if not db_type:
        return None
    return _DEFAULT_PORTS.get(db_type.lower())


def ssl_guidance(provider: str, db_type: Optional[str] = None) -> str:
    """Human-readable SSL / IAM guidance for operators (docs + UI)."""
    provider = (provider or "").lower()
    if provider in ("aws", "aws_rds", "rds"):
        return (
            "RDS requires TLS for IAM auth. Download the AWS RDS global CA bundle "
            "(https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem), "
            "set DSM_AWS_RDS_SSL_CA / extra.ssl_ca_path, and use sslmode=verify-full "
            "(PostgreSQL) or ssl.verify_identity (MySQL). IAM tokens from "
            "generate_db_auth_token expire in ~15 minutes."
        )
    if provider in ("gcp", "gcp_cloudsql", "cloudsql"):
        return (
            "Prefer the Cloud SQL Auth Proxy or cloud-sql-python-connector "
            "(pip install -e \".[gcp]\") so TLS is handled for you. For public IP, "
            "enable SSL in instance settings, allow your client IP, and pass "
            "server CA / client certs via extra.ssl_*. IAM DB auth needs the "
            "Cloud SQL Client role and instance-level IAM flags."
        )
    if provider in ("azure", "azure_sql"):
        return (
            "Azure SQL requires Encrypt=yes (ODBC Driver 18). Prefer Microsoft Entra "
            "access tokens (DefaultAzureCredential / service principal) via "
            "extra.auth_mode=entra_token; scope https://database.windows.net/.default. "
            "SQL authentication still needs a password stored only in connections.enc."
        )
    return "Use TLS for managed cloud databases; prefer IAM/Entra tokens over long-lived passwords."
