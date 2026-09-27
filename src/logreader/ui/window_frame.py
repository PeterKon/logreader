"""Native Windows title-bar colors."""

import ctypes
from ctypes import wintypes
from math import ceil, erfc, sqrt
import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .theme import THEME_COLORS


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


class TitleBarShadow(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("titleBarShadow")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Match the mockup's 3 px blur, 2 px offset, and 30% black shadow.
        sigma = 3 / 2
        offset = 2
        height = ceil(offset + 3 * sigma)
        self.setFixedHeight(height)
        self._gradient = QLinearGradient(0, 0, 0, height)
        for y in range(height):
            opacity = 0.3 * erfc((y - offset) / (sqrt(2) * sigma)) / 2
            self._gradient.setColorAt(y / height, QColor(0, 0, 0, round(255 * opacity)))
        self._gradient.setColorAt(1, QColor(0, 0, 0, 0))
        parent.installEventFilter(self)
        self.setGeometry(0, 0, parent.width(), height)
        self.raise_()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show,
        ):
            self.setGeometry(0, 0, watched.width(), self.height())
            self.raise_()
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._gradient)


def apply_title_bar_colors(window: QWidget) -> None:
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return
    handle = window.internalWinId()
    if not handle or sys.getwindowsversion().build < 22000:
        return

    set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
    set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    set_attribute.restype = ctypes.c_long

    active = window.isActiveWindow()
    colors = (
        (DWMWA_BORDER_COLOR, "ui_border_strong" if active else "ui_border"),
        (DWMWA_CAPTION_COLOR, "ui_caption"),
        (DWMWA_TEXT_COLOR, "ui_text" if active else "ui_muted"),
    )
    dark_mode = wintypes.BOOL(True)
    set_attribute(handle, DWMWA_USE_IMMERSIVE_DARK_MODE,
                  ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
    for attribute, role in colors:
        rgb = int(THEME_COLORS[role].removeprefix("#"), 16)
        # COLORREF stores red in the low byte, unlike an RGB hex color.
        color = wintypes.DWORD(((rgb & 0xff) << 16) | (rgb & 0xff00) | (rgb >> 16))
        # Unsupported attributes leave the native appearance in place.
        set_attribute(handle, attribute, ctypes.byref(color), ctypes.sizeof(color))
