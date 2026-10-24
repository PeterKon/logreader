"""Search and bookmark scrollbar markers for text editors."""

from __future__ import annotations

from array import array
from bisect import bisect_left
from typing import Iterable

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPainter, QTextDocument
from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider, QWidget

from ..theme import THEME_COLORS


class SearchMarkerScrollBar(QScrollBar):
    """Paint search and bookmark markers behind the scrollbar thumb."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self._match_blocks = array("I")
        self._document: QTextDocument | None = None
        self._bookmark_blocks = array("I")
        self._bookmark_document: QTextDocument | None = None
        self._marker_rows: tuple[int, ...] = ()
        self._marker_cache_key: tuple[int, ...] | None = None
        self._bookmark_marker_rows: tuple[int, ...] = ()
        self._bookmark_marker_cache_key: tuple[int, ...] | None = None
        self.rangeChanged.connect(self._invalidate_marker_rows)

    def set_match_blocks(
        self,
        match_blocks: array,
        document: QTextDocument | None,
    ) -> None:
        """Set compact matching block numbers without copying their array."""

        self._match_blocks = match_blocks
        self._document = document
        self._invalidate_marker_rows()

    def set_bookmark_blocks(self, blocks: Iterable[int], document: QTextDocument | None) -> None:
        self._bookmark_blocks = array("I", sorted(blocks))
        self._bookmark_document = document
        self._invalidate_marker_rows()

    @Slot()
    def _invalidate_marker_rows(self, *_args) -> None:
        self._marker_rows = ()
        self._marker_cache_key = None
        self._bookmark_marker_rows = ()
        self._bookmark_marker_cache_key = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if (
            not (self._match_blocks and self._document is not None
                 or self._bookmark_blocks and self._bookmark_document is not None)
            or self.orientation() != Qt.Orientation.Vertical
        ):
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarGroove,
            self,
        )
        if groove.isEmpty():
            return

        slider = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarSlider,
            self,
        )
        marker_rows = self._marker_rows_for_groove(groove)
        marker_left = groove.left() + 2
        marker_width = max(1, groove.width() - 4)

        painter = QPainter(self)
        painter.setClipRect(groove)
        marker_color = QColor(THEME_COLORS["ui_primary"])
        for row in marker_rows:
            if slider.top() <= row <= slider.bottom():
                continue
            painter.fillRect(marker_left, row, marker_width, 1, marker_color)

        bookmark_color = QColor(THEME_COLORS["bookmark_marker"])
        for row in self._marker_rows_for_groove(groove, bookmarks=True):
            if slider.top() <= row <= slider.bottom():
                continue
            # Bookmark pips take precedence over search pips on the same row.
            painter.fillRect(marker_left, row, marker_width, 1, bookmark_color)

    def _marker_rows_for_groove(self, groove, *, bookmarks=False) -> tuple[int, ...]:
        document = self._bookmark_document if bookmarks else self._document
        blocks = self._bookmark_blocks if bookmarks else self._match_blocks
        document_block_count = (
            document.blockCount() if document is not None else 0
        )
        document_width = (
            round(document.documentLayout().documentSize().width())
            if document is not None
            else 0
        )
        cache_key = (
            *groove.getRect(),
            self.minimum(),
            self.maximum(),
            self.pageStep(),
            document_block_count,
            document_width,
        )
        if bookmarks:
            if cache_key == self._bookmark_marker_cache_key:
                return self._bookmark_marker_rows
        elif cache_key == self._marker_cache_key:
            return self._marker_rows

        rows = self._project_marker_rows(groove, blocks, document, document_block_count)
        if bookmarks:
            self._bookmark_marker_cache_key = cache_key
            self._bookmark_marker_rows = rows
        else:
            self._marker_cache_key = cache_key
            self._marker_rows = rows
        return rows

    def _project_marker_rows(self, groove, blocks, document, document_block_count) -> tuple[int, ...]:
        height = groove.height()
        if (
            height <= 0
            or not blocks
            or document is None
        ):
            return ()

        row_span = max(0, height - 1)
        scroll_extent = self.maximum() - self.minimum() + self.pageStep()
        document_extent = max(document_block_count, scroll_extent)
        document_span = max(1, document_extent - 1)
        use_visual_lines = scroll_extent > document_block_count
        # Skip directly to the next occupied pixel row. Work scales with the
        # scrollbar height, rather than the number of matching document lines.
        def position_for_block(block_number):
            if use_visual_lines:
                block = document.findBlockByNumber(block_number)
                first_line = block.firstLineNumber() if block.isValid() else -1
                if first_line >= 0:
                    return first_line
            return block_number

        rows = []
        index = 0
        while index < len(blocks):
            position = position_for_block(blocks[index])
            relative_row = min(row_span, position * row_span // document_span)
            rows.append(groove.top() + relative_row)
            if relative_row == row_span:
                break
            next_position = (
                (relative_row + 1) * document_span + row_span - 1
            ) // row_span
            index = bisect_left(
                blocks, next_position, lo=index + 1,
                key=position_for_block,
            )
        return tuple(rows)
