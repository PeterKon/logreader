"""Inline recovery controls for a saved tab whose source cannot be loaded."""

from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from .theme import THEME_COLORS, configure_action_button


class UnavailableFileWarning(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("unavailableFileWarning")
        self.setStyleSheet(f"""
            QFrame#unavailableFileWarning {{ background: {THEME_COLORS['ui_island']};
                border-left: 3px solid {THEME_COLORS['limit_notice']}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(3)
        title = QLabel("File unavailable")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        self._failure = ""
        self.message = QTextEdit()
        self.message.setAccessibleName("File load details")
        self.message.setReadOnly(True)
        self.message.setTabChangesFocus(True)
        self.message.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.message.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message.setStyleSheet(f"background: transparent; color: {THEME_COLORS['ui_text']}; border: none;")
        self.message.document().setDocumentMargin(0)
        self.message.document().documentLayout().documentSizeChanged.connect(self._fit_message)
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        self.retry = QPushButton("Retry")
        self.replace = QPushButton("Replace file…")
        for button in (self.retry, self.replace):
            configure_action_button(button)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.hide()

    def show_failure(self, path: Path, reason: str):
        self._failure = f"{path}\n{reason}"
        self.set_detail("")
        self.show()

    def set_detail(self, message: str, *, busy: bool = False):
        self.message.setPlainText(f"{self._failure}\n{message}" if message else self._failure)
        self.retry.setEnabled(not busy)
        self.replace.setEnabled(not busy)

    def _fit_message(self, size):
        # Exceptionally long paths can scroll without pushing the actions offscreen.
        self.message.setFixedHeight(min(ceil(size.height()), 8 * self.message.fontMetrics().lineSpacing()))
