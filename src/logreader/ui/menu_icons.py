from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import THEME_COLORS


def stroke(path, *points):
    path.moveTo(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))


SAVE_PATH = QPainterPath()
stroke(SAVE_PATH, (11, 1.5), (12.5, 3), (12.5, 12.5), (1.5, 12.5), (1.5, 1.5), (11, 1.5))
stroke(SAVE_PATH, (4, 1.5), (4, 5), (9.5, 5), (9.5, 1.5))
stroke(SAVE_PATH, (4, 12.5), (4, 8), (10, 8), (10, 12.5))

FOLDER_PATH = QPainterPath()
stroke(FOLDER_PATH, (1.5, 11.5), (1.5, 2.5), (5, 2.5), (6.5, 4), (12, 4), (12, 6))
stroke(FOLDER_PATH, (1.5, 11.5), (3.5, 6), (13, 6), (11, 11.5), (1.5, 11.5))


def menu_icon(path: QPainterPath) -> QIcon:
    icon = QIcon()
    for enabled in (True, False):
        color = QColor(THEME_COLORS["ui_muted" if enabled else "ui_disabled_text"])
        for scale in (1, 2, 3):
            pixmap = QPixmap(16 * scale, 16 * scale)
            pixmap.setDevicePixelRatio(scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(1, 1)
            painter.setPen(QPen(color, 1.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.end()
            modes = (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected) if enabled else (QIcon.Mode.Disabled,)
            for mode in modes:
                icon.addPixmap(pixmap, mode)
    return icon
