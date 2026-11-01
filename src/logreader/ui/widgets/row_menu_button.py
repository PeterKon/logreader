"""Shared three-dot button for row options."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget

from ..theme import THEME_COLORS


class RowMenuButton(QPushButton):
    def __init__(self, parent: QWidget, *, hover_color: str | None = None) -> None:
        super().__init__("⋯", parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(24, 16)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 3px;"
            f" color: {THEME_COLORS['ui_text']};"
            " font-size: 16px; padding: 0; min-height: 0; }"
            f"QPushButton:hover {{ background: {hover_color or THEME_COLORS['ui_button_hover']}; }}"
            f"QPushButton:pressed {{ background: {THEME_COLORS['ui_button_pressed']}; }}"
        )
        self.hide()
