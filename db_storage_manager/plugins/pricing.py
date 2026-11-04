"""
Premium plugin pricing policy (first-party VoxHash plugins).

Philosophy: the core app and all built-in tools stay free. Premium plugins are
priced to be affordable worldwide and to fund maintenance, security hardening
and more free features - not to maximise revenue. Amounts below are the
recommended ceilings for first-party plugins (USD); LicenseChain holds the
authoritative price on each product, ``plugin.json`` only mirrors it for display.

LicenseChain Products API (``POST /v1/products``) supports ``license`` +
``one_time`` products and ``subscription`` + ``recurring`` products with a
``month`` or ``year`` interval, a single ``price`` and ``currency`` per product.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ..config import SPONSORS_URL  # noqa: F401  (re-exported via plugins.sdk)

# Recommended price points (USD) - single plugin and "all premium plugins" bundle.
PRICING_TIERS: Dict[str, Dict[str, float]] = {
    "plugin": {"monthly": 1.99, "yearly": 16.00, "one_time": 24.00},
    "bundle": {"monthly": 4.99, "yearly": 39.00, "one_time": 59.00},
}

# LicenseChain product ids provisioned for the first-party premium plugins and
# the "all premium plugins" bundle (one product per billing option). A plugin's
# ``plugin.json`` ``license.product_id`` is the one it sells first; these are
# not secrets (they appear in the public checkout URL).
PREMIUM_PRODUCT_IDS: Dict[str, Dict[str, str]] = {
    "bundle": {
        "monthly": "e4fb8e02-487f-4809-8ccb-9e99ff909861",
        "yearly": "7c7b34bd-d87c-4499-8935-05416a6599bc",
        "one_time": "287b2566-0a86-4173-98d2-243e3178658c",
    },
    "pitr-verify": {
        "monthly": "099aab71-af7c-4639-84ff-0779793a734a",
        "yearly": "5e6d976b-ab60-4cef-a343-aa91122bef60",
        "one_time": "81eb6032-2629-49ab-8318-ca990d209a0d",
    },
    "schema-drift": {
        "monthly": "9905dae5-a315-4214-9e89-9bf286b95405",
        "yearly": "4235eb77-3e75-4d8c-9192-6a07681293aa",
        "one_time": "b4a003ad-e70f-4c7b-bc0c-0af3b6c457d7",
    },
    "rls-audit": {
        "monthly": "892f385a-b481-4179-a2ab-042ec325fe01",
        "yearly": "e502a5fa-02d1-4419-824d-ac0435a47de9",
        "one_time": "d5a0e27b-605e-49e2-a223-505c509451ae",
    },
    "pooler-health": {
        "monthly": "d9f24bbd-e3a1-4d08-905b-6784635bb43d",
        "yearly": "1cdda732-32e5-404d-bb61-fdfe98981fd9",
        "one_time": "e8c8356b-f9c2-4614-870e-432fec4a51b1",
    },
    "encrypted-export": {
        "monthly": "d7d9d5ae-898c-46c4-a7a6-a1af6dc671cf",
        "yearly": "49f37f1f-3383-4f01-9200-47fef68c29c3",
        "one_time": "5fd3ee0f-6c16-49ca-ac06-23fc462d0cc1",
    },
}

# A valid licence for any bundle product unlocks every first-party premium
# plugin, i.e. every plugin whose ``license.product_id`` is listed under a
# non-bundle entry of ``PREMIUM_PRODUCT_IDS``.
BUNDLE_PRODUCT_IDS = frozenset(PREMIUM_PRODUCT_IDS["bundle"].values())
FIRST_PARTY_PLUGIN_PRODUCT_IDS = frozenset(
    product_id
    for plugin, options in PREMIUM_PRODUCT_IDS.items()
    if plugin != "bundle"
    for product_id in options.values()
)


def accepted_product_ids(product_id: str) -> frozenset:
    """Product ids whose licence unlocks a plugin that requires ``product_id``.

    Always the plugin's own product. For first-party premium plugins (the id is
    listed in ``PREMIUM_PRODUCT_IDS``) every product of that plugin (monthly,
    yearly and one-time) and every bundle product is accepted, so any SKU the
    customer bought unlocks it whichever one the manifest lists. Third-party
    plugins are never unlocked by a bundle or by another SKU: exact match only.
    """
    accepted = {product_id}
    for plugin, options in PREMIUM_PRODUCT_IDS.items():
        if product_id in options.values():
            accepted |= set(options.values())
            accepted |= BUNDLE_PRODUCT_IDS
    return frozenset(accepted)


BILLING_OPTIONS = ("monthly", "yearly", "one_time")
_MAX_AMOUNT = 10_000.0


def validate_pricing(raw: Any) -> Optional[Dict[str, Any]]:
    """Normalise a ``license.pricing`` object; raises ``ValueError`` when invalid."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("license.pricing must be a JSON object")
    currency = raw.get("currency", "USD")
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise ValueError("license.pricing.currency must be a 3-letter ISO code")
    out: Dict[str, Any] = {"currency": currency}
    for option in BILLING_OPTIONS:
        if option not in raw:
            continue
        value = raw[option]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"license.pricing.{option} must be a number")
        if not 0 < float(value) <= _MAX_AMOUNT:
            raise ValueError(f"license.pricing.{option} must be > 0")
        out[option] = round(float(value), 2)
    if len(out) == 1:
        raise ValueError(
            "license.pricing needs at least one of: " + ", ".join(BILLING_OPTIONS)
        )
    return out


def format_pricing(pricing: Optional[Mapping[str, Any]]) -> str:
    """Human-readable price line, e.g. ``US$1.99/month · US$16.00/year``."""
    if not pricing:
        return ""
    currency = pricing.get("currency", "USD")
    prefix = "US$" if currency == "USD" else f"{currency} "
    parts: List[str] = []
    for option, suffix in (("monthly", "/month"), ("yearly", "/year"), ("one_time", " one-time")):
        if option in pricing:
            parts.append(f"{prefix}{float(pricing[option]):.2f}{suffix}")
    return " · ".join(parts)


def exceeds_first_party_policy(pricing: Mapping[str, Any], tier: str = "plugin") -> List[str]:
    """Return the options priced above the affordable ceiling (USD only)."""
    if pricing.get("currency", "USD") != "USD":
        return []
    ceiling = PRICING_TIERS[tier]
    return [
        option
        for option in BILLING_OPTIONS
        if option in pricing and float(pricing[option]) > ceiling[option]
    ]


def product_bodies(
    name: str,
    description: str,
    pricing: Mapping[str, Any],
    *,
    urls: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """LicenseChain ``POST /v1/products`` bodies, one per billing option."""
    urls = dict(urls or {})
    currency = pricing.get("currency", "USD")
    bodies: List[Dict[str, Any]] = []
    for option, label in (
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
        ("one_time", "One-time"),
    ):
        if option not in pricing:
            continue
        body: Dict[str, Any] = {
            "name": f"{name} - {label}",
            "description": description,
            "price": float(pricing[option]),
            "currency": currency,
            "active": True,
            "sendLicenseToCustomer": True,
        }
        if option == "one_time":
            body.update(productType="license", billingType="one_time")
        else:
            body.update(
                productType="subscription",
                billingType="recurring",
                interval="month" if option == "monthly" else "year",
            )
        for key in (
            "successUrl",
            "cancelUrl",
            "helpUrl",
            "supportUrl",
            "termsUrl",
            "privacyUrl",
            "refundUrl",
        ):
            if urls.get(key):
                body[key] = urls[key]
        bodies.append(body)
    return bodies
