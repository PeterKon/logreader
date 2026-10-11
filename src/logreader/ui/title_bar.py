"""Qt menus in a Windows frame with native caption controls."""

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMenuBar, QWidget,
)

from .theme import THEME_COLORS as COLORS
from .window_frame import apply_menu_corners


WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
HTCLIENT, HTCAPTION, HTSYSMENU = 1, 2, 3
HTMINBUTTON, HTMAXBUTTON, HTTOP, HTCLOSE = 8, 9, 12, 20
SM_CYFRAME, SM_CYCAPTION, SM_CXPADDEDBORDER = 33, 4, 92


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]


class _CalcSize(ctypes.Structure):
    _fields_ = [("rects", wintypes.RECT * 3), ("window_pos", ctypes.c_void_p)]


class _WindowsFrame:
    def __init__(self) -> None:
        self.user = ctypes.WinDLL("user32")
        self.dwm = ctypes.WinDLL("dwmapi")
        self.user.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        self.user.DefWindowProcW.restype = ctypes.c_ssize_t
        self.user.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        self.user.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user.GetDpiForWindow.restype = wintypes.UINT
        self.user.IsZoomed.argtypes = [wintypes.HWND]
        self.user.IsZoomed.restype = wintypes.BOOL
        self.user.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        self.dwm.DwmDefWindowProc.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ctypes.POINTER(ctypes.c_ssize_t),
        ]
        self.dwm.DwmDefWindowProc.restype = wintypes.BOOL
        self.dwm.DwmExtendFrameIntoClientArea.argtypes = [
            wintypes.HWND, ctypes.POINTER(_Margins),
        ]
        self.dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long

    def metrics(self, handle: int) -> tuple[int, int]:
        dpi = self.user.GetDpiForWindow(handle) or 96
        metric = self.user.GetSystemMetricsForDpi
        border = metric(SM_CYFRAME, dpi) + metric(SM_CXPADDEDBORDER, dpi)
        return border, metric(SM_CYCAPTION, dpi)


class _TitleMenu(QMenu):
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_menu_corners(self)


class _TitleMenus(QMenuBar):
    def event(self, event) -> bool:
        # Menu navigation must not erase the current log/loading status.
        if event.type() == QEvent.Type.StatusTip:
            return True
        return super().event(event)


def create_title_menus(parent: QWidget) -> QMenuBar:
    menus = _TitleMenus(parent)
    menus.setObjectName("titleMenus")
    menus.setNativeMenuBar(False)
    menus.setStyleSheet(f"""
        QMenuBar {{ background: transparent; color: {COLORS['ui_menu_text']}; border: none; }}
        QMenuBar::item {{
            padding: 4px 10px 2px 10px; background: transparent; border-radius: 3px;
        }}
        QMenuBar::item:selected {{
            background: {COLORS['ui_button_hover']}; color: {COLORS['ui_menu_text']};
        }}
        QMenuBar::item:pressed {{
            background: {COLORS['ui_button_hover']}; color: {COLORS['ui_text']};
        }}
        QMenu {{
            background: {COLORS['ui_button']}; color: {COLORS['ui_text']};
            border: 1px solid {COLORS['ui_border']};
            padding-left: 3px;
        }}
        QMenu::item {{ margin: 2px 0; padding: 3px 4px; border-radius: 3px; }}
        QMenu::item:selected:enabled {{ background: {COLORS['ui_button_hover']}; }}
        QMenu::item:disabled {{ color: {COLORS['ui_muted']}; }}
        QMenu::separator {{
            height: 1px; background: rgba(255, 255, 255, 55); margin: 3px 6px;
        }}
    """)
    for title in ("&File", "&View", "&Settings", "&Profiles", "&Help"):
        menu = _TitleMenu(title, menus)
        menus.addMenu(menu)
        menu.setObjectName(f"{title[1:].lower()}Menu")
        menu.addAction("Coming soon...").setEnabled(False)
    return menus


