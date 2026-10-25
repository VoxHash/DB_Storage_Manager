"""
Library-style left navigation for the desktop shell.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class NavSidebar(QFrame):
    """Dense left rail: brand header + exclusive nav buttons."""

    navigated = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(4)

        self.brand = QLabel("DB Storage Manager")
        self.brand.setObjectName("NavBrand")
        self.brand.setWordWrap(True)
        layout.addWidget(self.brand)

        self.caption = QLabel("VoxHash")
        self.caption.setObjectName("NavCaption")
        layout.addWidget(self.caption)

        layout.addSpacing(12)

        self.section = QLabel()
        self.section.setObjectName("NavSection")
        layout.addWidget(self.section)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: List[QPushButton] = []
        self._group.idClicked.connect(self._on_id_clicked)

        self._nav_host = QWidget()
        self._nav_layout = QVBoxLayout(self._nav_host)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(2)
        layout.addWidget(self._nav_host)

        layout.addStretch(1)

        self.footer = QLabel()
        self.footer.setObjectName("NavFooter")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)

    def set_items(self, items: Sequence[Tuple[str, str]]) -> None:
        """Replace nav entries. Each item is (object_name_suffix, label)."""
        while self._buttons:
            btn = self._buttons.pop()
            self._group.removeButton(btn)
            self._nav_layout.removeWidget(btn)
            btn.deleteLater()

        for index, (_key, label) in enumerate(items):
            btn = QPushButton(label)
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._group.addButton(btn, index)
            self._nav_layout.addWidget(btn)
            self._buttons.append(btn)

        if self._buttons:
            self._buttons[0].setChecked(True)

    def set_section_label(self, text: str) -> None:
        self.section.setText(text)

    def set_footer(self, text: str) -> None:
        self.footer.setText(text)

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            btn = self._buttons[index]
            if not btn.isChecked():
                btn.setChecked(True)

    def set_labels(self, labels: Sequence[str]) -> None:
        for btn, label in zip(self._buttons, labels):
            btn.setText(label)

    def _on_id_clicked(self, index: int) -> None:
        self.navigated.emit(index)
