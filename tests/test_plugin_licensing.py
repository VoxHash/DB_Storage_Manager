"""Premium plugin licensing (LicenseChain) gate tests.

The unit tests talk to a real local HTTP server that implements the public
LicenseChain contract (``POST /v1/licenses/verify``, ``GET /v1/licenses/jwks``,
``POST /api/checkout/mirror/validate``) and signs ``license_token`` values with
a real RSA key, so the client, JWKS verification and SecureStore paths run for
real. One extra test hits the live LicenseChain API with an unknown key.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from db_storage_manager.plugins.base import PluginManager
from db_storage_manager.plugins.licensing import (
    LicenseChainClient,
    LicenseNetworkError,
    PluginLicenseError,
    PluginLicenseGate,
    PluginLicenseRequired,
    mask_license_key,
    verify_license_token,
)
from db_storage_manager.plugins.manifest import (
    LICENSECHAIN_CHECKOUT_BASE,
    ManifestError,
    validate_manifest,
)
from db_storage_manager.plugins.marketplace import LocalPluginMarketplace

PRODUCT_ID = "11111111-2222-3333-4444-555555555555"
OTHER_PRODUCT_ID = "99999999-8888-7777-6666-000000000000"
GOOD_KEY = "LC-TEST-GOOD-KEY1"
EMAIL = "buyer@example.com"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class _LicenseChainStub:
    """State shared with the HTTP handler (licenses + signing key)."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"
        self.licenses: dict[str, dict] = {}
        self.calls: list[str] = []
        self.online = True

    def jwks(self) -> dict:
        numbers = self.key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": self.kid,
                    "use": "sig",
                    "alg": "RS256",
                    "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                    "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
                }
            ]
        }

    def sign(self, claims: dict, *, key=None) -> str:
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": self.kid}).encode())
        payload = _b64(json.dumps(claims).encode())
        signer = key or self.key
        sig = signer.sign(
            f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{header}.{payload}.{_b64(sig)}"

    def token(self, license_id: str, *, key=None, ttl: int = 900) -> str:
        return self.sign(
            {
                "iss": "http://127.0.0.1",
                "sub": license_id,
                "token_use": "licensechain_license_v1",
                "exp": int(time.time()) + ttl,
            },
            key=key,
        )


@pytest.fixture
def stub():
    state = _LicenseChainStub()
    state.licenses[GOOD_KEY] = {
        "id": "lic_good",
        "email": EMAIL,
        "status": "ACTIVE",
        "expiresAt": None,
        "productId": PRODUCT_ID,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _send(self, code: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):  # noqa: N802
            state.calls.append(f"GET {self.path}")
            if not state.online:
                return self._send(503, {"error": "down"})
            if self.path == "/v1/licenses/jwks":
                return self._send(200, state.jwks())
            self._send(404, {"error": "nope"})

        def do_POST(self):  # noqa: N802
            body = self._json()
            state.calls.append(f"POST {self.path}")
            if not state.online:
                return self._send(503, {"error": "down"})
            if self.path == "/v1/licenses/verify":
                rec = state.licenses.get(body.get("key", ""))
                if rec is None:
                    return self._send(
                        200, {"valid": False, "reason": "License key not found"}
                    )
                if rec["status"] != "ACTIVE":
                    return self._send(
                        200,
                        {"valid": False, "reason": f"License is {rec['status'].lower()}"},
                    )
                if rec["expiresAt"]:
                    exp = datetime.fromisoformat(rec["expiresAt"])
                    if exp < datetime.now(timezone.utc):
                        return self._send(
                            200, {"valid": False, "reason": "License has expired"}
                        )
                out = {
                    "valid": True,
                    "status": rec["status"],
                    "expiresAt": rec["expiresAt"],
                    "email": rec["email"],
                    "verificationType": "basic",
                }
                if rec.get("signed"):
                    out["license_token"] = state.token(
                        rec["id"], key=rec.get("signing_key")
                    )
                return self._send(200, out)
            if self.path == "/api/checkout/mirror/validate":
                rec = state.licenses.get(body.get("license", ""))
                if (
                    rec is None
                    or (rec["email"] or "").lower() != str(body.get("email", "")).lower()
                ):
                    return self._send(
                        200, {"success": True, "verified": False, "status": "not_found"}
                    )
                return self._send(
                    200,
                    {
                        "success": True,
                        "verified": True,
                        "status": "successful",
                        "purchase": {"id": rec["id"], "productId": rec["productId"]},
                    },
                )
            self._send(404, {"error": "nope"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def gate(stub, isolated_secure_store):
    store, _ = isolated_secure_store
    clock = _Clock()
    client = LicenseChainClient(api_base=f"{stub.base}/v1", pay_base=stub.base, timeout=5)
    return PluginLicenseGate(store=store, client=client, clock=clock, use_hwuid=True), clock


def _requirement():
    manifest = validate_manifest(_manifest_dict())
    assert manifest.license is not None
    return manifest.license


def _manifest_dict(**overrides) -> dict:
    data = {
        "id": "pro_report",
        "name": "Pro Report",
        "version": "1.0.0",
        "author": "VoxHash Technologies",
        "description": "Premium reporting plugin",
        "plugin_type": "custom",
        "entry": "plugin:ProReport",
        "license": {"product_id": PRODUCT_ID},
    }
    data.update(overrides)
    return data


PLUGIN_SOURCE = '''
from db_storage_manager.plugins.sdk import Plugin


class ProReport(Plugin):
    def initialize(self, context):
        return True

    def execute(self, *args, **kwargs):
        return {"status": "success", "ran": True}

    def cleanup(self):
        pass
'''


def _write_plugin(root: Path, manifest: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(manifest or _manifest_dict()), encoding="utf-8"
    )
    (root / "plugin.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    return root


# --- manifest ---------------------------------------------------------------


def test_manifest_license_block_defaults_and_roundtrip():
    manifest = validate_manifest(_manifest_dict())
    assert manifest.license.product_id == PRODUCT_ID
    assert manifest.license.purchase_url == f"{LICENSECHAIN_CHECKOUT_BASE}/{PRODUCT_ID}"
    assert manifest.to_dict()["license"]["product_id"] == PRODUCT_ID


def test_manifest_without_license_is_free_and_has_no_license_key():
    data = _manifest_dict()
    del data["license"]
    manifest = validate_manifest(data)
    assert manifest.license is None
    assert "license" not in manifest.to_dict()


@pytest.mark.parametrize(
    "block",
    [
        "string",
        {"product_id": ""},
        {"product_id": "has space"},
        {"product_id": PRODUCT_ID, "provider": "other"},
        {"product_id": PRODUCT_ID, "purchase_url": "http://insecure.example"},
        {"product_id": PRODUCT_ID, "required": "yes"},
    ],
)
def test_manifest_rejects_bad_license_block(block):
    with pytest.raises(ManifestError):
        validate_manifest(_manifest_dict(license=block))


def test_manifest_required_false_is_free():
    manifest = validate_manifest(
        _manifest_dict(license={"required": False, "product_id": PRODUCT_ID})
    )
    assert manifest.license is None


# --- gate -------------------------------------------------------------------


def test_activate_stores_key_in_securestore_only(gate, isolated_secure_store):
    g, _ = gate
    store, data_dir = isolated_secure_store
    result = g.activate("pro_report", _requirement(), GOOD_KEY)
    assert result.allowed and result.state == "licensed"
    assert GOOD_KEY not in json.dumps(result.to_dict())
    assert result.masked_key == mask_license_key(GOOD_KEY)
    saved = store.get_plugin_licenses()["pro_report"]
    assert saved["license_key"] == GOOD_KEY
    assert saved["product_id"] == PRODUCT_ID
    raw = (data_dir / "plugin-licenses.enc").read_text(encoding="utf-8")
    assert GOOD_KEY not in raw and EMAIL not in raw


def test_activate_rejects_unknown_key_and_wrong_product(gate, stub):
    g, _ = gate
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), "LC-NOPE-NOPE-NOPE")
    assert exc.value.code == "invalid"

    stub.licenses["LC-OTHER-PRODUCT-1"] = {
        "id": "lic_other",
        "email": EMAIL,
        "status": "ACTIVE",
        "expiresAt": None,
        "productId": OTHER_PRODUCT_ID,
    }
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), "LC-OTHER-PRODUCT-1")
    assert exc.value.code == "mismatch"


def test_activate_rejects_revoked_expired_and_blank(gate, stub):
    g, _ = gate
    stub.licenses["LC-REVOKED-0001"] = {
        "id": "lic_r",
        "email": EMAIL,
        "status": "REVOKED",
        "expiresAt": None,
        "productId": PRODUCT_ID,
    }
    stub.licenses["LC-EXPIRED-0001"] = {
        "id": "lic_e",
        "email": EMAIL,
        "status": "ACTIVE",
        "expiresAt": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "productId": PRODUCT_ID,
    }
    with pytest.raises(PluginLicenseError):
        g.activate("pro_report", _requirement(), "LC-REVOKED-0001")
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), "LC-EXPIRED-0001")
    assert exc.value.code == "expired"
    for bad in ("", "   ", "has space", "x" * 600):
        with pytest.raises(PluginLicenseError):
            g.activate("pro_report", _requirement(), bad)


