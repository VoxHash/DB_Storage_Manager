"""
Local admin bootstrap for multi-user / RBAC.

Creates the first admin in encrypted ``users.enc`` when the store is empty.

Usage::

    db-storage-manager-bootstrap --username admin --password '…'
    # or
    python -m db_storage_manager.security.bootstrap --username admin --password '…'

Environment (optional, avoids shell history for the password)::

    DSM_BOOTSTRAP_USERNAME=admin
    DSM_BOOTSTRAP_PASSWORD=…
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Optional

from .auth import AuthenticationManager, reset_auth_manager
from .store import SecureStore


def bootstrap_admin(
    username: str,
    password: str,
    email: str = "",
    *,
    store: Optional[SecureStore] = None,
) -> str:
    """
    Create the first admin account.

    Returns the username on success. Raises on validation / already-initialized.
    """
    reset_auth_manager()
    s = store or SecureStore()
    auth = AuthenticationManager(store=s)
    user = auth.bootstrap_admin(username, password, email=email)
    # Publish as process singleton so GUI/API see the new accounts
    import db_storage_manager.security.auth as auth_mod

    auth_mod._auth_manager = auth
    # Keep settings.rbac.enabled in sync for UI/docs
    settings = s.get_settings()
    rbac = dict(settings.get("rbac") or {})
    rbac["enabled"] = True
    settings["rbac"] = rbac
    s.set_settings(settings)
    return user.username


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap the first local admin for DB Storage Manager RBAC "
            "(writes encrypted users.enc under the user data directory)"
        )
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("DSM_BOOTSTRAP_USERNAME", ""),
        help="Admin username (or DSM_BOOTSTRAP_USERNAME)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("DSM_BOOTSTRAP_PASSWORD", ""),
        help="Admin password (or DSM_BOOTSTRAP_PASSWORD; prompt if omitted)",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Optional email stored with the account",
    )
    args = parser.parse_args(argv)

    username = (args.username or "").strip()
    if not username:
        username = input("Admin username: ").strip()
    if not username:
        print("error: username is required", file=sys.stderr)
        return 2

    password = args.password or ""
    if not password:
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("error: passwords do not match", file=sys.stderr)
            return 2

    try:
        name = bootstrap_admin(username, password, email=args.email or "")
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Bootstrapped admin '{name}'. "
        "Restart the desktop app and sign in. "
        "API companion: use Basic auth as this user, or DSM_API_TOKEN "
        "(treated as system admin when RBAC is active)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
