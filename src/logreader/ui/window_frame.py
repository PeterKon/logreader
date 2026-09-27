"""Native Windows title-bar colors."""

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtWidgets import QApplication, QWidget

from .theme import THEME_COLORS


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


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
        (DWMWA_CAPTION_COLOR, "ui_canvas"),
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
