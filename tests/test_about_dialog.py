"""About keeps Check for Updates and Copy version info, and has no OK button."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from db_storage_manager.gui.about import AboutDialog  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_about_has_no_ok_button(app):
    dialog = AboutDialog()
    labels = [button.text() for button in (dialog.check_button, dialog.copy_button)]
    assert any("Update" in label for label in labels)
    assert any("Copy" in label or "version" in label.lower() for label in labels)
    assert not hasattr(dialog, "close_button")
    dialog.close()