def test_email_required_when_license_has_no_email(gate, stub):
    g, _ = gate
    stub.licenses["LC-NOEMAIL-0001"] = {
        "id": "lic_n",
        "email": None,
        "status": "ACTIVE",
        "expiresAt": None,
        "productId": PRODUCT_ID,
    }
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), "LC-NOEMAIL-0001")
    assert exc.value.code == "email_required"
    # supplying an email that does not match the purchase is rejected too
    with pytest.raises(PluginLicenseError):
        g.activate("pro_report", _requirement(), "LC-NOEMAIL-0001", "other@example.com")


def test_signed_license_token_is_verified_against_jwks(gate, stub):
    g, _ = gate
    stub.licenses[GOOD_KEY]["signed"] = True
    result = g.activate("pro_report", _requirement(), GOOD_KEY)
    assert result.allowed
    assert "GET /v1/licenses/jwks" in stub.calls


def test_forged_license_token_is_rejected(gate, stub):
    g, _ = gate
    stub.licenses[GOOD_KEY]["signed"] = True
    stub.licenses[GOOD_KEY]["signing_key"] = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), GOOD_KEY)
    assert "signature" in str(exc.value)


def test_verify_license_token_checks_purpose_and_expiry(stub):
    jwks = stub.jwks()
    good = stub.token("lic_1")
    assert verify_license_token(good, jwks)["sub"] == "lic_1"
    wrong_purpose = stub.sign(
        {"sub": "x", "token_use": "access", "exp": int(time.time()) + 60}
    )
    with pytest.raises(PluginLicenseError):
        verify_license_token(wrong_purpose, jwks)
    expired = stub.token("lic_1", ttl=-10)
    with pytest.raises(PluginLicenseError) as exc:
        verify_license_token(expired, jwks)
    assert exc.value.code == "expired"
    with pytest.raises(PluginLicenseError):
        verify_license_token("not.a.jwt.at.all", jwks)


