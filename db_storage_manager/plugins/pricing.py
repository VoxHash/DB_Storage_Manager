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
        "monthly": "68967897-d070-450c-bb7a-07a3e7d79bdf",
        "yearly": "38da2336-ae9f-42e5-81a1-1ea99a882e2c",
        "one_time": "4429e413-fe8f-4602-b281-0ecf3a7d3c60",
    },
    "pitr-verify": {
        "monthly": "2e1b1388-5e8c-459d-a5e6-62ef146c4682",
        "yearly": "d1c45cba-7af8-422e-8b47-88086ae4c714",
        "one_time": "50736ce6-a35e-48f1-b893-a4fc9a1ed173",
    },
    "schema-drift": {
        "monthly": "fbcb9ad2-6859-4d9b-832e-7d0224fb669a",
        "yearly": "2815f050-6b3b-4f94-a010-fc3388607f72",
        "one_time": "0db40f25-6248-45cd-b354-db0043b22cc2",
    },
    "rls-audit": {
        "monthly": "dbd8dffc-608b-4eed-9a84-2b0e4e406491",
        "yearly": "1cd4f7bd-72d9-4ba3-9a6a-4a35effe8bf7",
        "one_time": "a64d369f-2fa0-4598-88e0-afb79b304336",
    },
    "pooler-health": {
        "monthly": "869a9e74-5506-428f-a941-532c10b0c757",
        "yearly": "15cb51f0-9b8f-490f-9834-d9d845227028",
        "one_time": "4e51906a-8e0c-4ade-9069-760a08fda5dc",
    },
    "encrypted-export": {
        "monthly": "cf252f7b-9e64-4149-8c64-be1fcdbd8f98",
        "yearly": "0e19b52f-f0bf-4e0b-bf1e-ee53d917e949",
        "one_time": "15ba1ef3-4efa-4218-aaf3-8db9944dcb2e",
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
