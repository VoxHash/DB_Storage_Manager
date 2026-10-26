"""
Companion pairing tokens (SecureStore-backed).

Desktop generates a high-entropy Bearer token once, stores only its SHA-256
digest in encrypted settings, and shows the plaintext to the operator for
phone entry. The REST companion accepts either ``DSM_API_TOKEN`` (env) or a
valid pairing token. Fernet master keys are never mirrored to mobile clients.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import secrets
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .store import SecureStore

COMPANION_SETTINGS_KEY = "companion"
TOKEN_BYTES = 32


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def hash_pairing_token(token: str) -> str:
    """SHA-256 hex digest of a pairing / Bearer token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_companion_prefs(store: Optional[SecureStore] = None) -> Dict[str, Any]:
    store = store or SecureStore()
    settings = store.get_settings()
    raw = settings.get(COMPANION_SETTINGS_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def pairing_status(store: Optional[SecureStore] = None) -> Dict[str, Any]:
    prefs = get_companion_prefs(store)
    digest = prefs.get("pairing_token_hash")
    return {
        "paired": bool(digest),
        "created_at": prefs.get("pairing_created_at"),
        "label": prefs.get("pairing_label") or "",
        "token_fingerprint": (str(digest)[:12] + "…") if digest else None,
    }


def create_pairing_token(
    store: Optional[SecureStore] = None,
    *,
    label: str = "android-companion",
) -> str:
    """
    Generate a new pairing token, persist only its hash in SecureStore, return
    the plaintext once for operator display / QR / phone entry.
    """
    store = store or SecureStore()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    digest = hash_pairing_token(token)
    settings = store.get_settings()
    companion = dict(settings.get(COMPANION_SETTINGS_KEY) or {})
    companion["pairing_token_hash"] = digest
    companion["pairing_created_at"] = _utc_now_iso()
    companion["pairing_label"] = label or "android-companion"
    settings[COMPANION_SETTINGS_KEY] = companion
    store.set_settings(settings)
    return token


def revoke_pairing_token(store: Optional[SecureStore] = None) -> bool:
    """Clear SecureStore pairing digest. Returns True if something was cleared."""
    store = store or SecureStore()
    settings = store.get_settings()
    companion = dict(settings.get(COMPANION_SETTINGS_KEY) or {})
    had = bool(companion.get("pairing_token_hash"))
    companion["pairing_token_hash"] = None
    companion["pairing_created_at"] = None
    companion["pairing_label"] = companion.get("pairing_label") or ""
    companion["revoked_at"] = _utc_now_iso()
    settings[COMPANION_SETTINGS_KEY] = companion
    store.set_settings(settings)
    return had


def verify_pairing_token(
    presented: str, store: Optional[SecureStore] = None
) -> bool:
    """Constant-time check of a Bearer token against the SecureStore digest."""
    if not presented or not presented.strip():
        return False
    prefs = get_companion_prefs(store)
    expected = prefs.get("pairing_token_hash")
    if not expected or not isinstance(expected, str):
        return False
    got = hash_pairing_token(presented.strip())
    return hmac.compare_digest(got, expected)


def resolve_api_bearer_ok(
    presented: Optional[str],
    *,
    env_token: Optional[str] = None,
    store: Optional[SecureStore] = None,
) -> Tuple[bool, str]:
    """
    Accept env ``DSM_API_TOKEN`` or a SecureStore pairing token.

    Returns ``(ok, source)`` where source is ``env``, ``pairing``, or ``none``.
    """
    token = (presented or "").strip()
    if not token:
        return False, "none"
    expected_env = (env_token if env_token is not None else os.environ.get("DSM_API_TOKEN", "")).strip()
    if expected_env and hmac.compare_digest(token, expected_env):
        return True, "env"
    if verify_pairing_token(token, store=store):
        return True, "pairing"
    return False, "none"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or revoke a SecureStore-backed companion pairing token "
            "(plaintext shown once; only SHA-256 stored)."
        )
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Clear the stored pairing digest",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show whether a pairing digest is present (no secrets)",
    )
    parser.add_argument(
        "--label",
        default="android-companion",
        help="Label stored with the pairing digest (default: android-companion)",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the new plaintext token to stdout (default: stderr prompt style)",
    )
    args = parser.parse_args(argv)

    store = SecureStore()
    if args.status:
        status = pairing_status(store)
        print(
            f"paired={status['paired']} "
            f"label={status['label']!r} "
            f"created_at={status['created_at']} "
            f"fingerprint={status['token_fingerprint']}",
            flush=True,
        )
        return 0

    if args.revoke:
        had = revoke_pairing_token(store)
        print("Pairing token revoked." if had else "No pairing token was stored.", flush=True)
        return 0

    token = create_pairing_token(store, label=args.label)
    status = pairing_status(store)
    msg = (
        "Companion pairing token created.\n"
        f"  label: {status['label']}\n"
        f"  fingerprint: {status['token_fingerprint']}\n"
        "  Store the Bearer token on the phone only (EncryptedSharedPreferences).\n"
        "  Never commit the token. Fernet master keys stay on the desktop.\n"
        "  Enter this once on the Android companion (or set DSM_API_TOKEN):\n"
    )
    sys.stderr.write(msg)
    if args.print_token:
        print(token, flush=True)
    else:
        sys.stderr.write(f"\n{token}\n\n")
        sys.stderr.write(
            "Re-run with --print-token to emit only the token on stdout "
            "(for scripts / QR pipelines).\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
