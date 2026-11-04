"""Multi-cloud discovery — DigitalOcean, Supabase, Neon, and Aiven.

Extends Discover Cloud with the operator's own tokens. No token is bundled.
Passwords, URIs, and user records from provider payloads are dropped before
a row is returned. A 401 or 403 is ``not_available`` for that provider.

Supabase list-projects does not return a database hostname. The host is the
one Supabase documents for that project ref: ``db.<ref>.supabase.co``, port
5432, database ``postgres``.

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
``license.product_id`` is ``PREMIUM_PRODUCT_IDS["multi-cloud-discovery"]["monthly"]``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "multi-cloud-discovery"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"
PROVIDERS = ("digitalocean", "supabase", "neon", "aiven")

_ENGINE = {
    "pg": "postgresql",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "redis": "redis",
    "valkey": "redis",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "kafka": "kafka",
    "opensearch": "opensearch",
}


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Multi-cloud discovery",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Discover DigitalOcean, Supabase, Neon, and Aiven databases "
            "with the operator's own API token"
        ),
        plugin_type=PluginType.CUSTOM,
        plugin_id=PLUGIN_ID,
    )


def _db_type(engine: Any) -> str:
    return _ENGINE.get(str(engine or "").strip().lower(), str(engine or ""))


def _row(**fields: Any) -> Dict[str, Any]:
    """A Discover Cloud row. Secret-shaped keys are not accepted."""
    allowed = (
        "provider",
        "id",
        "name",
        "engine",
        "db_type",
        "endpoint",
        "host",
        "port",
        "database",
        "status",
        "region",
        "version",
        "host_source",
    )
    return {key: fields.get(key) for key in allowed if fields.get(key) not in (None, "")}


def interpret_digitalocean(payload: Any) -> List[Dict[str, Any]]:
    """DigitalOcean ``GET /v2/databases`` body. Passwords are not copied."""
    items = payload.get("databases") if isinstance(payload, dict) else None
    rows: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        conn = item.get("connection") if isinstance(item.get("connection"), dict) else {}
        names = item.get("db_names") if isinstance(item.get("db_names"), list) else []
        database = conn.get("database") or (names[0] if names else "")
        rows.append(
            _row(
                provider="digitalocean",
                id=item.get("id") or item.get("name"),
                name=item.get("name"),
                engine=item.get("engine"),
                db_type=_db_type(item.get("engine")),
                endpoint=conn.get("host"),
                host=conn.get("host"),
                port=conn.get("port"),
                database=database,
                status=item.get("status"),
                region=item.get("region"),
                version=item.get("version"),
            )
        )
    return rows


def interpret_supabase(payload: Any) -> List[Dict[str, Any]]:
    """Supabase ``GET /v1/projects``. Host is the documented ``db.<ref>`` name."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("projects") or []
    else:
        items = []
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("id") or item.get("ref") or "").strip()
        if not ref or any(ch in ref for ch in "/?# "):
            continue
        host = f"db.{ref}.supabase.co"
        rows.append(
            _row(
                provider="supabase",
                id=ref,
                name=item.get("name"),
                engine="pg",
                db_type="postgresql",
                endpoint=host,
                host=host,
                port=5432,
                database="postgres",
                status=item.get("status"),
                region=item.get("region"),
                host_source="documented supabase db hostname",
            )
        )
    return rows


