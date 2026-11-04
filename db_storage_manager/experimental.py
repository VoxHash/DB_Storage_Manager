"""Experimental feature gate (default OFF on stable builds).

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
    return is_enabled(FEATURE_RESTORE, settings)


def require_restore_enabled(settings: Optional[Dict[str, Any]] = None) -> None:
    if not is_restore_enabled(settings):
        raise ExperimentalDisabledError(
            "Full restore is an experimental feature and is off. Enable it in "
            f"Settings > Backups & Adapters or set {ENV_VAR}=1."
        )
