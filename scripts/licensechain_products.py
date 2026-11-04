#!/usr/bin/env python3
"""Create LicenseChain products for a premium DSM plugin from its plugin.json.

Dry run by default (prints the request bodies). With ``--apply`` it calls
``POST {LICENSECHAIN_API_BASE}/products`` using ``LICENSECHAIN_API_KEY`` from the
environment. The key and the returned ``callbackSecret`` are never printed.

    python scripts/licensechain_products.py path/to/plugin
    LICENSECHAIN_API_KEY=... python scripts/licensechain_products.py path/to/plugin --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db_storage_manager.plugins.manifest import load_manifest  # noqa: E402
from db_storage_manager.plugins.pricing import (  # noqa: E402
    exceeds_first_party_policy,
    format_pricing,
    product_bodies,
)

URL_FLAGS = (
    "success",
    "cancel",
    "help",
    "support",
    "terms",
    "privacy",
    "refund",
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="create the products")
    parser.add_argument(
        "--allow-above-policy",
        action="store_true",
        help="allow prices above the affordable first-party ceilings",
    )
    for flag in URL_FLAGS:
        parser.add_argument(f"--{flag}-url", default="")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.plugin_dir)
    pricing = manifest.license.pricing if manifest.license else None
    if not pricing:
        print("plugin.json has no license.pricing block", file=sys.stderr)
        return 2
    over = exceeds_first_party_policy(pricing)
    if over and not args.allow_above_policy:
        print(
            "pricing above the affordable policy ceiling for: " + ", ".join(over),
            file=sys.stderr,
        )
        return 2

    urls = {f"{flag}Url": getattr(args, f"{flag}_url") for flag in URL_FLAGS}
    bodies = product_bodies(manifest.name, manifest.description, pricing, urls=urls)
    print(f"{manifest.name}: {format_pricing(pricing)}")
    if not args.apply:
        print(json.dumps(bodies, indent=2))
        print("dry run - pass --apply to create these products", file=sys.stderr)
        return 0

    api_key = os.environ.get("LICENSECHAIN_API_KEY", "").strip()
    if not api_key:
        print("LICENSECHAIN_API_KEY is not set", file=sys.stderr)
        return 2
    base = (os.environ.get("LICENSECHAIN_API_BASE") or "https://api.licensechain.app/v1").rstrip("/")
    if not base.startswith("https://"):
        print("LICENSECHAIN_API_BASE must use https", file=sys.stderr)
        return 2
    for body in bodies:
        req = urllib.request.Request(
            f"{base}/products",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                created = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print(f"{body['name']}: HTTP {exc.code}", file=sys.stderr)
            return 1
        print(f"created {created.get('name')}: product id {created.get('id')}")
    print("Set license.product_id in plugin.json to the option you sell first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
