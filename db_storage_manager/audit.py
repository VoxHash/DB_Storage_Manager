"""Append-only JSON-lines audit trail for destructive actions.

Entries never contain passphrases, passwords or connection secrets - only who
did what to which object and how it ended.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

_lock = threading.Lock()

# Keys that must never be written even if a caller passes them by mistake.
_FORBIDDEN = ("password", "passphrase", "secret", "token", "key")


def audit_log_path() -> Path:
    return Path(config.AUDIT_LOG_FILE)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _clean(v)
            for k, v in value.items()
            if not any(bad in str(k).lower() for bad in _FORBIDDEN)
        }
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def current_actor() -> str:
    """Signed-in username, or ``local`` when RBAC is not active."""
    try:
        from .security.auth import get_auth_manager

        auth = get_auth_manager()
        if auth.is_rbac_active() and auth.current_user:
            return auth.current_user.username
    except Exception:  # noqa: BLE001 - audit must never break the action
        pass
    return "local"


def write_audit(action: str, outcome: str, **details: Any) -> Dict[str, Any]:
    """Append one audit record and return it."""
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "actor": current_actor(),
        "action": action,
        "outcome": outcome,
    }
    record.update(_clean(details))
    path = audit_log_path()
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if new_file and os.name != "nt":
            os.chmod(path, 0o600)
    return record


def read_audit(limit: Optional[int] = 200) -> List[Dict[str, Any]]:
    """Return the newest ``limit`` records (oldest first)."""
    path = audit_log_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows
