"""Theme colors and small visual helpers for the Logreader interface."""

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit, QToolButton

THEME_COLORS = {
    # Keep the controls area visibly raised above the results well, with its
    # nested islands another step lighter.
    "ui_canvas": "#202b38",
    "ui_surface": "#202b38",
    "ui_island": "#2f3e50",
    "ui_field": "#202b38",
    "ui_border": "#344255",
    "ui_border_strong": "#53657a",
    "ui_text": "#e6edf3",
    "ui_muted": "#9aa7b5",
    "ui_accent": "#79c0ff",
    "ui_button": "#263445",
    "ui_button_hover": "#32445a",
    "ui_button_pressed": "#1d2937",
    "ui_open_tab": "#384b60",
    "ui_primary": "#1f6feb",
    "ui_primary_hover": "#185fc7",
    "ui_disabled": "#151d27",
    "ui_disabled_text": "#778392",
    "background": "#0d1117",
    "body": "#d8dee9",
    "border": "#30363d",
    "selection": "#264f78",
    "search_current": "#f2cc60",
    "muted": "#8b949e",
    "scrollbar_track": "#161b22",
    "scrollbar_handle": "#6e7681",
    "scrollbar_handle_hover": "#8b949e",
    "heading": "#d2a8ff",
    "match": "#ff7b72",
    "matched_text": "#7ee787",
    "line_number": "#79c0ff",
    "hit_count": "#ff7b72",
    "limit_notice": "#79c0ff",
}


def vertical_resize_icon(*, contract: bool = False) -> QIcon:
    """Draw opposing vertical arrows, with crisp variants for high-DPI screens."""

    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(18 * scale, 18 * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(THEME_COLORS["ui_text"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # Expansion arrows share a continuous shaft; contraction arrows retain
        # a gap between their inward-facing heads so the direction stays clear.
        arrows = ((7, 1.5), (11, 16.5)) if contract else ((1.5, 9), (16.5, 9))
        for tip, tail in arrows:
            wing = tip + (2.5 if tail > tip else -2.5)
            painter.drawLine(QPointF(9, tail), QPointF(9, tip))
            painter.drawLine(QPointF(6.5, wing), QPointF(9, tip))
            painter.drawLine(QPointF(11.5, wing), QPointF(9, tip))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def configure_clear_button(line_edit: QLineEdit) -> None:
    """Enable a line edit's clear action with a high-contrast white glyph."""

    line_edit.setClearButtonEnabled(True)
    clear_button = line_edit.findChild(QToolButton)
    if clear_button is None:
        return

    icon_size = QSize(12, 12)
    icon_pixmap = QPixmap(icon_size)
    icon_pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(icon_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 1.75)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(2.5, 2.5), QPointF(9.5, 9.5))
    painter.drawLine(QPointF(9.5, 2.5), QPointF(2.5, 9.5))
    painter.end()

    clear_button.setObjectName(f"{line_edit.objectName()}ClearButton")
    clear_button.setIcon(QIcon(icon_pixmap))
    clear_button.setIconSize(icon_size)