def test_status_uses_cache_then_revalidates_then_grace(gate, stub):
    g, clock = gate
    req = _requirement()
    assert g.status("pro_report", req).state == "missing"
    g.activate("pro_report", req, GOOD_KEY)

    stub.calls.clear()
    assert g.status("pro_report", req).state == "licensed"
    assert stub.calls == []  # fresh cache -> no network

    clock.advance(hours=25)
    stub.calls.clear()
    assert g.status("pro_report", req).state == "licensed"
    assert "POST /v1/licenses/verify" in stub.calls  # revalidated

    stub.online = False
    clock.advance(hours=25)
    offline = g.status("pro_report", req)
    assert offline.state == "grace" and offline.allowed

    clock.advance(days=8)
    lapsed = g.status("pro_report", req)
    assert lapsed.state == "unverified" and not lapsed.allowed
    # cache-only mode never touches the network
    stub.calls.clear()
    g.status("pro_report", req, network=False)
    assert stub.calls == []


def test_revocation_is_picked_up_and_sticks_offline(gate, stub):
    g, clock = gate
    req = _requirement()
    g.activate("pro_report", req, GOOD_KEY)
    stub.licenses[GOOD_KEY]["status"] = "REVOKED"
    clock.advance(hours=30)
    revoked = g.status("pro_report", req)
    assert revoked.state == "invalid" and not revoked.allowed
    stub.online = False
    assert not g.status("pro_report", req).allowed  # no offline resurrection
    with pytest.raises(PluginLicenseError):
        g.require("pro_report", req)


