"""Shared fixed gutter for read-only source and results text."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QTextBlock, QTextCursor, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .theme import THEME_COLORS


GUTTER_LEFT_PADDING = 2
GUTTER_RIGHT_PADDING = 4
BOOKMARK_MARKER_GAP = 3


class LineNumberArea(QWidget):
    def paintEvent(self, event) -> None:  # noqa: N802
        self.parent().paint_line_numbers(event)


class LineNumberEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        self._bookmark_blocks: dict[int, bool] = {}
        self._bookmark_selections = []
        self._transient_selections = []
        self._context_target: QTextBlock | None = None
        super().__init__(parent)
        self.gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.update_gutter_area)
        self.document().contentsChange.connect(self._context_contents_changed)

    def set_context_target(self, block: QTextBlock | None) -> None:
        self._context_target = block if block is not None and block.isValid() else None
        self.viewport().update()
        self.gutter.update()

    def _context_contents_changed(self, _position: int, removed: int, added: int) -> None:
        if self._context_target is not None and (removed or added):
            self.set_context_target(None)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.set_context_target(None)
        super().hideEvent(event)

    def _paint_context_target(self, painter: QPainter, width: int) -> None:
        block = self._context_target
        if block is None or not block.isValid() or not block.isVisible():
            return
        rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
        painter.setPen(QColor(THEME_COLORS["ui_accent"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0.5, rect.top() + 0.5, width - 1, max(0, rect.height() - 1)))

    def set_bookmarked_blocks(self, blocks: dict[int, bool]) -> None:
        """Compose persistent row decoration with search/navigation overlays."""
        self._bookmark_blocks = dict(blocks)
        self._bookmark_selections = []
        for number, preferred in blocks.items():
            block = self.document().findBlockByNumber(number)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(block)
            selection.cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                          QTextCursor.MoveMode.KeepAnchor)
            selection.format.setBackground(QColor(THEME_COLORS[
                "bookmark" if preferred else "bookmark_related"
            ]))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            self._bookmark_selections.append(selection)
            # A nonempty Qt selection stops at the final character, even with
            # FullWidthSelection. An empty selection there fills the last
            # visual row too, including after a wrapped line's final character.
            tail = QTextEdit.ExtraSelection()
            tail.cursor = QTextCursor(selection.cursor)
            tail.cursor.clearSelection()
            tail.format = selection.format
            self._bookmark_selections.append(tail)
        self.setExtraSelections(self._transient_selections)
        self.gutter.update()

    def setExtraSelections(self, selections) -> None:  # noqa: N802
        self._transient_selections = list(selections)
        super().setExtraSelections(self._bookmark_selections + self._transient_selections)

    def _clear_decorations(self) -> None:
        self.set_context_target(None)
        self._bookmark_blocks.clear()
        self._bookmark_selections.clear()
        self.setExtraSelections([])

    def clear(self) -> None:
        self._clear_decorations()
        super().clear()

    def setPlainText(self, text: str) -> None:  # noqa: N802
        self._clear_decorations()
        super().setPlainText(text)

    def source_number(self, block: int) -> int | None:
        raise NotImplementedError

    def largest_source_number(self) -> int:
        raise NotImplementedError

    def update_gutter(self, *_args) -> None:
        largest = self.largest_source_number()
        width = (
            self.fontMetrics().horizontalAdvance(str(largest))
            + GUTTER_LEFT_PADDING + BOOKMARK_MARKER_GAP + GUTTER_RIGHT_PADDING
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

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # Qt leaves the document's left margin outside nonempty selections.
        # Fill only that margin so the gutter and native row highlight meet.
        margin = max(0, round(self.contentOffset().x() + self.document().documentMargin()))
        painter = QPainter(self.viewport())
        painter.setClipRect(event.rect())
        if not margin or not self._bookmark_blocks:
            self._paint_context_target(painter, self.viewport().width())
            return
        block = self.firstVisibleBlock()
        while block.isValid():
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if rect.top() > event.rect().bottom():
                break
            if block.isVisible() and block.blockNumber() in self._bookmark_blocks:
                preferred = self._bookmark_blocks[block.blockNumber()]
                painter.fillRect(0, round(rect.top()), margin, round(rect.height()),
                                 QColor(THEME_COLORS["bookmark" if preferred else "bookmark_related"]))
            block = block.next()
        self._paint_context_target(painter, self.viewport().width())

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(THEME_COLORS["background"]))
        painter.setPen(QColor(THEME_COLORS["muted"]))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        while block.isValid():
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            top = round(rect.top())
            if top > event.rect().bottom():
                break
            if block.isVisible() and block.blockNumber() in self._bookmark_blocks:
                preferred = self._bookmark_blocks[block.blockNumber()]
                painter.fillRect(0, top, self.gutter.width(), round(rect.height()),
                                 QColor(THEME_COLORS["bookmark" if preferred else "bookmark_related"]))
                painter.fillRect(0, top + 2, GUTTER_LEFT_PADDING,
                                 max(2, self.fontMetrics().height() - 6),
                                 QColor(THEME_COLORS["bookmark_marker" if preferred else "bookmark_related_marker"]))
            number = self.source_number(block.blockNumber())
            if block.isVisible() and number is not None:
                painter.drawText(
                    0, top, self.gutter.width() - GUTTER_RIGHT_PADDING, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(number),
                )
            block = block.next()
        self._paint_context_target(painter, self.gutter.width())
