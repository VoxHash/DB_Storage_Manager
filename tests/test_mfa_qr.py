"""TOTP enrolment QR matches the otpauth URI. The secret stays pending."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from db_storage_manager.security.auth import (  # noqa: E402
    AuthenticationManager,
    MFAProvider,
)
from db_storage_manager.security.mfa_qr import (  # noqa: E402
    png_modules,
    qr_modules,
    qr_png_bytes,
)


def test_qr_png_modules_match_the_otpauth_uri():
    secret = "JBSWY3DPEHPK3PXP"
    uri = MFAProvider.provisioning_uri(secret, "admin")
    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    png = qr_png_bytes(uri)
    assert png.startswith(b"\x89PNG")
    assert png_modules(png) == qr_modules(uri)
    other = qr_png_bytes(uri + "&x=1")
    assert png_modules(other) != qr_modules(uri)


def test_pending_secret_is_what_the_qr_encodes(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123", email="admin@localhost")
    auth.authenticate("admin", "password123")
    secret = auth.begin_mfa("admin")
    user = auth.get_user("admin")
    assert user.mfa_enabled is False
    assert user.mfa_pending_secret == secret
    uri = auth.mfa.provisioning_uri(secret, "admin")
    assert png_modules(qr_png_bytes(uri)) == qr_modules(uri)
    auth.cancel_mfa_enrollment("admin")
    assert auth.get_user("admin").mfa_pending_secret is None
    assert auth.get_user("admin").mfa_enabled is False


def test_enroll_dialog_shows_qr_and_manual_secret():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from db_storage_manager.gui.users import build_mfa_enroll_dialog

    app = QApplication.instance() or QApplication([])
    assert app is not None
    secret = "JBSWY3DPEHPK3PXP"
    uri = MFAProvider.provisioning_uri(secret, "admin")
    dialog = build_mfa_enroll_dialog(None, secret, uri)
    assert dialog.secret_edit.text() == secret
    assert dialog.uri_edit.text() == uri
    pixmap = dialog.qr_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    dialog.close()
