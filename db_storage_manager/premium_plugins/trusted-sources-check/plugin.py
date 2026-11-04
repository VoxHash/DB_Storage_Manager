"""Trusted sources — provider allow lists versus this session's client IP.

The client address is ``inet_client_addr()`` on PostgreSQL or the process
list host on MySQL. This check does not call an external IP-echo service.

Empty Neon ``settings.allowed_ips.ips`` means Neon still accepts any address
(Neon documents ``0.0.0.0`` until an allow list is saved). Supabase
``entitlement`` ``disallowed`` means the plan has no network restrictions,
which is ``not_available`` rather than a guess that the database is open.
An empty DigitalOcean firewall rule list is ``partial``: the API did not say
whether that is open or closed. A CIDR of ``0.0.0.0/0`` or ``::/0`` is an
explicit allow-all and is a finding.

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, Iterable, List, Optional, Sequence

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "trusted-sources-check"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"
_OPEN = frozenset({"0.0.0.0/0", "::/0", "0.0.0.0"})


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Trusted sources check",
        version="1.0.0",
        author="VoxHash",
        description="Compare a provider allow list with the IP this database session is using",
        plugin_type=PluginType.PERFORMANCE_MONITORING,
        plugin_id=PLUGIN_ID,
    )


def _engine_name(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    raw = getattr(config, "type", None) if config is not None else None
    if raw is None and isinstance(connection, dict):
        raw = connection.get("type")
    if raw is None:
        return None
    name = str(raw).strip().lower()
    if name in {"postgres", "supabase"}:
        return "postgresql"
    if name in {"mariadb"}:
        return "mysql"
    return name


def _network(value: str) -> Optional[Any]:
    text = str(value or "").strip()
    if not text:
        return None
    if "/" not in text:
        text = f"{text}/32" if ":" not in text else f"{text}/128"
    try:
        return ipaddress.ip_network(text, strict=False)
    except ValueError:
        return None


def _contains(cidrs: Sequence[str], client_ip: str) -> str:
    """``open``, ``match``, ``miss``, or ``unparsed``."""
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return "unparsed"
    saw_network = False
    for raw in cidrs:
        if str(raw).strip() in _OPEN:
            return "open"
        network = _network(str(raw))
        if network is None:
            continue
        saw_network = True
        if address in network:
            if network.prefixlen == 0:
                return "open"
            return "match"
    return "miss" if saw_network else "unparsed"


def _result(provider: str, status: str, reason: str, **extra: Any) -> Dict[str, Any]:
    row = {"provider": provider, "status": status, "reason": reason}
    row.update(extra)
    return row


def interpret_cidrs(
    provider: str,
    cidrs: Optional[Sequence[str]],
    client_ip: str,
    *,
    empty_means: str,
    missing_reason: str,
) -> Dict[str, Any]:
    if cidrs is None:
        return _result(provider, "not_available", missing_reason)
    cleaned = [str(item) for item in cidrs if str(item).strip()]
    if not cleaned:
        if empty_means == "unrestricted":
            return _result(
                provider,
                "fail",
                "The allow list is empty, and this provider treats that as open to any address.",
                matched=False,
            )
        return _result(
            provider,
            "partial",
            "The API returned no IP rules. This check does not guess whether that means open or closed.",
            matched=False,
        )
    kind = _contains(cleaned, client_ip)
    if kind == "open":
        return _result(
            provider,
            "fail",
            "The allow list contains 0.0.0.0/0 or ::/0.",
            matched=True,
        )
    if kind == "match":
        return _result(provider, "ok", "The session IP is inside an allow-list entry.", matched=True)
    if kind == "unparsed":
        return _result(
            provider,
            "partial",
            "Rules were returned but none were IP addresses or CIDRs this check can compare.",
            matched=False,
        )
    return _result(
        provider,
        "fail",
        "The session IP is not inside the allow list.",
        matched=False,
    )


def interpret_digitalocean_firewall(payload: Any, client_ip: str) -> Dict[str, Any]:
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return _result("digitalocean", "not_available", "DigitalOcean firewall rules were not in the response.")
    cidrs = [
        str(rule.get("value"))
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("type") or "") == "ip_addr"
    ]
    if rules and not cidrs:
        return _result(
            "digitalocean",
            "partial",
            "Firewall rules exist but none are ip_addr values, so the session IP was not compared.",
            matched=False,
        )
    return interpret_cidrs(
        "digitalocean",
        cidrs,
        client_ip,
        empty_means="unknown",
        missing_reason="DigitalOcean firewall rules were not in the response.",
    )


def interpret_neon_project(payload: Any, client_ip: str) -> Dict[str, Any]:
    settings = {}
    if isinstance(payload, dict):
        project = payload.get("project") if isinstance(payload.get("project"), dict) else payload
        settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    allowed = settings.get("allowed_ips") if isinstance(settings.get("allowed_ips"), dict) else None
    if allowed is None or "ips" not in allowed:
        return _result("neon", "not_available", "Neon settings.allowed_ips was not in the response.")
    ips = allowed.get("ips")
    if not isinstance(ips, list):
        return _result("neon", "not_available", "Neon allowed_ips.ips was not a list.")
    return interpret_cidrs(
        "neon",
        [str(item) for item in ips],
        client_ip,
        empty_means="unrestricted",
        missing_reason="Neon settings.allowed_ips was not in the response.",
    )


def interpret_supabase_restrictions(payload: Any, client_ip: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _result("supabase", "not_available", "Supabase network restrictions were not an object.")
    if str(payload.get("entitlement") or "").lower() == "disallowed":
        return _result(
            "supabase",
            "not_available",
            "Network restrictions are not available on this Supabase plan.",
        )
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    v4 = config.get("dbAllowedCidrs")
    v6 = config.get("dbAllowedCidrsV6")
    if not isinstance(v4, list) and not isinstance(v6, list):
        return _result("supabase", "not_available", "Supabase dbAllowedCidrs was not in the response.")
    cidrs = list(v4 or []) + list(v6 or [])
    return interpret_cidrs(
        "supabase",
        [str(item) for item in cidrs],
        client_ip,
        empty_means="unrestricted",
        missing_reason="Supabase dbAllowedCidrs was not in the response.",
    )


def interpret_aiven_service(payload: Any, client_ip: str) -> Dict[str, Any]:
    service = payload
    if isinstance(payload, dict) and isinstance(payload.get("service"), dict):
        service = payload["service"]
    user_config = service.get("user_config") if isinstance(service, dict) else None
    if not isinstance(user_config, dict) or "ip_filter" not in user_config:
        return _result("aiven", "not_available", "Aiven user_config.ip_filter was not in the response.")
    raw = user_config.get("ip_filter")
    if isinstance(raw, str):
        cidrs = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        cidrs = []
        for item in raw:
            if isinstance(item, str):
                cidrs.append(item)
            elif isinstance(item, dict) and item.get("network"):
                cidrs.append(str(item["network"]))
    else:
        return _result("aiven", "not_available", "Aiven ip_filter was not a list or a string.")
    return interpret_cidrs(
        "aiven",
        cidrs,
        client_ip,
        empty_means="unrestricted",
        missing_reason="Aiven user_config.ip_filter was not in the response.",
    )


def interpret_aws_ranges(payload: Any, client_ip: str) -> Dict[str, Any]:
    ranges = None
    if isinstance(payload, dict):
        ranges = payload.get("IPRanges") or payload.get("IpRanges")
    if not isinstance(ranges, list):
        return _result("aws", "not_available", "RDS IPRanges were not in the response.")
    cidrs = []
    for item in ranges:
        if isinstance(item, dict) and item.get("CIDRIP"):
            cidrs.append(str(item["CIDRIP"]))
        elif isinstance(item, str):
            cidrs.append(item)
    return interpret_cidrs(
        "aws",
        cidrs,
        client_ip,
        empty_means="unknown",
        missing_reason="RDS IPRanges were not in the response.",
    )


def summarize(checks: Iterable[Dict[str, Any]], client_ip: Optional[str]) -> Dict[str, Any]:
    rows = list(checks)
    if not client_ip:
        return {
            "ok": False,
            "status": "partial",
            "client_ip": None,
            "checks": rows,
            "reason": "This session has no client IP. Connect over TCP or pass client_ip.",
            "permission": RUN_PERMISSION,
        }
    statuses = {row.get("status") for row in rows}
    if not rows:
        status = "partial"
        reason = "No provider allow list was supplied, so nothing was compared."
    elif statuses <= {"ok"}:
        status = "ok"
        reason = "The session IP is allowed."
    elif "fail" in statuses:
        status = "fail"
        reason = "At least one allow list does not contain the session IP, or it allows every address."
    elif statuses <= {"not_available"}:
        status = "not_available"
        reason = "The allow list could not be read."
    else:
        status = "partial"
        reason = "Some providers could be compared and some could not."
    return {
        "ok": status == "ok",
        "status": status,
        "client_ip": client_ip,
        "checks": rows,
        "reason": reason,
        "permission": RUN_PERMISSION,
    }


class TrustedSourcesPlugin(Plugin):
    """Premium plugin: allow list versus the session IP."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, connection: Any = None, **kwargs: Any) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        client_ip = kwargs.get("client_ip")
        if client_ip is None and connection is not None:
            client_ip = _read_client_ip(connection, _engine_name(connection))
        if isinstance(client_ip, str):
            client_ip = client_ip.strip() or None
        payloads = kwargs.get("payloads") or {}
        checks: List[Dict[str, Any]] = []
        if "digitalocean" in payloads:
            checks.append(interpret_digitalocean_firewall(payloads["digitalocean"], client_ip or ""))
        if "neon" in payloads:
            checks.append(interpret_neon_project(payloads["neon"], client_ip or ""))
        if "supabase" in payloads:
            checks.append(interpret_supabase_restrictions(payloads["supabase"], client_ip or ""))
        if "aiven" in payloads:
            checks.append(interpret_aiven_service(payloads["aiven"], client_ip or ""))
        if "aws" in payloads:
            checks.append(interpret_aws_ranges(payloads["aws"], client_ip or ""))
        if not payloads and connection is None and not client_ip:
            return {
                "ok": False,
                "status": "not_available",
                "reason": "A connection or a recorded provider payload is required.",
                "permission": RUN_PERMISSION,
            }
        report = summarize(checks, client_ip if client_ip else None)
        report["engine"] = _engine_name(connection)
        return report

    def cleanup(self) -> None:
        self._context = {}


def _read_client_ip(connection: Any, engine: Optional[str]) -> Optional[str]:
    if engine == "postgresql":
        sql = "SELECT host(inet_client_addr()) AS client_ip"
    elif engine == "mysql":
        sql = (
            "SELECT SUBSTRING_INDEX(HOST, ':', 1) AS client_ip "
            "FROM information_schema.processlist WHERE ID = CONNECTION_ID()"
        )
    else:
        return None
    raw = getattr(connection, "connection", None)
    if raw is None:
        return None
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
    except Exception:
        return None
    finally:
        cursor.close()
    if not row:
        return None
    value = row[0] if not isinstance(row, dict) else row.get("client_ip")
    if value in (None, "", "localhost"):
        return None
    text = str(value)
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


PLUGIN_CLASS = TrustedSourcesPlugin
