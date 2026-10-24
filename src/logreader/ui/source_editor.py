"""Results interaction with source-specific clipboard text."""

from PySide6.QtCore import QPoint, Signal
from PySide6.QtGui import QColor, QFontDatabase

from .results.retained_editor import SparseResultsEditor
from .results.result_coordinates import TextPoint


class SourceEditor(SparseResultsEditor):
    reading_started = Signal()

    def __init__(self, presentation, parent=None):
        super().__init__(presentation, parent)
        self.setObjectName("sourceView")
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._formats["body"].setForeground(QColor("#ffffff"))

    def _reading_input(self, *_args):
        super()._reading_input(*_args)
        if not self._guard:
            self.reading_started.emit()

    def visible_ranges(self):
        # The caller consumes the complete viewport. Keep native block/cursor
        # access in one frame instead of suspending a generator between rows.
        visible = []
        height, width = self.viewport().height(), self.viewport().width()
        block = self.firstVisibleBlock()
        while block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            row = self.ranges.logical_at(block.blockNumber())
            if not isinstance(row, int):
                break
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if rect.top() >= height:
                break
            if rect.bottom() > 0:
                if self.lineWrapMode() == self.LineWrapMode.NoWrap:
                    y = max(0, min(height - 1, round(rect.top() + self.fontMetrics().height() / 2)))
                    left = self.cursorForPosition(QPoint(0, y)).positionInBlock()
                    right = self.cursorForPosition(QPoint(width - 1, y)).positionInBlock()
                else:
                    left = 0 if rect.top() >= 0 else self.cursorForPosition(QPoint(0, 0)).positionInBlock()
                    right = block.length() - 1 if rect.bottom() <= height else self.cursorForPosition(QPoint(width - 1, height - 1)).positionInBlock()
                visible.append((row, block, max(0, left - 2), right + 2))
            block = block.next()
        return visible

    def selected_text(self):
        start, end = sorted((self.anchor, self.caret))
        lines = self.presentation.lines
        if start == end or start.row >= len(lines):
            return ""
        if start == TextPoint(0) and end == TextPoint(len(lines)):
            return "\n".join(lines)

        def fragments():
            for row in range(start.row, min(end.row + 1, len(lines))):
                text = lines[row]
                if row == start.row or row == end.row:
                    left = start.column * 2 if row == start.row else 0
                    right = end.column * 2 if row == end.row else None
                    text = text.encode("utf-16-le", errors="surrogatepass")[left:right].decode(
                        "utf-16-le", errors="surrogatepass")
                yield text

        # Only separators between retained lines belong to the snapshot. The
        # logical EOF sentinel must not introduce a synthetic trailing newline.
        return "\n".join(fragments())