def test_expiry_date_in_cache_denies_without_network(gate, stub):
    g, clock = gate
    req = _requirement()
    soon = clock.now + timedelta(days=2)
    stub.licenses[GOOD_KEY]["expiresAt"] = soon.isoformat()
    g.activate("pro_report", req, GOOD_KEY)
    clock.advance(days=3)
    stub.online = False
    assert g.status("pro_report", req).state == "expired"


def test_require_raises_required_when_missing_and_free_passes(gate):
    g, _ = gate
    with pytest.raises(PluginLicenseRequired):
        g.require("pro_report", _requirement())
    assert g.require("free_plugin", None).state == "not_required"


def test_deactivate_removes_stored_key(gate, isolated_secure_store):
    g, _ = gate
    store, _ = isolated_secure_store
    g.activate("pro_report", _requirement(), GOOD_KEY)
    assert g.deactivate("pro_report") is True
    assert store.get_plugin_licenses() == {}
    assert g.deactivate("pro_report") is False


def test_client_rejects_insecure_remote_base():
    with pytest.raises(PluginLicenseError):
        LicenseChainClient(api_base="http://api.licensechain.app/v1")
    with pytest.raises(PluginLicenseError):
        LicenseChainClient(pay_base="ftp://pay.example")


def test_client_network_error_is_distinct():
    client = LicenseChainClient(
        api_base="http://127.0.0.1:9/v1", pay_base="http://127.0.0.1:9", timeout=1
    )
    with pytest.raises(LicenseNetworkError):
        client.verify("LC-ANY")


def test_live_licensechain_rejects_unknown_key():
    """Real LicenseChain API: an unknown key is cleanly reported as invalid."""
    client = LicenseChainClient(timeout=15)
    try:
        resp = client.verify("LC-DSM-TEST-UNKNOWN-0000")
    except LicenseNetworkError:
        pytest.skip("LicenseChain not reachable from this machine")
    assert resp.get("valid") is False


# --- marketplace integration ------------------------------------------------


@pytest.fixture
def market(tmp_path, monkeypatch, isolated_secure_store, gate):
    g, _clock = gate
    store, data_dir = isolated_secure_store
    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "PLUGINS_DIR", plugins_dir)
    mp = LocalPluginMarketplace(
        plugins_dir=plugins_dir, manager=PluginManager(), license_gate=g
    )
    return mp, g


def test_builtins_stay_free(market):
    mp, _ = market
    rows = {r["id"]: r for r in mp.list_installed()}
    for plugin_id in ("migration", "data_comparison"):
        assert rows[plugin_id]["license"] is None
        assert mp.license_status(plugin_id).state == "not_required"
        mp.set_enabled(plugin_id, True)
    mp.load_into_manager()
    assert mp.manager.get_plugin("migration") is not None


def test_builtin_id_cannot_acquire_license_requirement(market):
    mp, _ = market
    mp.sync_builtins()
    data = mp._read_registry()
    data["plugins"]["migration"]["manifest"]["license"] = {
        "required": True,
        "product_id": PRODUCT_ID,
    }
    mp._write_registry(data)
    assert mp.license_requirement("migration") is None


def test_free_third_party_plugin_installs_without_license(market, tmp_path):
    mp, _ = market
    manifest = _manifest_dict(id="free_echo")
    del manifest["license"]
    src = _write_plugin(tmp_path / "free_echo", manifest)
    row = mp.install_from_path(src)
    assert row["license"] is None
    assert mp.manager.execute_plugin("free_echo")["ran"] is True


def test_premium_install_requires_license_and_runs_nothing_before(market, tmp_path):
    mp, _ = market
    marker = tmp_path / "imported.marker"
    src = _write_plugin(tmp_path / "pro_report")
    (src / "plugin.py").write_text(
        f"open({str(marker)!r}, 'w').write('x')\n" + PLUGIN_SOURCE, encoding="utf-8"
    )
    with pytest.raises(PluginLicenseRequired):
        mp.install_from_path(src)
    assert not marker.exists(), "plugin code must not import before the license check"
    assert "pro_report" not in {r["id"] for r in mp.list_installed()}

    with pytest.raises(PluginLicenseError):
        mp.install_from_path(src, license_key="LC-NOPE-NOPE-NOPE")
    assert not marker.exists()


