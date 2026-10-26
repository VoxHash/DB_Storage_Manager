"""Resolve cloud-managed DB credentials from SecureStore / env / .env.cloud.local.

Secrets are never committed. Precedence (highest first):
explicit ``config`` → SecureStore ``cloud_managed`` → environment /
``.env.cloud.local``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import CloudNotConfiguredError

_ENV_FILE_CANDIDATES = (
    Path(".env.cloud.local"),
    Path.home() / ".config" / "db-storage-manager" / ".env.cloud.local",
)


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def load_cloud_dotenv(*, override: bool = False) -> Optional[Path]:
    """Load ``.env.cloud.local`` into the process environment if present.

    Returns the path loaded, or ``None`` if no file / dotenv unavailable.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    for path in _ENV_FILE_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=override)
            return path
    return None


def _stored_cloud(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if settings and isinstance(settings.get("cloud_managed"), dict):
        return dict(settings["cloud_managed"])
    if settings is None:
        try:
            from ..security.store import SecureStore

            return dict(SecureStore().get_settings().get("cloud_managed") or {})
        except Exception:
            return {}
    return {}


def resolve_cloud_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    settings: Optional[Dict[str, Any]] = None,
    load_env_file: bool = True,
) -> Dict[str, Any]:
    """Merge cloud provider settings for AWS RDS, GCP Cloud SQL, and Azure SQL."""
    if load_env_file:
        load_cloud_dotenv()

    stored = _stored_cloud(settings)
    aws_stored = dict(stored.get("aws") or {})
    gcp_stored = dict(stored.get("gcp") or {})
    azure_stored = dict(stored.get("azure") or {})

    explicit = config or {}
    aws_cfg = dict(aws_stored)
    aws_cfg.update(dict(explicit.get("aws") or {}))
    gcp_cfg = dict(gcp_stored)
    gcp_cfg.update(dict(explicit.get("gcp") or {}))
    azure_cfg = dict(azure_stored)
    azure_cfg.update(dict(explicit.get("azure") or {}))

    # AWS — prefer explicit keys, then env / default credential chain
    if not aws_cfg.get("region"):
        aws_cfg["region"] = _env_first(
            "DSM_AWS_REGION", "AWS_DEFAULT_REGION", "AWS_REGION"
        ) or "us-east-1"
    if not aws_cfg.get("access_key_id"):
        aws_cfg["access_key_id"] = _env_first(
            "DSM_AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"
        )
    if not aws_cfg.get("secret_access_key"):
        aws_cfg["secret_access_key"] = _env_first(
            "DSM_AWS_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"
        )
    if not aws_cfg.get("session_token"):
        aws_cfg["session_token"] = _env_first(
            "DSM_AWS_SESSION_TOKEN", "AWS_SESSION_TOKEN"
        )
    if not aws_cfg.get("profile"):
        aws_cfg["profile"] = _env_first("DSM_AWS_PROFILE", "AWS_PROFILE")
    if not aws_cfg.get("ssl_ca_path"):
        aws_cfg["ssl_ca_path"] = _env_first("DSM_AWS_RDS_SSL_CA", "RDS_SSL_CA")

    # GCP
    if not gcp_cfg.get("project_id"):
        gcp_cfg["project_id"] = _env_first(
            "DSM_GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"
        )
    if not gcp_cfg.get("credentials_path"):
        gcp_cfg["credentials_path"] = _env_first(
            "DSM_GCP_CREDENTIALS",
            "GOOGLE_APPLICATION_CREDENTIALS",
        )

    # Azure
    if not azure_cfg.get("subscription_id"):
        azure_cfg["subscription_id"] = _env_first(
            "DSM_AZURE_SUBSCRIPTION_ID", "AZURE_SUBSCRIPTION_ID"
        )
    if not azure_cfg.get("tenant_id"):
        azure_cfg["tenant_id"] = _env_first("DSM_AZURE_TENANT_ID", "AZURE_TENANT_ID")
    if not azure_cfg.get("client_id"):
        azure_cfg["client_id"] = _env_first("DSM_AZURE_CLIENT_ID", "AZURE_CLIENT_ID")
    if not azure_cfg.get("client_secret"):
        azure_cfg["client_secret"] = _env_first(
            "DSM_AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET"
        )

    return {
        "aws": {k: v for k, v in aws_cfg.items() if v is not None and v != ""},
        "gcp": {k: v for k, v in gcp_cfg.items() if v is not None and v != ""},
        "azure": {k: v for k, v in azure_cfg.items() if v is not None and v != ""},
    }


def aws_ready(cfg: Dict[str, Any]) -> bool:
    """True when boto3 can authenticate (keys, profile, or default chain)."""
    aws = cfg.get("aws") or {}
    if aws.get("access_key_id") and aws.get("secret_access_key"):
        return True
    if aws.get("profile"):
        return True
    # Default chain (instance role, ~/.aws/credentials, etc.) may work —
    # treat as ready if region is set; live calls surface auth errors.
    return bool(aws.get("region"))


def gcp_ready(cfg: Dict[str, Any]) -> bool:
    gcp = cfg.get("gcp") or {}
    return bool(gcp.get("project_id"))


def azure_ready(cfg: Dict[str, Any]) -> bool:
    azure = cfg.get("azure") or {}
    return bool(azure.get("subscription_id"))


def require_aws(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not aws_ready(cfg):
        raise CloudNotConfiguredError(
            "AWS RDS is not configured. Set DSM_AWS_REGION (and optional "
            "DSM_AWS_ACCESS_KEY_ID / DSM_AWS_SECRET_ACCESS_KEY or AWS_PROFILE), "
            "or SecureStore settings cloud_managed.aws. "
            "See .env.cloud.local.example."
        )
    return cfg["aws"]


def require_gcp(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not gcp_ready(cfg):
        raise CloudNotConfiguredError(
            "GCP Cloud SQL is not configured. Set DSM_GCP_PROJECT_ID "
            "(and optional GOOGLE_APPLICATION_CREDENTIALS / DSM_GCP_CREDENTIALS), "
            "or SecureStore settings cloud_managed.gcp. "
            "See .env.cloud.local.example."
        )
    return cfg["gcp"]


def require_azure(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not azure_ready(cfg):
        raise CloudNotConfiguredError(
            "Azure SQL is not configured. Set DSM_AZURE_SUBSCRIPTION_ID "
            "(and optional AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET "
            "or use DefaultAzureCredential), or SecureStore settings "
            "cloud_managed.azure. See .env.cloud.local.example."
        )
    return cfg["azure"]


def configuration_status(
    config: Optional[Dict[str, Any]] = None,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """UI-friendly readiness summary (no secrets)."""
    cfg = resolve_cloud_config(config, settings=settings)
    aws = cfg.get("aws") or {}
    gcp = cfg.get("gcp") or {}
    azure = cfg.get("azure") or {}
    return {
        "aws": {
            "ready": aws_ready(cfg),
            "region": aws.get("region"),
            "auth": (
                "keys"
                if aws.get("access_key_id")
                else ("profile" if aws.get("profile") else "default_chain")
            ),
            "ssl_ca_path": aws.get("ssl_ca_path"),
        },
        "gcp": {
            "ready": gcp_ready(cfg),
            "project_id": gcp.get("project_id"),
            "credentials_path": bool(gcp.get("credentials_path")),
        },
        "azure": {
            "ready": azure_ready(cfg),
            "subscription_id": azure.get("subscription_id"),
            "auth": (
                "service_principal"
                if azure.get("client_id") and azure.get("client_secret")
                else "default_credential"
            ),
        },
    }
