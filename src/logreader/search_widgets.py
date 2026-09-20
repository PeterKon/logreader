"""Shared search highlighting and scrollbar markers for text editors."""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from heapq import merge
from typing import Iterable

from PySide6.QtCore import QElapsedTimer, QTimer, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QScrollBar, QStyle, QStyleOptionSlider, QWidget

from .search_storage import BlockSet, SearchMatches
from .theme import THEME_COLORS


INCREMENTAL_SEARCH_BATCH_MS = 4


class SearchMatchHighlighter(QSyntaxHighlighter):
    """Paint result-search matches without retaining text cursors."""

    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor.document())
        self._editor = editor
        self._matches = SearchMatches()
        self._match_blocks = array("I")
        self._painted_blocks = BlockSet()
        self._fresh_blocks = BlockSet()
        self._targets = iter(())
        self._visible_targets = iter(())
        self._cancelled = False
        self._painting = False
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._highlight_next_batch)
        editor.updateRequest.connect(self._prioritize_viewport)
        self._match_format = QTextCharFormat()
        self._match_format.setBackground(QColor(THEME_COLORS["ui_primary"]))
        self._match_format.setForeground(QColor("#ffffff"))

    def _prioritize_viewport(self, *_args) -> None:
        if self._cancelled or self._painting:
            return
        rect = self._editor.viewport().rect()
        first = self._editor.firstVisibleBlock().blockNumber()
        last = self._editor.cursorForPosition(rect.bottomRight()).blockNumber()
        self._visible_targets = iter(range(first, last + 1))
        self._highlight_timer.start(0)

    @Slot()
    def _highlight_next_batch(self) -> None:
        if self._cancelled:
            return
        elapsed = QElapsedTimer()
        elapsed.start()
        while True:
            number = next(self._visible_targets, None)
            if number is None:
                number = next(self._targets, None)
            if number is None:
                return
            if number not in self._fresh_blocks:
                index = bisect_left(self._match_blocks, number)
                has_matches = (index < len(self._match_blocks)
                               and self._match_blocks[index] == number)
                if has_matches or number in self._painted_blocks:
                    block = self.document().findBlockByNumber(number)
                    if block.isValid():
                        self._painting = True
                        try:
                            # Qt 6.11 retains a HarfBuzz shaping buffer per text engine.
                            # Rehighlighting additional document blocks can therefore
                            # increase retained native memory, even after search
                            # highlights are cleared. Our Qt 6.10.0 / 6.11.2 comparison
                            # showed substantially higher repeated-search memory use
                            # on 6.11.2. This is not evidence of an ever-growing
                            # Python match cache.
                            #
                            # Before changing this highlighting path, compare Qt
                            # versions and benchmark native scrolling, wrapping,
                            # and search responsiveness.
                            # Investigation: benchmarks/layout-memory-investigation.md
                            # Upstream report: https://qt-project.atlassian.net/browse/QTBUG-150286
                            # Upstream change:
                            # https://github.com/qt/qtbase/commit/8209078e0eb1f100f0f822d75856c9f557f60195
                            self.rehighlightBlock(block)
                        finally:
                            self._painting = False
                    self._fresh_blocks.add(number)
                    if has_matches:
                        self._painted_blocks.add(number)
                    else:
                        self._painted_blocks.discard(number)
            if elapsed.elapsed() >= INCREMENTAL_SEARCH_BATCH_MS:
                self._highlight_timer.start(1)
                return

    def cancel(self) -> None:
        self._cancelled = True
        self._highlight_timer.stop()

    def set_matches(
        self, matches: SearchMatches, match_blocks: array | None = None,
    ) -> None:
        """Paint visible matches first, then only matching or previously painted blocks."""
        self._cancelled = False
        if matches is not self._matches:
            self._matches = matches
            self._match_blocks = match_blocks if match_blocks is not None else array("I")
            self._fresh_blocks.clear()
            # Include formats left by an interrupted older query so rapid edits
            # cannot leave stale highlights elsewhere in the document.
            self._targets = merge(self._painted_blocks.ordered_snapshot(), self._match_blocks)
        self._prioritize_viewport()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        """Apply the ordinary match format to ranges in the current block."""

        if not self._matches or not text:
            return

        block_start = self.currentBlock().position()
        block_end = block_start + self.currentBlock().length() - 1
        starts, ends = self._matches.starts, self._matches.ends
        match_index = bisect_right(ends, block_start)
        while match_index < len(starts):
            start, end = starts[match_index], ends[match_index]
            if start >= block_end:
                break

            visible_start = max(start, block_start)
            visible_end = min(end, block_end)
            if visible_end > visible_start:
                self.setFormat(
                    visible_start - block_start,
                    visible_end - visible_start,
                    self._match_format,
                )
            match_index += 1


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