class TitleBarWindow(QMainWindow):
    def __init__(self) -> None:
        self._caption_api = None
        self._caption_bar = None
        super().__init__()

    def install_title_bar(self) -> None:
        self.title_menus = create_title_menus(self)
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            self.setMenuBar(self.title_menus)
            return

        self._caption_api = _WindowsFrame()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(self.styleSheet() + f"\nQMainWindow {{background: {COLORS['ui_caption']};}}")
        self._caption_bar = QWidget(self)
        self._caption_bar.setObjectName("captionBar")
        self._caption_bar.setStyleSheet(
            f"QWidget#captionBar {{background: {COLORS['ui_caption']};}}"
            f"QLabel {{color: {COLORS['ui_text']};}}"
        )
        layout = QHBoxLayout(self._caption_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._caption_icon = QLabel(self._caption_bar)
        self._caption_icon.setFixedWidth(21)
        layout.addWidget(self._caption_icon)
        self._caption_title = QLabel(self.windowTitle(), self._caption_bar)
        self._caption_title.setFont(QFont("Segoe UI", 9))
        layout.addWidget(self._caption_title)
        layout.addSpacing(12)
        divider = QFrame(self._caption_bar)
        divider.setFixedSize(1, 16)
        divider.setStyleSheet(f"background: {COLORS['ui_border']};")
        layout.addWidget(divider)
        layout.addSpacing(7)
        layout.addWidget(self.title_menus, 0, Qt.AlignmentFlag.AlignVCenter)

        self._caption_refresh = QTimer(self)
        self._caption_refresh.setSingleShot(True)
        self._caption_refresh.timeout.connect(self._refresh_caption)
        self.windowTitleChanged.connect(self._schedule_caption_refresh)
        self.windowIconChanged.connect(self._schedule_caption_refresh)
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED.
        self._caption_api.user.SetWindowPos(int(self.winId()), None, 0, 0, 0, 0, 0x27)
        self.windowHandle().screenChanged.connect(self._schedule_caption_refresh)
        self._refresh_caption()

    def _schedule_caption_refresh(self, *_args) -> None:
        self._caption_refresh.start(0)

    def _refresh_caption(self) -> None:
        if self.isMinimized():
            return
        handle = int(self.winId())
        border, caption = self._caption_api.metrics(handle)
        scale = self.devicePixelRatioF()
        maximized = bool(self._caption_api.user.IsZoomed(handle))
        self._caption_title.setText(self.windowTitle())
        self._caption_icon.setPixmap(self.windowIcon().pixmap(16, 16))
        self._caption_title.setStyleSheet(
            f"color: {COLORS['ui_text'] if self.isActiveWindow() else COLORS['ui_muted']};"
        )
        # Keep the client origin at the frame top for native DWM hit testing.
        # Windows puts the maximized resize border above the screen.
        self.setContentsMargins(0, round((caption + border) / scale), 0, 0)
        self._caption_bar.setGeometry(
            8, round(border / scale) if maximized else 0,
            min(self._caption_bar.sizeHint().width(), max(0, self.width() - 166)),
            round((caption + (0 if maximized else border)) / scale),
        )
        self._caption_bar.show()
        self._caption_bar.raise_()
        self._caption_api.dwm.DwmExtendFrameIntoClientArea(
            handle, ctypes.byref(_Margins(0, 0, caption + border, 0)),
        )
        self.update()

    def event(self, event) -> bool:
        result = super().event(event)
        if getattr(self, "_caption_refresh", None) is not None and event.type() in (
            QEvent.Type.Show, QEvent.Type.WindowStateChange, QEvent.Type.Resize,
            QEvent.Type.ActivationChange, QEvent.Type.ThemeChange,
            QEvent.Type.DevicePixelRatioChange,
        ):
            self._schedule_caption_refresh()
        return result

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._caption_api is not None:
            painter = QPainter(self)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            # Alpha zero makes this layered surface transparent to hover tracking.
            painter.fillRect(
                self.width() - 150, 0, 150, self.contentsMargins().top(), QColor(0, 0, 0, 1),
            )

    def nativeEvent(self, kind, message):  # noqa: N802
        api = self._caption_api
        if api is None:
            return super().nativeEvent(kind, message)
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            params = _CalcSize.from_address(msg.lParam)
            top = params.rects[0].top
            api.user.DefWindowProcW(msg.hWnd, msg.message, msg.wParam, msg.lParam)
            params.rects[0].top = top
            return True, 0

        # Include WM_NCMOUSELEAVE so Windows clears its own hover highlights.
        result = ctypes.c_ssize_t()
        if api.dwm.DwmDefWindowProc(
            msg.hWnd, msg.message, msg.wParam, msg.lParam, ctypes.byref(result),
        ):
            return True, result.value
        if msg.message == WM_NCHITTEST and self._caption_bar is not None:
            native_hit = api.user.DefWindowProcW(msg.hWnd, msg.message, msg.wParam, msg.lParam)
            if native_hit in (HTMINBUTTON, HTMAXBUTTON, HTCLOSE):
                return True, native_hit
            # Preserve native side/corner resizing before treating the title as draggable.
            if not api.user.IsZoomed(msg.hWnd) and 10 <= native_hit <= 17:
                return True, native_hit
            point = wintypes.POINT(
                ctypes.c_short(msg.lParam & 0xffff).value,
                ctypes.c_short((msg.lParam >> 16) & 0xffff).value,
            )
            api.user.ScreenToClient(msg.hWnd, ctypes.byref(point))
            scale = self.devicePixelRatioF()
            local = QPoint(round(point.x / scale), round(point.y / scale))
            if not api.user.IsZoomed(msg.hWnd) and 0 <= local.y() < 5:
                return True, HTTOP
            if 0 <= local.y() < self.contentsMargins().top():
                if local.x() < 28:
                    return True, HTSYSMENU
                menu_point = self.title_menus.mapFrom(self, local)
                return True, HTCLIENT if self.title_menus.actionAt(menu_point) else HTCAPTION
        return super().nativeEvent(kind, message)