def test_premium_install_enable_run_and_deactivate(market, tmp_path):
    mp, g = market
    src = _write_plugin(tmp_path / "pro_report")
    row = mp.install_from_path(src, license_key=GOOD_KEY)
    assert row["license"]["product_id"] == PRODUCT_ID
    assert mp.license_status("pro_report").allowed
    assert mp.manager.execute_plugin("pro_report")["ran"] is True

    # deactivating the license blocks enable + execution
    mp.deactivate_license("pro_report")
    assert mp.manager.is_enabled("pro_report") is False
    with pytest.raises(PluginLicenseRequired):
        mp.set_enabled("pro_report", True)
    mp.manager.set_enabled("pro_report", True)
    with pytest.raises(PluginLicenseRequired):
        mp.manager.execute_plugin("pro_report")

    # re-activate through the marketplace API
    status = mp.activate_license("pro_report", GOOD_KEY)
    assert status.allowed
    mp.set_enabled("pro_report", True)
    assert mp.manager.execute_plugin("pro_report")["ran"] is True


def test_load_into_manager_skips_unlicensed_premium(market, tmp_path):
    mp, g = market
    src = _write_plugin(tmp_path / "pro_report")
    mp.install_from_path(src, license_key=GOOD_KEY)
    g.deactivate("pro_report")

    fresh = LocalPluginMarketplace(
        plugins_dir=mp.plugins_dir, manager=PluginManager(), license_gate=g
    )
    fresh.load_into_manager()
    assert fresh.manager.get_plugin("pro_report") is None
    assert fresh.manager.get_plugin("migration") is not None


def test_malformed_license_block_in_registry_fails_closed(market, tmp_path):
    mp, _ = market
    src = _write_plugin(tmp_path / "pro_report")
    mp.install_from_path(src, license_key=GOOD_KEY)
    data = mp._read_registry()
    data["plugins"]["pro_report"]["manifest"]["license"] = "garbage"
    mp._write_registry(data)
    assert mp.license_requirement("pro_report") is not None
    assert not mp.license_status("pro_report").allowed


def test_activate_license_on_free_plugin_is_rejected(market):
    mp, _ = market
    with pytest.raises(PluginLicenseError):
        mp.activate_license("migration", GOOD_KEY)


# --- bundle licences --------------------------------------------------------

from db_storage_manager.plugins.manifest import LicenseRequirement  # noqa: E402
from db_storage_manager.plugins.pricing import (  # noqa: E402
    BUNDLE_PRODUCT_IDS,
    PREMIUM_PRODUCT_IDS,
    accepted_product_ids,
)

PLUGIN_ONLY_ID = PREMIUM_PRODUCT_IDS["pitr-verify"]["monthly"]
BUNDLE_KEY = "LC-TEST-BUNDLE-KEY1"


def _premium_requirements():
    """(plugin, option, requirement) for every first-party premium product."""
    return [
        (plugin, option, LicenseRequirement(product_id=pid))
        for plugin, options in PREMIUM_PRODUCT_IDS.items()
        if plugin != "bundle"
        for option, pid in options.items()
    ]


def _add_license(stub, key, product_id, **extra):
    stub.licenses[key] = {
        "id": f"lic_{key.lower()}",
        "email": EMAIL,
        "status": "ACTIVE",
        "expiresAt": None,
        "productId": product_id,
        **extra,
    }


def test_accepted_product_ids_policy():
    assert accepted_product_ids(PLUGIN_ONLY_ID) == {PLUGIN_ONLY_ID} | BUNDLE_PRODUCT_IDS
    assert accepted_product_ids(PRODUCT_ID) == {PRODUCT_ID}  # third party: own id only
    assert len(BUNDLE_PRODUCT_IDS) == 3


def test_plugin_only_key_unlocks_just_that_plugin(gate, stub):
    g, _ = gate
    _add_license(stub, "LC-TEST-PITR-KEY1", PLUGIN_ONLY_ID)
    req = LicenseRequirement(product_id=PLUGIN_ONLY_ID)
    assert g.activate("pitr-verify", req, "LC-TEST-PITR-KEY1").allowed
    assert g.status("pitr-verify", req).allowed

    other = LicenseRequirement(product_id=PREMIUM_PRODUCT_IDS["schema-drift"]["monthly"])
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("schema-drift", other, "LC-TEST-PITR-KEY1")
    assert exc.value.code == "mismatch"
    assert not g.status("schema-drift", other).allowed


