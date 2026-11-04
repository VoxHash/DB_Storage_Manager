"""
Premium plugin licensing backed by LicenseChain.

Free plugins (the built-ins and any third-party plugin without a ``license``
block in ``plugin.json``) never touch this module's network code. A premium
plugin declares::

    "license": {"product_id": "<LicenseChain product id>"}

and the host then requires an active LicenseChain license for that product
before the plugin is installed, enabled, loaded or executed.

Verification uses only public LicenseChain endpoints, so no seller API key or
callback secret ever ships in the desktop app:

* ``POST {api}/licenses/verify``                  - validity, expiry, buyer email,
  optional RS256 ``license_token`` (checked against ``GET {api}/licenses/jwks``)
* ``POST {pay}/api/checkout/mirror/validate``     - proves the key was bought for
  ``product_id`` (the core verify response does not name the product)

License keys live in ``SecureStore`` (Fernet, ``plugin-licenses.enc``).
Environment overrides (same names the VoxHash web apps use):
``LICENSECHAIN_API_BASE``, ``LICENSECHAIN_PAY_BASE``. DSM-specific:
``DSM_LICENSE_RECHECK_HOURS`` (default 24), ``DSM_LICENSE_GRACE_DAYS``
(default 7, offline tolerance), ``DSM_LICENSECHAIN_HWUID=0`` (do not bind the
license to this device).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from .manifest import LicenseRequirement

DEFAULT_API_BASE = "https://api.licensechain.app/v1"
DEFAULT_PAY_BASE = "https://pay.licensechain.app"
LICENSE_TOKEN_USE_CLAIM = "licensechain_license_v1"

DEFAULT_RECHECK_HOURS = 24.0
DEFAULT_GRACE_DAYS = 7.0
_MAX_KEY_LENGTH = 512

# LicenseChain states that must never unlock a plugin.
_DENY_STATUSES = {"REVOKED", "SUSPENDED", "EXPIRED", "INACTIVE", "CANCELLED"}


class PluginLicenseError(RuntimeError):
    """A premium plugin is not licensed (or the license could not be proven)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid",
        requirement: Optional[LicenseRequirement] = None,
    ):
        super().__init__(message)
        self.code = code
        self.requirement = requirement


class PluginLicenseRequired(PluginLicenseError):
    """No license is stored for the plugin yet - the caller should ask for a key."""

    plugin_name: Optional[str] = None  # filled in by the marketplace for UI prompts


class LicenseNetworkError(PluginLicenseError):
    """LicenseChain could not be reached (offline, DNS, 5xx)."""

    def __init__(self, message: str, *, requirement=None):
        super().__init__(message, code="unverified", requirement=requirement)


@dataclass
class LicenseStatus:
    """Result of a license check. Never carries the license key itself."""

    plugin_id: str
    state: str  # not_required|licensed|grace|missing|invalid|expired|mismatch|unverified
    allowed: bool
    message: str = ""
    masked_key: str = ""
    expires_at: Optional[str] = None
    verified_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "state": self.state,
            "allowed": self.allowed,
            "message": self.message,
            "masked_key": self.masked_key,
            "expires_at": self.expires_at,
            "verified_at": self.verified_at,
        }


