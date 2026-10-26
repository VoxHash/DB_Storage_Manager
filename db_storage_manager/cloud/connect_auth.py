"""Apply cloud IAM / Entra auth and SSL extras onto SQL driver connect params."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..db.base import ConnectionConfig
from .errors import CloudNotConfiguredError, CloudProviderError


def _extra(config: ConnectionConfig) -> Dict[str, Any]:
    return dict(config.extra or {})


def cloud_auth_mode(config: ConnectionConfig) -> Optional[str]:
    extra = _extra(config)
    mode = (extra.get("auth_mode") or "").strip().lower()
    return mode or None


def cloud_provider(config: ConnectionConfig) -> Optional[str]:
    extra = _extra(config)
    return (extra.get("cloud_provider") or "").strip().lower() or None


def resolve_password_and_ssl(
    config: ConnectionConfig,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Return (password, ssl_kwargs) after applying cloud auth when configured.

    - ``auth_mode=iam`` + ``cloud_provider=aws_rds`` → RDS IAM token as password
    - ``auth_mode=entra_token`` + Azure → password unused; ssl_kwargs carry
      ``odbc_attrs_before`` for pyodbc
    - SSL paths / sslmode from ``extra`` always forwarded when present
    """
    extra = _extra(config)
    password = config.password
    ssl_kwargs: Dict[str, Any] = {}

    ssl_ca = extra.get("ssl_ca_path") or extra.get("sslrootcert")
    sslmode = extra.get("sslmode")
    if ssl_ca:
        ssl_kwargs["sslrootcert"] = ssl_ca
        ssl_kwargs["ssl_ca"] = ssl_ca
    if sslmode:
        ssl_kwargs["sslmode"] = sslmode

    mode = cloud_auth_mode(config)
    provider = cloud_provider(config)

    if mode == "iam" and provider in ("aws_rds", "aws", "rds"):
        from .aws import AWSRDSProvider

        region = extra.get("aws_region")
        provider_obj = AWSRDSProvider(
            region=region or "us-east-1",
            ssl_ca_path=ssl_ca,
            config={"region": region} if region else None,
        )
        if not config.host or not config.username:
            raise CloudNotConfiguredError(
                "RDS IAM auth requires host and username on the connection profile."
            )
        password = provider_obj.generate_iam_auth_token(
            config.host,
            int(config.port or 5432),
            config.username,
            region=region,
        )
        if "sslmode" not in ssl_kwargs and (config.type or "").lower() in (
            "postgresql",
            "postgres",
        ):
            ssl_kwargs["sslmode"] = "verify-full" if ssl_ca else "require"
        return password, ssl_kwargs

    if mode in ("entra_token", "aad", "iam") and provider in (
        "azure_sql",
        "azure",
    ):
        from .azure import AzureDatabaseProvider, SQL_COPT_SS_ACCESS_TOKEN

        azure = AzureDatabaseProvider(
            config={
                "subscription_id": extra.get("subscription_id"),
                "tenant_id": extra.get("tenant_id"),
                "client_id": extra.get("client_id"),
                "client_secret": extra.get("client_secret"),
            }
        )
        try:
            token_struct = azure.get_odbc_access_token_struct()
        except Exception as e:
            raise CloudProviderError(str(e)) from e
        ssl_kwargs["odbc_attrs_before"] = {SQL_COPT_SS_ACCESS_TOKEN: token_struct}
        ssl_kwargs["encrypt"] = extra.get("encrypt") or "yes"
        ssl_kwargs["trust_server_certificate"] = (
            extra.get("trust_server_certificate") or "no"
        )
        # Password unused with access token
        return None, ssl_kwargs

    if mode == "iam" and provider in ("gcp_cloudsql", "gcp", "cloudsql"):
        # IAM DB auth for Cloud SQL typically needs the Auth Proxy / connector.
        # Surface a clear error rather than silently using a stale password.
        raise CloudNotConfiguredError(
            "GCP Cloud SQL IAM DB authentication requires the Cloud SQL Auth "
            "Proxy or cloud-sql-python-connector (pip install -e \".[gcp]\"). "
            "For public IP + password auth, set extra.auth_mode=password and "
            "store the DB user password in the connection profile. "
            f"Instance connection name: {extra.get('connection_name') or 'unknown'}."
        )

    return password, ssl_kwargs