@pytest.mark.parametrize("option", ["monthly", "yearly", "one_time"])
def test_bundle_key_unlocks_every_premium_plugin(gate, stub, option):
    g, _ = gate
    _add_license(stub, BUNDLE_KEY, PREMIUM_PRODUCT_IDS["bundle"][option])
    for plugin, _opt, req in _premium_requirements():
        result = g.activate(plugin, req, BUNDLE_KEY)
        assert result.allowed and result.state == "licensed", (plugin, _opt)
        assert g.status(plugin, req, network=False).allowed
    saved = g.store.get_plugin_licenses()["pitr-verify"]
    assert saved["product_id"] == PREMIUM_PRODUCT_IDS["bundle"][option]


def test_bundle_key_does_not_unlock_third_party_plugin(gate, stub):
    g, _ = gate
    _add_license(stub, BUNDLE_KEY, PREMIUM_PRODUCT_IDS["bundle"]["monthly"])
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pro_report", _requirement(), BUNDLE_KEY)
    assert exc.value.code == "mismatch"


def test_bundle_key_invalid_expired_revoked_still_block(gate, stub):
    g, clock = gate
    req = LicenseRequirement(product_id=PLUGIN_ONLY_ID)
    bundle_id = PREMIUM_PRODUCT_IDS["bundle"]["yearly"]

    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pitr-verify", req, "LC-NOPE-NOPE-NOPE")
    assert exc.value.code == "invalid"

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _add_license(stub, "LC-TEST-OLD-BUNDLE", bundle_id, expiresAt=past)
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pitr-verify", req, "LC-TEST-OLD-BUNDLE")
    assert exc.value.code == "expired"

    _add_license(stub, "LC-TEST-REVOKED-BDL", bundle_id, status="REVOKED")
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pitr-verify", req, "LC-TEST-REVOKED-BDL")
    assert exc.value.code == "invalid"

    # an active bundle key that is later revoked / expires stops unlocking
    _add_license(stub, BUNDLE_KEY, bundle_id)
    assert g.activate("pitr-verify", req, BUNDLE_KEY).allowed
    stub.licenses[BUNDLE_KEY]["status"] = "REVOKED"
    clock.advance(hours=25)
    assert not g.status("pitr-verify", req).allowed
    stub.licenses[BUNDLE_KEY]["status"] = "ACTIVE"
    soon = clock.now + timedelta(days=2)
    stub.licenses[BUNDLE_KEY]["expiresAt"] = soon.isoformat()
    assert g.activate("pitr-verify", req, BUNDLE_KEY).allowed
    clock.advance(days=3)
    assert g.status("pitr-verify", req, network=False).state == "expired"


def test_stored_license_for_other_product_is_still_a_mismatch(gate, stub):
    g, _ = gate
    _add_license(stub, "LC-TEST-OTHER-KEY1", OTHER_PRODUCT_ID)
    req = LicenseRequirement(product_id=PLUGIN_ONLY_ID)
    with pytest.raises(PluginLicenseError) as exc:
        g.activate("pitr-verify", req, "LC-TEST-OTHER-KEY1")
    assert exc.value.code == "mismatch"


def test_bundle_key_unlocks_premium_plugin_via_marketplace(market, stub, tmp_path):
    mp, _ = market
    _add_license(stub, BUNDLE_KEY, PREMIUM_PRODUCT_IDS["bundle"]["monthly"])
    manifest = _manifest_dict(license={"product_id": PLUGIN_ONLY_ID})
    src = _write_plugin(tmp_path / "pro_report", manifest)
    with pytest.raises(PluginLicenseRequired):
        mp.install_from_path(src)
    mp.install_from_path(src, license_key=BUNDLE_KEY)
    assert mp.license_status("pro_report").allowed
    assert mp.manager.execute_plugin("pro_report")["ran"] is True


def test_free_builtins_never_contact_licensechain_even_with_bundle(market, stub):
    mp, g = market
    _add_license(stub, BUNDLE_KEY, PREMIUM_PRODUCT_IDS["bundle"]["monthly"])
    stub.calls.clear()
    for plugin_id in ("migration", "data_comparison"):
        assert mp.license_status(plugin_id).state == "not_required"
        assert g.status(plugin_id, None).allowed
    assert stub.calls == []
