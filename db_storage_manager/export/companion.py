"""
Credential / connection metadata export for companions.

Default mode never includes plaintext passwords, SSH secrets, cloud keys, or
Fernet master material. Opt-in ``include_secrets=True`` requires
``consent=True`` and is intended for air-gapped desktop backup only — not for
phone sync.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.sanitize import sanitize_connections
from ..security.pairing import pairing_status
from ..security.store import SecureStore

EXPORT_FORMAT = "dsm-companion-export"
EXPORT_VERSION = 1


class CompanionExportError(ValueError):
    """Invalid export options (e.g. secrets without consent)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def export_companion_bundle(
    store: Optional[SecureStore] = None,
    *,
    include_secrets: bool = False,
    consent: bool = False,
    label: str = "",
) -> Dict[str, Any]:
    """
    Build a JSON-serializable companion export document.

    Parameters
    ----------
    include_secrets:
        When False (default), passwords and key material are redacted (``***``).
    consent:
        Must be True if ``include_secrets`` is True. Documents operator intent;
        still never appropriate for GrapheneOS / phone storage of Fernet keys.
    """
    if include_secrets and not consent:
        raise CompanionExportError(
            "include_secrets requires consent=True "
            "(plaintext secrets must never leave the desktop without explicit opt-in)"
        )

    store = store or SecureStore()
    connections = store.get_connections()
    if include_secrets:
        exported_connections: List[Dict[str, Any]] = copy.deepcopy(connections)
        secrets_mode = "plaintext_with_consent"
    else:
        exported_connections = sanitize_connections(connections)
        secrets_mode = "redacted"

    pair = pairing_status(store)
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": _utc_now_iso(),
        "label": label or "",
        "secrets_mode": secrets_mode,
        "include_secrets": bool(include_secrets),
        "consent": bool(consent) if include_secrets else False,
        "warnings": _warnings(include_secrets),
        "pairing": {
            "paired": pair["paired"],
            "label": pair["label"],
            "created_at": pair["created_at"],
            "token_fingerprint": pair["token_fingerprint"],
            # Never embed the Bearer token or its full hash in export files
        },
        "connections": exported_connections,
        "connection_count": len(exported_connections),
        "notes": (
            "Sanitized metadata for companion glance / inventory. "
            "Does not include .master-key, users.enc password hashes, or "
            "cloud static keys unless include_secrets+consent was set."
        ),
    }


def _warnings(include_secrets: bool) -> List[str]:
    warnings = [
        "Do not sync .master-key or *.enc stores to phone cloud backup.",
        "Prefer SecureStore pairing Bearer token over copying connection passwords.",
        "Companion APIs already return redacted connection profiles.",
    ]
    if include_secrets:
        warnings.insert(
            0,
            "PLAINTEXT SECRETS PRESENT — desktop air-gap / encrypted archive only; "
            "never load this file on Android / GrapheneOS.",
        )
    return warnings


def write_companion_export(
    path: Path,
    store: Optional[SecureStore] = None,
    *,
    include_secrets: bool = False,
    consent: bool = False,
    label: str = "",
) -> Dict[str, Any]:
    """Write export JSON to ``path`` (mode 0o600 on POSIX)."""
    import os

    bundle = export_companion_bundle(
        store,
        include_secrets=include_secrets,
        consent=consent,
        label=label,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)
    return bundle


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export connection metadata for companions "
            "(secrets redacted unless --include-secrets --i-consent)"
        )
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write JSON to this path (mode 600). Default: stdout",
    )
    parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="Include plaintext passwords (requires --i-consent; not for phones)",
    )
    parser.add_argument(
        "--i-consent",
        action="store_true",
        help="Explicit consent that plaintext secrets may be written (desktop only)",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional label embedded in the export document",
    )
    args = parser.parse_args(argv)

    try:
        if args.output:
            bundle = write_companion_export(
                args.output,
                include_secrets=args.include_secrets,
                consent=args.i_consent,
                label=args.label,
            )
            print(
                f"Wrote {args.output} "
                f"(secrets_mode={bundle['secrets_mode']}, "
                f"connections={bundle['connection_count']})",
                flush=True,
            )
        else:
            bundle = export_companion_bundle(
                include_secrets=args.include_secrets,
                consent=args.i_consent,
                label=args.label,
            )
            json.dump(bundle, sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
    except CompanionExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
