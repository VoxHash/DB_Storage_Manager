"""Feature gate. Full restore is stable and on unless Settings turns it off.

A feature is enabled when either ``DSM_EXPERIMENTAL`` is truthy in the process
environment or the matching flag is set in SecureStore ``settings["experimental"]``.
Environment wins so an operator can force-enable or CI can exercise a feature
without touching the encrypted settings file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

ENV_VAR = "DSM_EXPERIMENTAL"
FEATURE_RESTORE = "restore"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


class ExperimentalDisabledError(RuntimeError):
    """Raised when an experimental feature is used while it is switched off."""


def env_forces_experimental() -> bool:
    """True when ``DSM_EXPERIMENTAL`` enables every experimental feature."""
    return os.environ.get(ENV_VAR, "").strip().lower() in _TRUTHY


def is_enabled(
    feature: str, settings: Optional[Dict[str, Any]] = None
) -> bool:
    """Return whether ``feature`` is on (environment first, then settings)."""
    if env_forces_experimental():
        return True
    if settings is None:
        from .security.store import SecureStore

        settings = SecureStore().get_settings()
    flags = settings.get("experimental")
    return bool(isinstance(flags, dict) and flags.get(feature))


def is_restore_enabled(settings: Optional[Dict[str, Any]] = None) -> bool:
    """Full restore is stable and on unless Settings turns it off.

    ``DSM_EXPERIMENTAL=1`` forces it on. A missing flag is on. An explicit
    ``experimental.restore: false`` hides Restore. It still needs
    ``backups:restore``, a typed confirmation, and a safety backup.
    """
    if env_forces_experimental():
        return True
    if settings is None:
        from .security.store import SecureStore

        settings = SecureStore().get_settings()
    flags = settings.get("experimental")
    if not isinstance(flags, dict) or FEATURE_RESTORE not in flags:
        return True
    return bool(flags.get(FEATURE_RESTORE))


def require_restore_enabled(settings: Optional[Dict[str, Any]] = None) -> None:
    """Raise when the operator has turned full restore off."""
    if not is_restore_enabled(settings):
        raise ExperimentalDisabledError(
            "Full restore is turned off. Enable it under Settings → Backups & Adapters."
        )
