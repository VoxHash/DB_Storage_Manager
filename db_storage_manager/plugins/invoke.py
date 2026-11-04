"""Build and run a plugin execution from the Plugins page.

The plan names saved connection ids and plain arguments. ``execute_plan``
opens those connections with the real adapters, calls ``execute``, and
disconnects. A missing licence, a disabled plugin, or a missing role is
``not_available``. ``multi-cloud-discovery`` stays on Connections → Discover
Cloud and is not called from here. No credentials are bundled.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from ..security.auth import PermissionDenied
from .licensing import PluginLicenseError
from .live_tables import (
    config_secrets,
    connection_from_profile,
    public_error,
    scrub,
)
from .sdk import not_available

MULTI_CLOUD_ID = "multi-cloud-discovery"


@dataclass(frozen=True)
class Slot:
    """One connection argument of ``execute``."""

    kwarg: str
    required: bool = True


@dataclass(frozen=True)
class RunSpec:
    """Which fields the Run dialog shows for one plugin."""

    slots: tuple = ()
    table: bool = False
    tables: bool = False
    replace: bool = False
    dest: bool = False
    passphrase: bool = False
    export_format: bool = False
    redact: bool = False
    retention_days: bool = False
    message: bool = False
    discover_cloud: bool = False


@dataclass
class RunPlan:
    """Arguments for one Run click. ``blocked`` skips opening any connection."""

    plugin_id: str
    connection_ids: Dict[str, str] = field(default_factory=dict)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    blocked: str = ""


_GENERIC = RunSpec(slots=(Slot("connection", required=False),), message=True)

SPECS: Dict[str, RunSpec] = {
    "migration": RunSpec(
        slots=(Slot("source_db"), Slot("target_db")),
        tables=True,
        replace=True,
    ),
    "data_comparison": RunSpec(
        slots=(Slot("db1"), Slot("db2")),
        table=True,
    ),
    "schema-drift": RunSpec(
        slots=(Slot("connection"), Slot("other", required=False)),
    ),
    "pooler-health": RunSpec(
        slots=(Slot("connection"), Slot("pooled", required=False)),
    ),
    "encrypted-export": RunSpec(
        slots=(Slot("connection"),),
        table=True,
        dest=True,
        passphrase=True,
        export_format=True,
        redact=True,
    ),
    "pitr-verify": RunSpec(
        slots=(Slot("connection"),),
        retention_days=True,
    ),
    "rls-audit": RunSpec(slots=(Slot("connection"),)),
    "extension-inventory": RunSpec(slots=(Slot("connection"),)),
    "trusted-sources-check": RunSpec(slots=(Slot("connection"),)),
    "maintenance-window-watch": RunSpec(slots=(Slot("connection"),)),
}


def run_spec(plugin_id: str) -> RunSpec:
    """Dialog fields for ``plugin_id``."""
    if plugin_id == MULTI_CLOUD_ID:
        return RunSpec(discover_cloud=True)
    return SPECS.get(plugin_id, _GENERIC)


def plan_run(plugin_id: str, form: Mapping[str, Any]) -> RunPlan:
    """Turn dialog fields into a plan. Does not open a connection."""
    if plugin_id == MULTI_CLOUD_ID:
        return RunPlan(
            plugin_id=plugin_id,
            blocked=(
                "multi-cloud-discovery runs from Connections → Discover Cloud "
                "after it is installed and licensed. This Run dialog does not "
                "call provider APIs and does not bundle credentials."
            ),
        )
    spec = SPECS.get(plugin_id, _GENERIC)
    source_id = str(form.get("source_id") or "")
    target_id = str(form.get("target_id") or "")
    chosen = (source_id, target_id)
    connection_ids: Dict[str, str] = {}
    for index, slot in enumerate(spec.slots):
        picked = chosen[index] if index < len(chosen) else ""
        if slot.required and not picked:
            which = "connection" if index == 0 else "second connection"
            return RunPlan(
                plugin_id=plugin_id,
                blocked=f"Select a saved {which}.",
            )
        if picked:
            connection_ids[slot.kwarg] = picked
    if plugin_id == "migration" and source_id and source_id == target_id:
        return RunPlan(
            plugin_id=plugin_id,
            blocked="Source and target must be different saved connections.",
        )
    kwargs: Dict[str, Any] = {}
    if spec.table:
        table = str(form.get("table") or "").strip()
        if not table:
            return RunPlan(
                plugin_id=plugin_id, blocked="A table name is required."
            )
        kwargs["table"] = table
    if spec.tables:
        raw_tables = str(form.get("tables") or "").strip()
        if raw_tables:
            kwargs["tables"] = [
                part.strip() for part in raw_tables.split(",") if part.strip()
            ]
    if spec.replace:
        kwargs["replace"] = bool(form.get("replace"))
        kwargs["confirm"] = str(form.get("confirm") or "")
    if spec.dest:
        dest = str(form.get("dest") or "").strip()
        if not dest:
            return RunPlan(
                plugin_id=plugin_id,
                blocked="A destination path is required.",
            )
        kwargs["dest"] = dest
    if spec.passphrase:
        passphrase = str(form.get("passphrase") or "")
        if not passphrase:
            return RunPlan(
                plugin_id=plugin_id, blocked="A passphrase is required."
            )
        kwargs["passphrase"] = passphrase
    if spec.export_format:
        kwargs["format"] = str(form.get("export_format") or "csv")
    if spec.redact:
        raw_redact = str(form.get("redact") or "").strip()
        if raw_redact:
            kwargs["redact"] = [
                part.strip() for part in raw_redact.split(",") if part.strip()
            ]
    if spec.retention_days:
        raw_days = str(form.get("retention_days") or "").strip()
        if raw_days:
            try:
                kwargs["expected_retention_days"] = int(raw_days)
            except ValueError:
                return RunPlan(
                    plugin_id=plugin_id,
                    blocked="Retention days must be a whole number.",
                )
    if spec.message:
        message = str(form.get("message") or "").strip()
        if message:
            kwargs["message"] = message
    return RunPlan(
        plugin_id=plugin_id,
        connection_ids=connection_ids,
        kwargs=kwargs,
    )


def format_plugin_result(result: Any) -> str:
    """Pretty JSON for the Run dialog, with secrets removed."""
    if not isinstance(result, dict):
        result = {"ok": True, "status": "success", "result": result}
    return json.dumps(scrub(result), indent=2, sort_keys=True, default=str)


def execute_plan(
    marketplace: Any,
    plan: RunPlan,
    profiles: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Open the planned connections, call ``execute``, then disconnect."""
    if plan.blocked:
        return scrub(not_available(plan.blocked))
    status = marketplace.license_status(plan.plugin_id, network=False)
    if not status.allowed:
        reason = status.message or f"License {status.state}"
        return scrub(not_available(reason))
    if not marketplace.is_enabled(plan.plugin_id):
        return scrub(not_available("Plugin is disabled"))
    if marketplace.manager.get_plugin(plan.plugin_id) is None:
        marketplace.load_into_manager(only_enabled=False)
    if marketplace.manager.get_plugin(plan.plugin_id) is None:
        return scrub(not_available("Plugin is not loaded"))

    by_id = {
        str(profile.get("id")): profile
        for profile in profiles
        if profile.get("id")
    }
    opened: List[Any] = []
    secrets: List[str] = []
    kwargs = dict(plan.kwargs)
    try:
        for arg, connection_id in plan.connection_ids.items():
            profile = by_id.get(connection_id)
            if profile is None:
                return scrub(not_available("Saved connection was not found"))
            secrets.extend(config_secrets(profile))
            db = connection_from_profile(dict(profile))
            kwargs[arg] = db
            opened.append(db)
        try:
            result = marketplace.manager.execute_plugin(
                plan.plugin_id, **kwargs
            )
        except PluginLicenseError as exc:
            result = not_available(public_error(exc, secrets))
        except PermissionDenied as exc:
            result = not_available(str(exc))
        except Exception as exc:
            result = not_available(public_error(exc, secrets))
    except Exception as exc:
        result = not_available(public_error(exc, secrets))
    finally:
        _disconnect(opened)
    if result is None:
        result = not_available("Plugin is disabled or not loaded")
    if not isinstance(result, dict):
        result = {"ok": True, "status": "success", "result": result}
    return scrub(result)


def _disconnect(connections: Sequence[Any]) -> None:
    pending = [
        db
        for db in connections
        if getattr(db, "connected", False)
        or getattr(db, "connection", None) is not None
    ]
    if not pending:
        return

    async def _close() -> None:
        for db in pending:
            try:
                await db.disconnect()
            except Exception:
                db.connection = None
                db.connected = False

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_close())
        return
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, _close()).result()
