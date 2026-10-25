"""
Dashboard layout / watched-metrics preferences (pure helpers, no Qt).

Persisted under SecureStore settings key ``dashboard_layout``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .config import (
    DASHBOARD_COLUMN_KEYS,
    DASHBOARD_METRIC_KEYS,
    DEFAULT_DASHBOARD_LAYOUT,
)

_LAYOUT_SNAPSHOT_KEYS = ("watched_metrics", "table_columns", "metric_order")


def _filter_known(values: Any, allowed: tuple) -> List[str]:
    if not isinstance(values, (list, tuple)):
        return list(allowed)
    seen = set()
    out: List[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        if item in allowed and item not in seen:
            out.append(item)
            seen.add(item)
    return out if out else list(allowed)


def normalize_layout_snapshot(raw: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Normalize watched metrics / columns / order for one layout view."""
    raw = raw if isinstance(raw, dict) else {}
    watched = _filter_known(raw.get("watched_metrics"), DASHBOARD_METRIC_KEYS)
    columns = _filter_known(raw.get("table_columns"), DASHBOARD_COLUMN_KEYS)
    order = _filter_known(raw.get("metric_order"), DASHBOARD_METRIC_KEYS)
    # Keep metric_order aligned with watched set while preserving relative order
    watched_set = set(watched)
    order = [m for m in order if m in watched_set]
    for m in watched:
        if m not in order:
            order.append(m)
    return {
        "watched_metrics": watched,
        "table_columns": columns,
        "metric_order": order,
    }


def normalize_dashboard_layout(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge and sanitize a full dashboard_layout settings blob."""
    defaults = copy.deepcopy(DEFAULT_DASHBOARD_LAYOUT)
    if not isinstance(raw, dict):
        return defaults

    current = normalize_layout_snapshot(
        {
            "watched_metrics": raw.get("watched_metrics", defaults["watched_metrics"]),
            "table_columns": raw.get("table_columns", defaults["table_columns"]),
            "metric_order": raw.get("metric_order", defaults["metric_order"]),
        }
    )

    saved_raw = raw.get("saved_layouts")
    saved: Dict[str, Dict[str, List[str]]] = {}
    if isinstance(saved_raw, dict):
        for name, snap in saved_raw.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if isinstance(snap, dict):
                saved[name.strip()] = normalize_layout_snapshot(snap)
    if "Default" not in saved:
        saved["Default"] = normalize_layout_snapshot(defaults["saved_layouts"]["Default"])

    active = raw.get("active_layout")
    if not isinstance(active, str) or active not in saved:
        active = "Default"

    last_id = raw.get("last_connection_id")
    if last_id is not None and not isinstance(last_id, str):
        last_id = None

    return {
        "watched_metrics": current["watched_metrics"],
        "table_columns": current["table_columns"],
        "metric_order": current["metric_order"],
        "last_connection_id": last_id,
        "active_layout": active,
        "saved_layouts": saved,
    }


def snapshot_from_layout(layout: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract the current view snapshot from a full layout dict."""
    return normalize_layout_snapshot(
        {k: layout.get(k) for k in _LAYOUT_SNAPSHOT_KEYS}
    )


def apply_named_layout(layout: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Activate a named saved layout onto the current view fields."""
    normalized = normalize_dashboard_layout(layout)
    saved = normalized["saved_layouts"]
    if name not in saved:
        raise KeyError(name)
    snap = saved[name]
    normalized["watched_metrics"] = list(snap["watched_metrics"])
    normalized["table_columns"] = list(snap["table_columns"])
    normalized["metric_order"] = list(snap["metric_order"])
    normalized["active_layout"] = name
    return normalized


def save_named_layout(layout: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Persist the current view into ``saved_layouts[name]`` and activate it."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Layout name is required")
    name = name.strip()
    normalized = normalize_dashboard_layout(layout)
    snap = snapshot_from_layout(normalized)
    normalized["saved_layouts"][name] = snap
    normalized["active_layout"] = name
    return normalized


def delete_named_layout(layout: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Remove a named layout (Default cannot be deleted)."""
    if name == "Default":
        raise ValueError("Cannot delete the Default layout")
    normalized = normalize_dashboard_layout(layout)
    if name not in normalized["saved_layouts"]:
        raise KeyError(name)
    del normalized["saved_layouts"][name]
    if normalized["active_layout"] == name:
        normalized = apply_named_layout(normalized, "Default")
    return normalized
