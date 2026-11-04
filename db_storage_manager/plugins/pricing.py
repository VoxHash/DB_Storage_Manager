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