def interpret_neon(payload: Any, endpoints: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Neon ``GET /v2/projects`` plus optional ``endpoints`` keyed by project id."""
    if isinstance(payload, dict):
        items = payload.get("projects") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    endpoints = endpoints or {}
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("id") or "")
        host = ""
        raw_eps = endpoints.get(project_id)
        ep_items = []
        if isinstance(raw_eps, dict):
            ep_items = raw_eps.get("endpoints") or []
        elif isinstance(raw_eps, list):
            ep_items = raw_eps
        for ep in ep_items:
            if not isinstance(ep, dict) or not ep.get("host"):
                continue
            host = str(ep["host"])
            if ep.get("type") == "read_write":
                break
        rows.append(
            _row(
                provider="neon",
                id=project_id or item.get("name"),
                name=item.get("name"),
                engine="pg",
                db_type="postgresql",
                endpoint=host,
                host=host,
                port=5432,
                database="neondb",
                region=item.get("region_id"),
                version=item.get("pg_version"),
            )
        )
    return rows


def interpret_aiven(payload: Any) -> List[Dict[str, Any]]:
    """Aiven ``GET /v1/project/{project}/service``. Service URIs are not copied."""
    items = payload.get("services") if isinstance(payload, dict) else None
    rows: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        params = item.get("service_uri_params")
        params = params if isinstance(params, dict) else {}
        port = params.get("port")
        try:
            port = int(port) if port not in (None, "") else None
        except (TypeError, ValueError):
            port = None
        rows.append(
            _row(
                provider="aiven",
                id=item.get("service_name"),
                name=item.get("service_name"),
                engine=item.get("service_type"),
                db_type=_db_type(item.get("service_type")),
                endpoint=params.get("host"),
                host=params.get("host"),
                port=port,
                database=params.get("dbname") or params.get("database"),
                status=item.get("state"),
            )
        )
    return rows


def _env_token(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _extra(connection: Any) -> Dict[str, Any]:
    config = getattr(connection, "config", None)
    extra = getattr(config, "extra", None) if config is not None else None
    if extra is None and isinstance(connection, dict):
        extra = connection.get("extra")
    return extra if isinstance(extra, dict) else {}


def _http_json(url: str, headers: Dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PermissionError(
                f"HTTP {exc.code}: not available on this plan or role"
            ) from exc
        raise RuntimeError(f"HTTP {exc.code}") from exc


def _bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def fetch_provider(
    provider: str,
    *,
    connection: Any = None,
    http_get: Optional[Callable[..., Any]] = None,
) -> Any:
    """Call one provider. Raises ``RuntimeError`` when the token is absent."""
    http_get = http_get or _http_json
    extra = _extra(connection)
    if provider == "digitalocean":
        token = _env_token("DSM_DIGITALOCEAN_TOKEN", "DIGITALOCEAN_ACCESS_TOKEN")
        token = token or str(extra.get("digitalocean_token") or "")
        if not token.strip():
            raise RuntimeError("DigitalOcean token is not configured. No token is bundled.")
        return http_get("https://api.digitalocean.com/v2/databases", _bearer(token.strip()))
    if provider == "supabase":
        token = _env_token("DSM_SUPABASE_ACCESS_TOKEN", "SUPABASE_ACCESS_TOKEN")
        token = token or str(extra.get("supabase_access_token") or "")
        if not token.strip():
            raise RuntimeError("Supabase access token is not configured. No token is bundled.")
        return http_get("https://api.supabase.com/v1/projects", _bearer(token.strip()))
    if provider == "neon":
        token = _env_token("DSM_NEON_API_KEY", "NEON_API_KEY")
        token = token or str(extra.get("neon_api_key") or "")
        if not token.strip():
            raise RuntimeError("Neon API key is not configured. No key is bundled.")
        projects = http_get(
            "https://console.neon.tech/api/v2/projects", _bearer(token.strip())
        )
        endpoints: Dict[str, Any] = {}
        items = projects.get("projects") if isinstance(projects, dict) else []
        for item in items or []:
            project_id = str(item.get("id") or "")
            if not project_id or any(ch in project_id for ch in "/?# "):
                continue
            endpoints[project_id] = http_get(
                f"https://console.neon.tech/api/v2/projects/{project_id}/endpoints",
                _bearer(token.strip()),
            )
        return {"projects": projects, "endpoints": endpoints}
    if provider == "aiven":
        token = _env_token("DSM_AIVEN_TOKEN", "AIVEN_API_TOKEN")
        token = token or str(extra.get("aiven_token") or "")
        project = _env_token("DSM_AIVEN_PROJECT") or str(extra.get("aiven_project") or "")
        if not token.strip() or not project.strip():
            raise RuntimeError(
                "Aiven token and project are not configured. No token is bundled."
            )
        if any(ch in project for ch in "/?# "):
            raise RuntimeError("Aiven project name is not a single path token")
        return http_get(
            f"https://api.aiven.io/v1/project/{project.strip()}/service",
            {
                "Authorization": f"aivenv1 {token.strip()}",
                "Accept": "application/json",
            },
        )
    raise RuntimeError(f"Unknown provider {provider}")


def discover(
    *,
    connection: Any = None,
    payloads: Optional[Dict[str, Any]] = None,
    providers: Optional[List[str]] = None,
    http_get: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Discover databases. ``payloads`` skips the network for that provider."""
    wanted = [p for p in (providers or PROVIDERS) if p in PROVIDERS]
    payloads = payloads or {}
    databases: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []
    for provider in wanted:
        try:
            if provider in payloads:
                raw = payloads[provider]
            else:
                raw = fetch_provider(provider, connection=connection, http_get=http_get)
            if provider == "digitalocean":
                databases.extend(interpret_digitalocean(raw))
            elif provider == "supabase":
                databases.extend(interpret_supabase(raw))
            elif provider == "neon":
                if isinstance(raw, dict) and "projects" in raw and "endpoints" in raw:
                    body = raw["projects"]
                    endpoints = raw["endpoints"]
                else:
                    body = raw
                    endpoints = payloads.get("neon_endpoints")
                databases.extend(interpret_neon(body, endpoints))
            elif provider == "aiven":
                databases.extend(interpret_aiven(raw))
        except PermissionError as exc:
            notes.append(
                {"provider": provider, "status": "not_available", "reason": str(exc)}
            )
        except Exception as exc:
            notes.append(
                {
                    "provider": provider,
                    "status": "not_available",
                    "reason": str(exc),
                }
            )
    if databases and notes:
        status = "partial"
    elif databases:
        status = "ok"
    elif notes:
        status = "not_available"
    else:
        status = "ok"
    return {
        "ok": bool(databases) or not notes,
        "status": status,
        "databases": databases,
        "providers": notes,
        "permission": RUN_PERMISSION,
    }


class MultiCloudDiscoveryPlugin(Plugin):
    """Premium plugin: DigitalOcean, Supabase, Neon, Aiven discovery."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, connection: Any = None, **kwargs: Any) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        return discover(
            connection=connection,
            payloads=kwargs.get("payloads"),
            providers=kwargs.get("providers"),
            http_get=kwargs.get("http_get"),
        )

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = MultiCloudDiscoveryPlugin
