"""Paged plain source display with independent snapshot-wide search state."""

from array import array
from bisect import bisect_left

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from .search_storage import SearchMatches
from .source_search import SourceMatches, iter_source_matches
from .theme import THEME_COLORS, configure_action_button


SOURCE_PAGE_LINES = 10_000
SOURCE_PAGE_CHARACTERS = 2560 * 1024
SOURCE_BATCH_MS = 4


class LineNumberArea(QWidget):
    def paintEvent(self, event) -> None:  # noqa: N802
        self.parent().paint_line_numbers(event)


class SourceEditor(QPlainTextEdit):
    """Original line numbers live in a gutter, not in selected/copied text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.first_source_line = 1
        self.gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.update_gutter)

    def update_gutter(self, *_args) -> None:
        width = self.fontMetrics().horizontalAdvance(
            str(self.first_source_line + self.blockCount())
        ) + 18
        self.setViewportMargins(width, 0, 0, 0)
        # Block positions are viewport-relative; include the styled editor's
        # frame and padding when placing the gutter beside that viewport.
        viewport = self.viewport().geometry()
        self.gutter.setGeometry(viewport.left() - width, viewport.top(), width, viewport.height())
        self.gutter.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
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
            if block.isVisible():
                painter.drawText(
                    0, top, self.gutter.width() - 8, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(self.first_source_line + block.blockNumber()),
                )
            block = block.next()


class SourceView(QWidget):
    """Borrow source strings and materialize only the active page in Qt.

    Paging never silently reads a newer disk snapshot. A single unusually long
    source line is kept intact even if it exceeds the normal page character cap.
    """

    search_status_changed = Signal(str)

    def __init__(self, parent, *, highlighter_factory, scrollbar_factory, editor_style):
        super().__init__(parent)
        self.lines: tuple[str, ...] = ()
        self.total_line_count = 0
        self.page_start = self.page_end = 0
        self.target_line: int | None = None
        self.query = ""
        self.searched_query: str | None = None
        self.matches = SourceMatches()
        self.current_match: int | None = None
        self.search_status = ""
        self._search_work = None
        self._pending = SourceMatches()
        self._pending_navigation = None
        self._page_work = None
        self._materialized = False
        self._from_viewport = True
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._advance_search)
        self._page_timer = QTimer(self)
        self._page_timer.setSingleShot(True)
        self._page_timer.timeout.connect(self._advance_page_highlights)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 4)
        self.previous_button = QPushButton("Previous page")
        self.next_button = QPushButton("Next page")
        self.goto_input = QLineEdit()
        self.goto_input.setObjectName("sourceGoToLine")
        self.goto_input.setAccessibleName("Original source line number")
        self.goto_input.setPlaceholderText("Line number")
        self.goto_input.setMaximumWidth(125)
        self.goto_button = QPushButton("Go to line")
        for button in (self.previous_button, self.next_button, self.goto_button):
            configure_action_button(button)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.goto_button.clicked.connect(self.go_to_input)
        self.goto_input.returnPressed.connect(self.go_to_input)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        controls.addWidget(self.goto_input)
        controls.addWidget(self.goto_button)
        layout.addLayout(controls)
        self.range_label = QLabel()
        self.range_label.setObjectName("sourceRange")
        self.range_label.setContentsMargins(8, 2, 8, 4)
        self.range_label.setWordWrap(True)
        layout.addWidget(self.range_label)
        self.editor = SourceEditor(self)
        self.editor.setObjectName("sourceView")
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setStyleSheet(editor_style + "QPlainTextEdit#sourceView { color: #ffffff; }")
        self.marker = scrollbar_factory(Qt.Orientation.Vertical, self.editor)
        self.marker.setToolTip("Search markers and scrolling cover this source page.")
        self.editor.setVerticalScrollBar(self.marker)
        for scrollbar in (self.marker, self.editor.horizontalScrollBar()):
            scrollbar.sliderPressed.connect(self._use_viewport_anchor)
            scrollbar.actionTriggered.connect(self._use_viewport_anchor)
        self.highlighter = highlighter_factory(self.editor)
        layout.addWidget(self.editor, 1)
        self.reset()

    @property
    def first_line(self) -> int:
        return self.total_line_count - len(self.lines) + 1

    @property
    def is_searching(self) -> bool:
        return self._search_work is not None

    def _status(self, text: str) -> None:
        self.search_status = text
        self.search_status_changed.emit(text)

    def reset(self, message="Source is not loaded yet.") -> None:
        self.cancel_search()
        self.lines = ()
        self.total_line_count = 0
        self.page_start = self.page_end = 0
        self.target_line = None
        self._materialized = False
        self.query = ""
        self.goto_input.clear()
        self.editor.clear()
        self.editor.setExtraSelections([])
        self.editor.setPlaceholderText(message)
        self.range_label.setText(message)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def set_source(self, lines: tuple[str, ...], total_line_count: int) -> None:
        self.reset()
        self.lines = lines  # Same immutable tuple as the document session.
        self.total_line_count = total_line_count
        self.editor.setPlaceholderText("Empty source file" if not lines else "")
        self.range_label.setText(self._retained_range())

    def _retained_range(self) -> str:
        if not self.lines:
            return "Empty source file"
        return f"Retained source: {self.first_line:,}–{self.total_line_count:,}"

    def ensure_page(self) -> None:
        if self.lines and not self._materialized:
            self._load_page(0, align="start")

    def _load_page(self, index: int, *, align="center") -> None:
        self._from_viewport = True
        self._cancel_page_highlights()
        start, end = index, index + 1
        characters = len(self.lines[index]) + 1
        before = SOURCE_PAGE_LINES // 2 if align == "center" else SOURCE_PAGE_LINES - 1
        if align != "start":
            while start > 0 and index - start < before:
                size = len(self.lines[start - 1]) + 1
                if characters + size > SOURCE_PAGE_CHARACTERS:
                    break
                start -= 1
                characters += size
        if align != "end":
            while end < len(self.lines) and end - start < SOURCE_PAGE_LINES:
                size = len(self.lines[end]) + 1
                if characters + size > SOURCE_PAGE_CHARACTERS:
                    break
                characters += size
                end += 1
        self.page_start, self.page_end = start, end
        self._materialized = True
        self.highlighter.set_matches(SearchMatches())
        self.marker.set_match_blocks(array("I"), None)
        self.editor.first_source_line = self.first_line + start
        self.editor.setPlainText("\n".join(self.lines[start:end]))
        self.editor.update_gutter()
        self.previous_button.setEnabled(start > 0)
        self.next_button.setEnabled(end < len(self.lines))
        self._update_range()
        self._schedule_page_highlights()

    def _update_range(self) -> None:
        self.range_label.setText(
            f"Showing {self.first_line + self.page_start:,}–{self.first_line + self.page_end - 1:,}  •  "
            f"{self._retained_range()}  •  Search covers all retained lines"
        )

    def go_to_line(self, number: int, *, highlight=True) -> bool:
        index = number - self.first_line
        if not 0 <= index < len(self.lines):
            self.range_label.setText(f"Line {number:,} is not retained. {self._retained_range()}")
            return False
        if highlight:
            self.target_line = number
            self._from_viewport = True
        if not self.page_start <= index < self.page_end:
            self._load_page(index)
        cursor = QTextCursor(self.editor.document().findBlockByNumber(index - self.page_start))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.goto_input.setText(str(number))
        self._update_range()
        self._update_selections()
        return True

    def go_to_input(self) -> None:
        value = "".join(self.goto_input.text().split())
        if not value.isascii() or not value.isdecimal():
            self.range_label.setText(f"Enter an original line number. {self._retained_range()}")
            return
        # Bound parsing of arbitrary pasted input, without QSpinBox's int32 limit.
        if len(value) > 20:
            self.range_label.setText(f"Line number is outside the retained range. {self._retained_range()}")
            return
        self.go_to_line(int(value))

    def next_page(self) -> None:
        if self.page_end < len(self.lines):
            self._load_page(self.page_end, align="start")
            self._update_selections()

    def previous_page(self) -> None:
        if self.page_start:
            self._load_page(self.page_start - 1, align="end")
            self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())
            self._update_selections()

    def set_query(self, query: str) -> None:
        self.cancel_search()
        self.query = query

    def _use_viewport_anchor(self, *_args) -> None:
        self._from_viewport = True

    def cancel_search(self) -> None:
        self._search_timer.stop()
        self._search_work = None
        self._pending = SourceMatches()
        self._pending_navigation = None
        self.matches = SourceMatches()
        self.current_match = None
        self._from_viewport = True
        self.searched_query = None
        self._cancel_page_highlights()
        self.highlighter.set_matches(SearchMatches())
        self.marker.set_match_blocks(array("I"), None)
        self._status("")
        self._update_selections()

    def search(self) -> None:
        if self.query == self.searched_query:
            self.navigate(True)
            return
        self.cancel_search()
        self.searched_query = self.query
        if not self.query:
            return
        self._search_work = iter_source_matches(self.lines, self.query)
        self._status("Searching…")
        self._search_timer.start(0)

    def _advance_search(self) -> None:
        if self._search_work is None:
            return
        elapsed = QElapsedTimer()
        elapsed.start()
        while elapsed.elapsed() < SOURCE_BATCH_MS:
            try:
                match = next(self._search_work)
            except StopIteration:
                self._search_work = None
                self.matches = self._pending
                self._pending = SourceMatches()
                self._status(f"0 / {len(self.matches):,}" if self.matches else "No matches")
                self._schedule_page_highlights()
                navigation = self._pending_navigation
                self._pending_navigation = None
                if navigation is not None:
                    self.navigate(navigation)
                return
            if match is not None:
                self._pending.append(*match)
        self._search_timer.start(1)

    def navigate(self, forward: bool) -> None:
        if self.searched_query != self.query:
            self.search()
        if self.is_searching:
            self._pending_navigation = forward
            return
        if not self.matches:
            return
        if self.current_match is None or self._from_viewport:
            anchor = self.page_start + self.editor.firstVisibleBlock().blockNumber()
            index = bisect_left(self.matches.lines, anchor)
            if not forward:
                index -= 1
        else:
            index = self.current_match + (1 if forward else -1)
        self.current_match = index % len(self.matches)
        row = self.matches.lines[self.current_match]
        self.go_to_line(self.first_line + row, highlight=False)
        block = self.editor.document().findBlockByNumber(row - self.page_start)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + self.matches.starts[self.current_match])
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self._from_viewport = False
        self._status(f"{self.current_match + 1:,} / {len(self.matches):,}")
        self._update_selections()

    def _cancel_page_highlights(self) -> None:
        self._page_timer.stop()
        self._page_work = None

    def _schedule_page_highlights(self) -> None:
        self._cancel_page_highlights()
        self._page_work = self._project_page_matches()
        self._page_timer.start(0)

    def _project_page_matches(self):
        matches = SearchMatches()
        blocks = array("I")
        start = bisect_left(self.matches.lines, self.page_start)
        end = bisect_left(self.matches.lines, self.page_end)
        last_row = None
        block_position = 0
        for index in range(start, end):
            row = self.matches.lines[index] - self.page_start
            if row != last_row:
                block_position = self.editor.document().findBlockByNumber(row).position()
                blocks.append(row)
                last_row = row
            matches.append(block_position + self.matches.starts[index],
                           block_position + self.matches.ends[index])
            yield
        self.highlighter.set_matches(matches, blocks)
        self.marker.set_match_blocks(blocks, self.editor.document())

    def _advance_page_highlights(self) -> None:
        elapsed = QElapsedTimer()
        elapsed.start()
        while self._page_work is not None and elapsed.elapsed() < SOURCE_BATCH_MS:
            try:
                next(self._page_work)
            except StopIteration:
                self._page_work = None
        if self._page_work is not None:
            self._page_timer.start(1)

    def _update_selections(self) -> None:
        selections = []
        if self.target_line is not None:
            row = self.target_line - self.first_line - self.page_start
            if 0 <= row < self.page_end - self.page_start:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(self.editor.document().findBlockByNumber(row))
                selection.format.setBackground(QColor(THEME_COLORS["selection"]))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selections.append(selection)
        if self.current_match is not None:
            index = self.current_match
            row = self.matches.lines[index] - self.page_start
            if 0 <= row < self.page_end - self.page_start:
                block = self.editor.document().findBlockByNumber(row)
                selection = QTextEdit.ExtraSelection()
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + self.matches.starts[index])
                cursor.setPosition(block.position() + self.matches.ends[index], QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = cursor
                selection.format.setBackground(QColor(THEME_COLORS["search_current"]))
                selection.format.setForeground(QColor(THEME_COLORS["background"]))
                selections.append(selection)
        self.editor.setExtraSelections(selections)
