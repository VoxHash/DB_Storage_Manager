#!/usr/bin/env python3
"""E2E: import real local SSH / .env paths, probe, optionally save to SecureStore.

Opsec: never prints passwords or private key material. Skips missing paths.
Usage:

  .venv/bin/python scripts/import_connections_e2e.py
  .venv/bin/python scripts/import_connections_e2e.py --save
  .venv/bin/python scripts/import_connections_e2e.py --save-on-pass
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_storage_manager.importers import (  # noqa: E402
    import_env_file,
    import_ssh_key_path,
    probe_connection_sync,
    save_imported_connections,
    summarize_profile,
)

BRIGHTADS = Path(
    "/run/media/raider/Gaming_Images/Clients/BrightAds/connections"
)
SSH_CANDIDATES = [
    BRIGHTADS / "escortgirlsexy.com",
    BRIGHTADS / "escortsgirlsexy.com",
    BRIGHTADS / "transsexualdivas.com",
]
ENV_CANDIDATES = [
    Path(
        "/run/media/raider/Gaming_Images/Clients/JosaCore/local/"
        "asesoresyasociados.org/.env"
    ),
]


def _resolve_ssh_dirs() -> List[Path]:
    found: List[Path] = []
    seen = set()
    for path in SSH_CANDIDATES:
        if path.is_dir() and path.resolve() not in seen:
            key = path / "KEY"
            if key.is_file() or any(path.glob("id_*")):
                found.append(path)
                seen.add(path.resolve())
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--save",
        action="store_true",
        help="Always merge imported profiles into local SecureStore",
    )
    parser.add_argument(
        "--save-on-pass",
        action="store_true",
        help="Save only profiles whose probe passed",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=25.0,
        help="Per-connection probe timeout seconds",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional gitignored report path (redacted)",
    )
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "paths_found": [],
        "paths_missing": [],
        "results": [],
    }

    profiles: List[Dict[str, Any]] = []

    for path in SSH_CANDIDATES:
        if path.exists():
            report["paths_found"].append(str(path))
        else:
            report["paths_missing"].append(str(path))

    for directory in _resolve_ssh_dirs():
        try:
            profile = import_ssh_key_path(directory)
            profiles.append(profile)
            print(
                f"[import:ssh] {summarize_profile(profile)['name']} "
                f"type={profile.get('type')} bastion={profile.get('ssh_config', {}).get('ssh_host')}"
            )
        except Exception as exc:
            print(f"[import:ssh] FAIL {directory.name}: {type(exc).__name__}")
            report["results"].append(
                {
                    "source": "ssh",
                    "path": str(directory),
                    "status": "import_fail",
                    "error": type(exc).__name__,
                }
            )

    for env_path in ENV_CANDIDATES:
        if not env_path.is_file():
            report["paths_missing"].append(str(env_path))
            print(f"[import:env] skip missing {env_path}")
            continue
        report["paths_found"].append(str(env_path))
        try:
            imported = import_env_file(env_path)
            # Prefer pooler when direct host may be firewalled
            profiles.extend(imported)
            for p in imported:
                print(
                    f"[import:env] {summarize_profile(p)['name']} "
                    f"type={p.get('type')} host={p.get('host')} key={p.get('extra', {}).get('env_key')}"
                )
        except Exception as exc:
            print(f"[import:env] FAIL: {type(exc).__name__}")
            report["results"].append(
                {
                    "source": "env",
                    "path": str(env_path),
                    "status": "import_fail",
                    "error": type(exc).__name__,
                }
            )

    passed: List[Dict[str, Any]] = []
    for profile in profiles:
        result = probe_connection_sync(profile, timeout=args.timeout)
        status = result.get("status")
        err = result.get("error")
        summary = result.get("profile") or summarize_profile(profile)
        line = (
            f"[probe] {status} name={summary.get('name')} "
            f"engine={summary.get('type')} host={summary.get('host')}"
        )
        if summary.get("ssh_host"):
            line += f" bastion={summary.get('ssh_host')}"
        if err:
            line += f" error={err}"
        print(line)
        report["results"].append(
            {
                "status": status,
                "ok": result.get("ok"),
                "profile": summary,
                "error": err,
            }
        )
        if result.get("ok"):
            passed.append(profile)

    to_save: List[Dict[str, Any]] = []
    if args.save:
        to_save = profiles
    elif args.save_on_pass:
        to_save = passed

    if to_save:
        saved = save_imported_connections(to_save)
        report["secure_store"] = {
            "saved": saved.get("saved"),
            "total": saved.get("total"),
            "profiles": saved.get("profiles"),
        }
        print(
            f"[securestore] saved={saved.get('saved')} total_connections={saved.get('total')}"
        )
    else:
        report["secure_store"] = {"saved": 0, "note": "not requested"}

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(f"[report] wrote {args.json_out}")

    failures = [r for r in report["results"] if r.get("status") == "fail"]
    # Exit 0 if at least one probe passed and none hard-failed import;
    # still non-zero if all probes failed when paths existed.
    if not profiles:
        print("[e2e] no profiles imported (paths missing?)")
        return 0
    if failures and not passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