def mask_license_key(key: str) -> str:
    """Return a display-safe form of a license key (never log the full key)."""
    key = (key or "").strip()
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def default_hwuid() -> str:
    """Stable per-device id (sha256) used for LicenseChain hardware binding."""
    parts = ["dsm", platform.system(), platform.machine()]
    machine_id = ""
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                machine_id = handle.read().strip()
            if machine_id:
                break
        except OSError:
            continue
    parts.append(machine_id or socket.gethostname())
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _safe_base(url: str, label: str) -> str:
    parsed = urlparse(url)
    local = (parsed.hostname or "") in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise PluginLicenseError(
            f"{label} must use https (got {url!r})", code="config"
        )
    if not parsed.netloc:
        raise PluginLicenseError(f"{label} is missing a host", code="config")
    return url.rstrip("/")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def verify_license_token(
    token: str,
    jwks: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Verify a LicenseChain ``license_token`` (RS256) against a JWKS document.

    Uses ``cryptography`` (already a dependency); no PyJWT required. Raises
    :class:`PluginLicenseError` when the signature, expiry or purpose claim is
    wrong.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise PluginLicenseError(
            "license token is malformed", code="invalid"
        ) from exc

    if header.get("alg") != "RS256":
        raise PluginLicenseError("license token alg must be RS256", code="invalid")

    keys = [k for k in (jwks or {}).get("keys", []) if isinstance(k, dict)]
    kid = header.get("kid")
    candidates = [k for k in keys if k.get("kid") == kid] if kid else keys
    if not candidates:
        raise PluginLicenseError(
            "license token signing key is not published", code="invalid"
        )
    verified = False
    for jwk in candidates:
        if jwk.get("kty") != "RSA" or "n" not in jwk or "e" not in jwk:
            continue
        public_key = RSAPublicNumbers(
            int.from_bytes(_b64url_decode(jwk["e"]), "big"),
            int.from_bytes(_b64url_decode(jwk["n"]), "big"),
        ).public_key()
        try:
            public_key.verify(
                signature,
                f"{header_b64}.{payload_b64}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            verified = True
            break
        except InvalidSignature:
            continue
    if not verified:
        raise PluginLicenseError(
            "license token signature is invalid", code="invalid"
        )

    if claims.get("token_use") != LICENSE_TOKEN_USE_CLAIM:
        raise PluginLicenseError("license token has the wrong purpose", code="invalid")
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        moment = now or _utc_now()
        if moment.timestamp() >= exp:
            raise PluginLicenseError("license token has expired", code="expired")
    return claims


class LicenseChainClient:
    """Minimal client for the public LicenseChain verify / validate endpoints."""

    def __init__(
        self,
        api_base: Optional[str] = None,
        pay_base: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.api_base = _safe_base(
            api_base or os.environ.get("LICENSECHAIN_API_BASE") or DEFAULT_API_BASE,
            "LICENSECHAIN_API_BASE",
        )
        self.pay_base = _safe_base(
            pay_base or os.environ.get("LICENSECHAIN_PAY_BASE") or DEFAULT_PAY_BASE,
            "LICENSECHAIN_PAY_BASE",
        )
        self.timeout = timeout

    def _request(self, req: urllib.request.Request) -> Dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            if 400 <= exc.code < 500:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
                raise PluginLicenseError(
                    f"LicenseChain rejected the request (HTTP {exc.code})",
                    code="invalid",
                ) from exc
            raise LicenseNetworkError(
                f"LicenseChain is unavailable (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LicenseNetworkError(f"cannot reach LicenseChain: {exc}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LicenseNetworkError("LicenseChain returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise LicenseNetworkError("LicenseChain returned an unexpected payload")
        return parsed

    def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from ..config import APP_VERSION

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"DBStorageManager/{APP_VERSION}",
            },
        )
        return self._request(req)

    def verify(self, key: str, hwuid: Optional[str] = None) -> Dict[str, Any]:
        """``POST /v1/licenses/verify`` (public; hwuid binds on first use)."""
        payload: Dict[str, Any] = {"key": key}
        if hwuid:
            payload["hwuid"] = hwuid
        return self._post(f"{self.api_base}/licenses/verify", payload)

    def validate_purchase(self, key: str, email: str) -> Dict[str, Any]:
        """``POST {pay}/api/checkout/mirror/validate`` -> purchase.productId."""
        return self._post(
            f"{self.pay_base}/api/checkout/mirror/validate",
            {"license": key, "email": email},
        )

    def jwks(self) -> Dict[str, Any]:
        """``GET /v1/licenses/jwks`` (always from the trusted API base)."""
        from ..config import APP_VERSION

        req = urllib.request.Request(
            f"{self.api_base}/licenses/jwks",
            headers={
                "Accept": "application/json",
                "User-Agent": f"DBStorageManager/{APP_VERSION}",
            },
        )
        return self._request(req)


class PluginLicenseGate:
    """Decides whether a premium plugin may be installed / enabled / run."""

    def __init__(
        self,
        store: Any = None,
        client: Optional[LicenseChainClient] = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        recheck: Optional[timedelta] = None,
        grace: Optional[timedelta] = None,
        use_hwuid: Optional[bool] = None,
    ):
        self._store = store
        self._client = client
        self._clock = clock
        self.recheck = recheck or timedelta(
            hours=_env_float("DSM_LICENSE_RECHECK_HOURS", DEFAULT_RECHECK_HOURS)
        )
        self.grace = grace or timedelta(
            days=_env_float("DSM_LICENSE_GRACE_DAYS", DEFAULT_GRACE_DAYS)
        )
        if use_hwuid is None:
            use_hwuid = os.environ.get("DSM_LICENSECHAIN_HWUID", "1").strip() != "0"
        self.use_hwuid = use_hwuid

    # -- plumbing -------------------------------------------------------
    @property
    def store(self):
        if self._store is None:
            from ..security.store import SecureStore

            self._store = SecureStore()
        return self._store

    @property
    def client(self) -> LicenseChainClient:
        if self._client is None:
            self._client = LicenseChainClient()
        return self._client

    def _audit(self, action: str, outcome: str, **details: Any) -> None:
        try:
            from ..audit import write_audit

            write_audit(action, outcome, **details)
        except Exception:  # noqa: BLE001 - audit must never break licensing
            pass

    # -- online verification ---------------------------------------------
    def _verify_online(
        self,
        key: str,
        requirement: LicenseRequirement,
        email: Optional[str],
    ) -> Dict[str, Any]:
        now = self._clock()
        hwuid = default_hwuid() if self.use_hwuid else None
        resp = self.client.verify(key, hwuid)
        if not resp.get("valid"):
            reason = str(resp.get("reason") or resp.get("error") or "invalid license")
            code = "expired" if "expire" in reason.lower() else "invalid"
            raise PluginLicenseError(
                f"License rejected: {reason}", code=code, requirement=requirement
            )
        status = str(resp.get("status") or "ACTIVE").upper()
        if status in _DENY_STATUSES:
            raise PluginLicenseError(
                f"License is {status.lower()}",
                code="expired" if status == "EXPIRED" else "invalid",
                requirement=requirement,
            )
        expires_at = _parse_time(resp.get("expiresAt"))
        if expires_at is not None and expires_at <= now:
            raise PluginLicenseError(
                "License has expired", code="expired", requirement=requirement
            )

        license_id = None
        token = resp.get("license_token")
        if isinstance(token, str) and token:
            try:
                jwks = self.client.jwks()
            except LicenseNetworkError:
                jwks = None  # response itself came over TLS; keep going
            if jwks is not None:
                claims = verify_license_token(token, jwks, now=now)
                license_id = claims.get("sub")

        buyer = str(resp.get("email") or email or "").strip().lower()
        if not buyer:
            raise PluginLicenseError(
                "Enter the purchase email for this license",
                code="email_required",
                requirement=requirement,
            )
        purchase = self.client.validate_purchase(key, buyer)
        if not purchase.get("verified"):
            raise PluginLicenseError(
                "No active purchase found for this key and email",
                code="invalid",
                requirement=requirement,
            )
        info = purchase.get("purchase") or {}
        if str(info.get("productId") or "") != requirement.product_id:
            raise PluginLicenseError(
                "This license is for a different product",
                code="mismatch",
                requirement=requirement,
            )
        return {
            "license_key": key,
            "email": buyer,
            "product_id": requirement.product_id,
            "license_id": license_id or info.get("id"),
            "expires_at": _iso(expires_at) if expires_at else None,
            "verified_at": _iso(now),
        }

    # -- public API -------------------------------------------------------
    def activate(
        self,
        plugin_id: str,
        requirement: LicenseRequirement,
        key: str,
        email: Optional[str] = None,
    ) -> LicenseStatus:
        """Verify ``key`` online and store it for ``plugin_id`` (SecureStore)."""
        key = (key or "").strip()
        if not key or len(key) > _MAX_KEY_LENGTH or any(c.isspace() for c in key):
            raise PluginLicenseError(
                "Enter a valid license key", code="invalid", requirement=requirement
            )
        try:
            record = self._verify_online(key, requirement, email)
        except PluginLicenseError as exc:
            self._audit(
                "plugin.license.activate", "denied", plugin=plugin_id, reason=exc.code
            )
            raise
        licenses = self.store.get_plugin_licenses()
        licenses[plugin_id] = record
        self.store.save_plugin_licenses(licenses)
        self._audit("plugin.license.activate", "ok", plugin=plugin_id)
        return self._licensed(plugin_id, record, "licensed", "License active")

    def deactivate(self, plugin_id: str) -> bool:
        """Forget the stored license for ``plugin_id``."""
        licenses = self.store.get_plugin_licenses()
        if plugin_id not in licenses:
            return False
        del licenses[plugin_id]
        self.store.save_plugin_licenses(licenses)
        self._audit("plugin.license.deactivate", "ok", plugin=plugin_id)
        return True

    @staticmethod
    def _licensed(
        plugin_id: str, record: Dict[str, Any], state: str, message: str
    ) -> LicenseStatus:
        return LicenseStatus(
            plugin_id=plugin_id,
            state=state,
            allowed=state in ("licensed", "grace"),
            message=message,
            masked_key=mask_license_key(record.get("license_key", "")),
            expires_at=record.get("expires_at"),
            verified_at=record.get("verified_at"),
        )

    def status(
        self,
        plugin_id: str,
        requirement: Optional[LicenseRequirement],
        *,
        network: bool = True,
    ) -> LicenseStatus:
        """Return the license state; ``network=False`` only trusts the cache."""
        if requirement is None or not requirement.required:
            return LicenseStatus(plugin_id, "not_required", True, "Free plugin")

        licenses = self.store.get_plugin_licenses()
        record = licenses.get(plugin_id)
        if not record:
            return LicenseStatus(
                plugin_id, "missing", False, "License required"
            )
        if record.get("product_id") != requirement.product_id:
            return self._licensed(
                plugin_id, record, "mismatch", "Stored license is for another product"
            )
        if record.get("invalid_reason"):
            return self._licensed(
                plugin_id, record, "invalid", str(record["invalid_reason"])
            )

        now = self._clock()
        expires_at = _parse_time(record.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            return self._licensed(plugin_id, record, "expired", "License has expired")
        verified_at = _parse_time(record.get("verified_at"))
        age = (now - verified_at) if verified_at else None

        if age is not None and age < self.recheck:
            return self._licensed(plugin_id, record, "licensed", "License active")

        if network:
            try:
                fresh = self._verify_online(
                    record["license_key"], requirement, record.get("email")
                )
            except LicenseNetworkError:
                pass  # fall through to the offline grace window
            except PluginLicenseError as exc:
                record["invalid_reason"] = str(exc)
                licenses[plugin_id] = record
                self.store.save_plugin_licenses(licenses)
                self._audit(
                    "plugin.license.revalidate",
                    "denied",
                    plugin=plugin_id,
                    reason=exc.code,
                )
                return self._licensed(
                    plugin_id,
                    record,
                    "expired" if exc.code == "expired" else "invalid",
                    str(exc),
                )
            else:
                licenses[plugin_id] = fresh
                self.store.save_plugin_licenses(licenses)
                return self._licensed(plugin_id, fresh, "licensed", "License active")

        if age is not None and age <= self.grace:
            return self._licensed(
                plugin_id,
                record,
                "grace",
                "Offline - using last verified license",
            )
        return self._licensed(
            plugin_id,
            record,
            "unverified",
            "License could not be re-verified; connect to the internet",
        )

    def require(
        self,
        plugin_id: str,
        requirement: Optional[LicenseRequirement],
        *,
        network: bool = True,
    ) -> LicenseStatus:
        """Raise unless the plugin is free or has an allowed license state."""
        result = self.status(plugin_id, requirement, network=network)
        if result.allowed:
            return result
        error_cls = PluginLicenseRequired if result.state == "missing" else PluginLicenseError
        raise error_cls(
            result.message or "License required",
            code=result.state,
            requirement=requirement,
        )
