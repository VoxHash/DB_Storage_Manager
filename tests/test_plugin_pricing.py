"""Premium plugin pricing metadata, policy ceilings and LicenseChain product bodies."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from db_storage_manager.config import SPONSORS_URL
from db_storage_manager.plugins.manifest import ManifestError, validate_manifest
from db_storage_manager.plugins.pricing import (
    PRICING_TIERS,
    exceeds_first_party_policy,
    format_pricing,
    product_bodies,
    validate_pricing,
)

PRODUCT_ID = "11111111-2222-3333-4444-555555555555"
ROOT = Path(__file__).resolve().parents[1]


def _manifest(pricing=None) -> dict:
    lic = {"product_id": PRODUCT_ID}
    if pricing is not None:
        lic["pricing"] = pricing
    return {
        "id": "pro_report",
        "name": "Pro Report",
        "version": "1.0.0",
        "author": "VoxHash Technologies",
        "description": "Premium reporting plugin",
        "plugin_type": "custom",
        "entry": "plugin:ProReport",
        "license": lic,
    }


def test_recommended_tiers_are_affordable_and_ordered():
    for tier in PRICING_TIERS.values():
        assert tier["monthly"] < tier["yearly"] < tier["one_time"]
        assert tier["yearly"] < tier["monthly"] * 12  # yearly always cheaper
        assert tier["one_time"] <= 59.0
    assert PRICING_TIERS["plugin"]["monthly"] < 2.0
    assert PRICING_TIERS["bundle"]["monthly"] < PRICING_TIERS["plugin"]["monthly"] * 3


def test_sponsors_url_matches_funding_yml():
    funding = (ROOT / ".github" / "FUNDING.yml").read_text("utf-8")
    assert "github: [voxhash]" in funding.lower()
    assert SPONSORS_URL == "https://github.com/sponsors/VoxHash"


def test_manifest_carries_pricing_and_roundtrips():
    manifest = validate_manifest(
        _manifest({"currency": "USD", "monthly": 1.99, "one_time": 24})
    )
    assert manifest.license.pricing == {
        "currency": "USD",
        "monthly": 1.99,
        "one_time": 24.0,
    }
    assert manifest.to_dict()["license"]["pricing"]["one_time"] == 24.0
    assert format_pricing(manifest.license.pricing) == "US$1.99/month · US$24.00 one-time"


def test_manifest_without_pricing_omits_block():
    manifest = validate_manifest(_manifest())
    assert manifest.license.pricing is None
    assert "pricing" not in manifest.to_dict()["license"]


@pytest.mark.parametrize(
    "bad",
    [
        "free",
        {"currency": "usd", "monthly": 1},
        {"currency": "USD"},
        {"monthly": 0},
        {"monthly": -3},
        {"monthly": "1.99"},
        {"monthly": True},
        {"monthly": 1_000_000},
    ],
)
def test_invalid_pricing_fails_closed(bad):
    with pytest.raises(ManifestError):
        validate_manifest(_manifest(bad))


def test_policy_ceiling():
    tier = PRICING_TIERS["plugin"]
    assert exceeds_first_party_policy({"currency": "USD", **tier}) == []
    assert exceeds_first_party_policy({"currency": "USD", "monthly": 9.99}) == ["monthly"]
    assert exceeds_first_party_policy({"currency": "EUR", "monthly": 99}) == []
    assert exceeds_first_party_policy(
        {"currency": "USD", "monthly": 4.99}, tier="bundle"
    ) == []


def test_product_bodies_match_licensechain_products_api():
    pricing = validate_pricing({"currency": "USD", **PRICING_TIERS["plugin"]})
    bodies = product_bodies(
        "Pro Report",
        "desc",
        pricing,
        urls={"successUrl": "https://example.com/ok", "termsUrl": ""},
    )
    by_name = {b["name"]: b for b in bodies}
    monthly = by_name["Pro Report - Monthly"]
    assert (monthly["productType"], monthly["billingType"], monthly["interval"]) == (
        "subscription",
        "recurring",
        "month",
    )
    assert monthly["price"] == 1.99 and monthly["currency"] == "USD"
    assert by_name["Pro Report - Yearly"]["interval"] == "year"
    once = by_name["Pro Report - One-time"]
    assert (once["productType"], once["billingType"]) == ("license", "one_time")
    assert "interval" not in once
    assert monthly["successUrl"] == "https://example.com/ok"
    assert "termsUrl" not in monthly
    json.dumps(bodies)


def test_script_dry_run_prints_bodies_and_never_calls_network(tmp_path):
    plugin = tmp_path / "pro_report"
    plugin.mkdir()
    manifest = _manifest({"currency": "USD", **PRICING_TIERS["plugin"]})
    (plugin / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin / "plugin.py").write_text("class ProReport: pass\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "licensechain_products.py"), str(plugin)],
        capture_output=True,
        text=True,
        env={"PATH": "", "LICENSECHAIN_API_KEY": "secret-should-not-appear"},
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "US$1.99/month" in result.stdout
    assert "secret-should-not-appear" not in result.stdout + result.stderr
    assert json.loads(result.stdout.split("\n", 1)[1])[0]["billingType"] == "recurring"


def test_script_rejects_unaffordable_price(tmp_path):
    plugin = tmp_path / "pro_report"
    plugin.mkdir()
    manifest = _manifest({"currency": "USD", "monthly": 19.99})
    (plugin / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin / "plugin.py").write_text("class ProReport: pass\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "licensechain_products.py"), str(plugin)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 2
    assert "policy ceiling" in result.stderr
