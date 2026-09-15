"""Shared fixed gutter for read-only source and results text."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .theme import THEME_COLORS


GUTTER_LEFT_PADDING = 2
GUTTER_RIGHT_PADDING = 4


class LineNumberArea(QWidget):
    def paintEvent(self, event) -> None:  # noqa: N802
        self.parent().paint_line_numbers(event)


class LineNumberEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.update_gutter_area)

    def source_number(self, block: int) -> int | None:
        raise NotImplementedError

    def largest_source_number(self) -> int:
        raise NotImplementedError

    def update_gutter(self, *_args) -> None:
        largest = self.largest_source_number()
        width = (
            self.fontMetrics().horizontalAdvance(str(largest))
            + GUTTER_LEFT_PADDING + GUTTER_RIGHT_PADDING
        ) if largest else 0
        if self.viewportMargins().left() != width:
            self.setViewportMargins(width, 0, 0, 0)
        viewport = self.viewport().geometry()
        self.gutter.setGeometry(viewport.left() - width, viewport.top(), width, viewport.height())
        self.gutter.update()

    def update_gutter_area(self, rect, dy: int) -> None:
        """Reuse scrolled gutter pixels and repaint only damaged rows."""
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update_gutter()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if hasattr(self, "gutter"):
            self.update_gutter()

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(THEME_COLORS["background"]))
        painter.setPen(QColor(THEME_COLORS["muted"]))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        while block.isValid():
            top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            if top > event.rect().bottom():
                break
            number = self.source_number(block.blockNumber())
            if block.isVisible() and number is not None:
                painter.drawText(
                    0, top, self.gutter.width() - GUTTER_RIGHT_PADDING, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(number),
                )
            block = block.next()
