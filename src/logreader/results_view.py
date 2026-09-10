"""Qt results panel and incremental rendering for Logreader."""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from heapq import merge
from time import perf_counter
from typing import Callable, Iterator

from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QSignalBlocker,
    QSize,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollBar,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import APP_VERSION, LogreaderConfig
from .core import (
    COMBINED_CATEGORY_KEY,
    AnalysisResult,
    CategoryResult,
    ResultLine,
)
from .presentation import CategoryPresentation, build_category_presentations
from .theme import THEME_COLORS, configure_clear_button, vertical_resize_icon


RESULT_COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
RULE = "─" * 72
ENTRY_SEPARATOR = "-------->"
INCREMENTAL_RENDER_BATCH_MS = 8
INCREMENTAL_SEARCH_BATCH_MS = 4
SEARCH_CHUNK_SIZE = 4096

RenderOperation = tuple[str, str, bool]
CheckBoxFactory = Callable[[], QCheckBox]
SpinBoxFactory = Callable[[], QSpinBox]


class SearchMatchHighlighter(QSyntaxHighlighter):
    """Paint result-search matches without retaining text cursors."""

    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor.document())
        self._editor = editor
        self._matches: tuple[tuple[int, int], ...] = ()
        self._match_blocks = array("I")
        self._painted_blocks: set[int] = set()
        self._fresh_blocks: set[int] = set()
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
        self, matches: tuple[tuple[int, int], ...], match_blocks: array | None = None,
    ) -> None:
        """Paint visible matches first, then only matching or previously painted blocks."""
        self._cancelled = False
        if matches is not self._matches:
            self._matches = matches
            self._match_blocks = match_blocks if match_blocks is not None else array("I")
            self._fresh_blocks.clear()
            # Include formats left by an interrupted older query so rapid edits
            # cannot leave stale highlights elsewhere in the document.
            self._targets = merge(sorted(self._painted_blocks), self._match_blocks)
        self._prioritize_viewport()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        """Apply the ordinary match format to ranges in the current block."""

        if not self._matches or not text:
            return

        block_start = self.currentBlock().position()
        block_end = block_start + self.currentBlock().length() - 1
        match_index = bisect_right(
            self._matches, block_start, key=lambda match: match[1],
        )
        while match_index < len(self._matches):
            start, end = self._matches[match_index]
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
    """Paint compact result-search markers behind the scrollbar thumb."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self._match_blocks = array("I")
        self._document: QTextDocument | None = None
        self._marker_rows: tuple[int, ...] = ()
        self._marker_cache_key: tuple[int, ...] | None = None
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

    @Slot()
    def _invalidate_marker_rows(self, *_args) -> None:
        self._marker_rows = ()
        self._marker_cache_key = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if (
            not self._match_blocks
            or self._document is None
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

    def _marker_rows_for_groove(self, groove) -> tuple[int, ...]:
        document_block_count = (
            self._document.blockCount() if self._document is not None else 0
        )
        document_width = (
            round(self._document.documentLayout().documentSize().width())
            if self._document is not None
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
        if cache_key == self._marker_cache_key:
            return self._marker_rows

        self._marker_cache_key = cache_key
        height = groove.height()
        if (
            height <= 0
            or not self._match_blocks
            or self._document is None
        ):
            self._marker_rows = ()
            return self._marker_rows

        row_span = max(0, height - 1)
        scroll_extent = self.maximum() - self.minimum() + self.pageStep()
        document_extent = max(document_block_count, scroll_extent)
        document_span = max(1, document_extent - 1)
        use_visual_lines = scroll_extent > document_block_count
        # Skip directly to the next occupied pixel row. Work scales with the
        # scrollbar height, rather than the number of matching document lines.
        def position_for_block(block_number):
            if use_visual_lines:
                block = self._document.findBlockByNumber(block_number)
                first_line = block.firstLineNumber() if block.isValid() else -1
                if first_line >= 0:
                    return first_line
            return block_number

        rows = []
        index = 0
        while index < len(self._match_blocks):
            position = position_for_block(self._match_blocks[index])
            relative_row = min(row_span, position * row_span // document_span)
            rows.append(groove.top() + relative_row)
            if relative_row == row_span:
                break
            next_position = (
                (relative_row + 1) * document_span + row_span - 1
            ) // row_span
            index = bisect_left(
                self._match_blocks, next_position, lo=index + 1,
                key=position_for_block,
            )
        self._marker_rows = tuple(rows)
        return self._marker_rows


class IncrementalAnalysisRenderer(QObject):
    """Build a formatted results document in event-loop-sized batches."""

    completed = Signal(int, float)
    failed = Signal(int, str)

    def __init__(
        self,
        request_id: int,
        view: QPlainTextEdit,
        source_name: str,
        analysis: AnalysisResult,
        config: LogreaderConfig,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._view = view
        self._operations = _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
        )
        self._cursor: QTextCursor | None = None
        self._started = 0.0
        self._cancelled = False
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_next_batch)

    def start(self) -> None:
        """Clear the previous document and schedule the first render batch."""

        self._started = perf_counter()
        self._view.setUpdatesEnabled(False)
        self._view.clear()
        self._cursor = QTextCursor(self._view.document())
        self._timer.start(0)

    def cancel(self) -> None:
        """Stop future batches and restore painting for the results view."""

        self._cancelled = True
        self._timer.stop()
        self._cursor = None
        # A suspended generator owns the full analysis (and source strings).
        # Release it now, even if a caller retains the renderer wrapper until
        # after Qt processes deleteLater().
        self._operations = iter(())
        self._view.setUpdatesEnabled(True)

    def set_paused(self, paused: bool) -> None:
        if self._cancelled or paused == (self._paused_at is not None):
            return
        if paused:
            self._paused_at = perf_counter()
            self._timer.stop()
            self._view.setUpdatesEnabled(True)
        else:
            self._paused_seconds += perf_counter() - self._paused_at
            self._paused_at = None
            self._view.setUpdatesEnabled(False)
            self._timer.start(0)

    @Slot()
    def _render_next_batch(self) -> None:
        if self._cancelled or self._cursor is None or self._paused_at is not None:
            return

        batch_elapsed = QElapsedTimer()
        batch_elapsed.start()
        finished = False
        self._cursor.beginEditBlock()
        try:
            while True:
                try:
                    text, role, bold = next(self._operations)
                except StopIteration:
                    finished = True
                    break

                _insert(self._cursor, text, role, bold=bold)
                if batch_elapsed.elapsed() >= INCREMENTAL_RENDER_BATCH_MS:
                    break
        except Exception as error:
            self._cursor.endEditBlock()
            self._cursor = None
            self._view.setUpdatesEnabled(True)
            self.failed.emit(self.request_id, str(error))
            return
        self._cursor.endEditBlock()

        if not finished:
            self._timer.start(0)
            return

        self._cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._view.setTextCursor(self._cursor)
        self._cursor = None
        self._view.setUpdatesEnabled(True)
        self.completed.emit(
            self.request_id,
            perf_counter() - self._started - self._paused_seconds,
        )


def _iter_search_matches(
    document: QTextDocument, query: str,
) -> Iterator[tuple[int, int, int] | None]:
    """Use Qt's literal matching on bounded slices, including boundary overlap.

    Positions and slice lengths are UTF-16 units, as required by QTextCursor.
    Yield even on empty slices so sparse/no-match searches also yield to the UI.
    """
    query_length = len(query.encode("utf-16-le", errors="surrogatepass")) // 2
    scratch = QTextDocument()
    cursor = QTextCursor(document)
    position = 0
    last_position = document.characterCount() - 1
    while position < last_position:
        boundary = min(position + SEARCH_CHUNK_SIZE, last_position)
        # PySide's QString conversion drops an isolated surrogate. Never cut
        # a supplementary character in half or subsequent offsets would drift.
        if (boundary < last_position
                and 0xDC00 <= ord(document.characterAt(boundary)) <= 0xDFFF):
            boundary += 1
        end = min(boundary + query_length - 1, last_position)
        if (end < last_position
                and 0xDC00 <= ord(document.characterAt(end)) <= 0xDFFF):
            end += 1
        cursor.setPosition(position)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        scratch.setPlainText(cursor.selectedText())
        local_position = 0
        next_position = boundary
        while True:
            match = scratch.find(query, local_position)
            if match.isNull() or position + match.selectionStart() >= boundary:
                break
            start = position + match.selectionStart()
            stop = position + match.selectionEnd()
            yield start, stop, document.findBlock(start).blockNumber()
            local_position = match.selectionEnd()
            next_position = max(next_position, stop)
        position = next_position
        yield None


class ResultsView(QWidget):
    """Results editor, controls, and incremental rendering lifecycle."""

    maximized_changed = Signal(bool)
    rendering_completed = Signal(int, float)
    rendering_failed = Signal(int, str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        checkbox_factory: CheckBoxFactory = QCheckBox,
        spinbox_factory: SpinBoxFactory = QSpinBox,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultsPanel")
        self._maximized = False
        self._renderer: IncrementalAnalysisRenderer | None = None
        self._search_matches: tuple[tuple[int, int], ...] = ()
        self._search_match_blocks = array("I")
        self._current_search_match: int | None = None
        self._searched_query: str | None = None
        self._search_from_viewport = True
        self._search_generation = 0
        self._search_work: Iterator[tuple[int, int, int] | None] | None = None
        self._pending_matches: list[tuple[int, int]] = []
        self._pending_blocks = array("I")
        self._pending_navigation: bool | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search_next_batch)

        panel_layout = QVBoxLayout(self)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("resultsHeader")
        header.setMinimumHeight(36)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 5, 8, 5)
        header_layout.setSpacing(8)

        self._expand_icon = vertical_resize_icon()
        self._contract_icon = vertical_resize_icon(contract=True)
        self._maximize_button = QPushButton()
        self._maximize_button.setIcon(self._expand_icon)
        self._maximize_button.setIconSize(QSize(18, 18))
        self._maximize_button.setObjectName("maximizeResultsButton")
        self._maximize_button.setAccessibleName("Maximize results")
        self._maximize_button.setFixedSize(38, 26)
        self._maximize_button.setStyleSheet(
            "QPushButton#maximizeResultsButton {"
            " padding: 0;"
            "}"
            "QToolTip { font-weight: 400; }"
        )
        self._maximize_button.setToolTip("Expand results window")
        self._maximize_button.clicked.connect(self.toggle_maximized)
        header_layout.addWidget(self._maximize_button)
        header_layout.addStretch(1)

        self._search_count_label = QLabel()
        self._search_count_label.setObjectName("resultsSearchCount")
        self._search_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._search_count_label.setStyleSheet(
            f"color: {THEME_COLORS['ui_muted']};"
        )
        self._search_count_label.setMinimumWidth(84)
        count_size_policy = self._search_count_label.sizePolicy()
        count_size_policy.setRetainSizeWhenHidden(True)
        self._search_count_label.setSizePolicy(count_size_policy)
        self._search_count_label.hide()
        header_layout.addWidget(self._search_count_label)

        search_controls = QWidget(header)
        search_controls.setObjectName("resultsSearchControls")
        search_controls_layout = QHBoxLayout(search_controls)
        search_controls_layout.setContentsMargins(0, 0, 0, 0)
        search_controls_layout.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("resultsSearch")
        self._search_input.setAccessibleName("Search results")
        self._search_input.setPlaceholderText("Press enter to search...")
        configure_clear_button(self._search_input)
        self._search_input.setFixedWidth(220)
        self._search_input.setStyleSheet(
            "QLineEdit#resultsSearch {"
            " border-right: none;"
            " border-top-right-radius: 0;"
            " border-bottom-right-radius: 0;"
            "}"
        )
        self._search_input.textChanged.connect(self._invalidate_search_results)
        self._search_input.returnPressed.connect(self.search_results)
        search_controls_layout.addWidget(self._search_input)

        search_button_separator = QFrame(search_controls)
        search_button_separator.setObjectName("resultsSearchButtonSeparator")
        search_button_separator.setFixedSize(1, 28)
        search_button_separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']};"
            " border: none;"
        )
        search_controls_layout.addWidget(search_button_separator)

        self._search_navigation = spinbox_factory()
        self._search_navigation.setObjectName("resultsSearchNavigation")
        self._search_navigation.setAccessibleName("Navigate search results")
        self._search_navigation.setToolTip(
            "Up: previous result; down: next result."
        )
        self._search_navigation.setRange(-1, 1)
        self._search_navigation.setValue(0)
        self._search_navigation.setFixedSize(22, 28)
        self._search_navigation.setStyleSheet(
            "QSpinBox#resultsSearchNavigation {"
            " border-left: none;"
            " border-top-left-radius: 0;"
            " border-bottom-left-radius: 0;"
            " padding: 0;"
            "}"
        )
        self._search_navigation.lineEdit().hide()
        self._search_navigation.valueChanged.connect(
            self._navigate_from_search_arrows
        )
        search_controls_layout.addWidget(self._search_navigation)
        header_layout.addWidget(search_controls)

        search_separator = QFrame()
        search_separator.setObjectName("resultsSearchSeparator")
        search_separator.setFrameShape(QFrame.Shape.VLine)
        search_separator.setFrameShadow(QFrame.Shadow.Plain)
        search_separator.setFixedWidth(1)
        search_separator.setMaximumHeight(22)
        search_separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']};"
            " border: none;"
        )
        header_layout.addWidget(search_separator)

        line_wrap_label = QLabel("Line wrapping")
        line_wrap_label.setObjectName("lineWrapLabel")
        header_layout.addWidget(line_wrap_label)

        self._line_wrap_check = checkbox_factory()
        self._line_wrap_check.setObjectName("lineWrapCheck")
        self._line_wrap_check.setAccessibleName("Line wrapping")
        self._line_wrap_check.setToolTip(
            "Wrap long result lines to the width of the results window."
        )
        self._line_wrap_check.toggled.connect(self.set_line_wrapping)
        header_layout.addWidget(self._line_wrap_check)
        panel_layout.addWidget(header)

        self._editor = QPlainTextEdit(self)
        self._editor.setObjectName("resultsView")
        self._editor.setReadOnly(True)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setPlaceholderText(
            "Open a log file to display the analyzed results here."
        )
        self._editor.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self._editor.setStyleSheet(_results_editor_style_sheet())
        self._search_marker_scrollbar = SearchMarkerScrollBar(
            Qt.Orientation.Vertical,
            self._editor,
        )
        self._editor.setVerticalScrollBar(self._search_marker_scrollbar)
        for scrollbar in (
            self._search_marker_scrollbar,
            self._editor.horizontalScrollBar(),
        ):
            # User actions re-anchor navigation; ordinary value changes from
            # revealing a match or laying out the document must not do so.
            scrollbar.sliderPressed.connect(self._use_viewport_search_anchor)
            scrollbar.actionTriggered.connect(self._use_viewport_search_anchor)
        self._search_highlighter = SearchMatchHighlighter(
            self._editor
        )
        self._editor.document().contentsChange.connect(self._results_changed)
        panel_layout.addWidget(self._editor, 1)

    @property
    def editor(self) -> QPlainTextEdit:
        """Return the read-only editor displaying formatted results."""

        return self._editor

    @property
    def is_maximized(self) -> bool:
        return self._maximized

    def reset_for_loaded_file(self, source_name: str) -> None:
        """Clear old output and describe the newly staged source file."""

        self.cancel_rendering()
        self._search_input.clear()
        self._clear_search_results()
        self._editor.clear()
        self._editor.setPlaceholderText(
            f"{source_name} is loaded. Choose Analyze to display results."
        )

    def focus_editor(self) -> None:
        self._search_input.deselect()
        self._search_input.clearFocus()
        self._editor.setFocus()

    @Slot()
    def toggle_maximized(self) -> None:
        self.set_maximized(not self._maximized)

    def set_maximized(self, maximized: bool) -> None:
        """Update the results expansion state and notify the window shell."""

        if maximized == self._maximized:
            return

        self._maximized = maximized
        if maximized:
            self._maximize_button.setIcon(self._contract_icon)
            self._maximize_button.setAccessibleName("Restore layout")
            self._maximize_button.setToolTip("Show menu and filters")
        else:
            self._maximize_button.setIcon(self._expand_icon)
            self._maximize_button.setAccessibleName("Maximize results")
            self._maximize_button.setToolTip("Expand results window")
        self.maximized_changed.emit(maximized)

    @Slot(bool)
    def set_line_wrapping(self, enabled: bool) -> None:
        """Enable or disable wrapping of long result lines."""

        line_wrap_mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self._editor.setLineWrapMode(line_wrap_mode)

    @Slot(str)
    def _invalidate_search_results(self, _query: str) -> None:
        """Clear stale matches without searching while the user types."""

        self._clear_search_results()

    @Slot()
    def search_results(self) -> None:
        """Highlight a new query, or navigate down for an unchanged search."""

        if self._renderer is not None:
            return
        if self._searched_query != self._search_input.text():
            self._refresh_search_matches()
        else:
            self.find_next()

    @Slot()
    def _use_viewport_search_anchor(self) -> None:
        """Start the next navigation from the top visible text line."""

        self._search_from_viewport = True

    @Slot()
    def _refresh_search_matches(self) -> None:
        """Find and highlight every literal occurrence in rendered results."""

        query = self._search_input.text()
        self._clear_search_results()
        self._searched_query = query
        if not query:
            return

        self._search_work = _iter_search_matches(self._editor.document(), query)
        self._search_count_label.setText("Searching…")
        self._search_count_label.show()
        self._search_timer.start(0)

    @property
    def is_searching(self) -> bool:
        return self._search_work is not None

    @Slot(int, int, int)
    def _results_changed(self, _position: int, removed: int, added: int) -> None:
        if (removed or added) and (
            self.is_searching or self._searched_query is not None
        ):
            self._clear_search_results()

    @Slot()
    def _search_next_batch(self) -> None:
        self._advance_search(self._search_generation)

    def _advance_search(self, generation: int) -> None:
        if generation != self._search_generation or self._search_work is None:
            return
        elapsed = QElapsedTimer()
        elapsed.start()
        while elapsed.elapsed() < INCREMENTAL_SEARCH_BATCH_MS:
            try:
                match = next(self._search_work)
            except StopIteration:
                self._search_work = None
                self._search_matches = tuple(self._pending_matches)
                self._pending_matches = []
                self._search_match_blocks = self._pending_blocks
                self._pending_blocks = array("I")
                count = len(self._search_matches)
                self._search_count_label.setText(
                    f"0 / {count}" if count else "No matches",
                )
                self._search_highlighter.set_matches(
                    self._search_matches, self._search_match_blocks,
                )
                self._search_marker_scrollbar.set_match_blocks(
                    self._search_match_blocks, self._editor.document(),
                )
                navigation = self._pending_navigation
                self._pending_navigation = None
                if navigation is not None:
                    self._navigate_search(forward=navigation)
                return
            if match is not None:
                start, end, block = match
                self._pending_matches.append((start, end))
                if not self._pending_blocks or self._pending_blocks[-1] != block:
                    self._pending_blocks.append(block)
        self._search_timer.start(1)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.cancel_search()
        super().closeEvent(event)

    def cancel_search(self) -> None:
        """Invalidate pending batches and release their document references."""
        if self.is_searching:
            self._searched_query = None
            self._search_count_label.hide()
        self._search_generation += 1
        self._search_timer.stop()
        self._search_work = None
        self._pending_matches = []
        self._pending_blocks = array("I")
        self._pending_navigation = None
        self._search_highlighter.cancel()

    def _clear_search_results(self) -> None:
        self.cancel_search()
        self._search_matches = ()
        self._search_match_blocks = array("I")
        self._current_search_match = None
        self._searched_query = None
        self._search_from_viewport = True
        self._search_count_label.hide()
        self._search_highlighter.set_matches(())
        self._search_marker_scrollbar.set_match_blocks(
            self._search_match_blocks,
            None,
        )
        self._editor.setExtraSelections([])

    @Slot()
    def find_next(self) -> None:
        """Move to the next result-search match, wrapping at the end."""

        self._navigate_search(forward=True)

    @Slot()
    def find_previous(self) -> None:
        """Move to the previous result-search match, wrapping at the start."""

        self._navigate_search(forward=False)

    def _navigate_search(self, *, forward: bool) -> None:
        if self._renderer is not None:
            return
        if self._searched_query != self._search_input.text():
            self._refresh_search_matches()
        if self.is_searching:
            self._pending_navigation = forward
            return
        if not self._search_matches:
            return

        if self._current_search_match is None or self._search_from_viewport:
            anchor = self._editor.cursorForPosition(
                self._editor.viewport().rect().topLeft()
            )
            anchor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            current = bisect_left(
                self._search_matches,
                anchor.position(),
                key=lambda match: match[0],
            )
            if not forward:
                current -= 1
            current %= len(self._search_matches)
        else:
            step = 1 if forward else -1
            current = (self._current_search_match + step) % len(
                self._search_matches
            )

        self._current_search_match = current
        self._search_count_label.setText(
            f"{current + 1} / {len(self._search_matches)}"
        )
        self._update_current_search_highlight()

        start, _end = self._search_matches[current]
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(start)
        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()
        self._search_from_viewport = False

    @Slot(int)
    def _navigate_from_search_arrows(self, value: int) -> None:
        if value > 0:
            self.find_previous()
        elif value < 0:
            self.find_next()

        blocker = QSignalBlocker(self._search_navigation)
        self._search_navigation.setValue(0)
        del blocker

    def _update_current_search_highlight(self) -> None:
        if self._current_search_match is None:
            self._editor.setExtraSelections([])
            return

        start, end = self._search_matches[self._current_search_match]
        selection = QTextEdit.ExtraSelection()
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection.cursor = cursor
        selection.format.setBackground(
            QColor(THEME_COLORS["search_current"])
        )
        selection.format.setForeground(QColor(THEME_COLORS["background"]))
        self._editor.setExtraSelections([selection])

    def start_rendering(
        self,
        request_id: int,
        source_name: str,
        analysis: AnalysisResult,
        config: LogreaderConfig,
    ) -> None:
        """Start a new incremental render, cancelling any previous one."""

        self.cancel_rendering()
        # Analyze focuses the editor when invoked. A later worker completion
        # must preserve whatever control (or other tab) the user moved to.
        self._clear_search_results()
        renderer = IncrementalAnalysisRenderer(
            request_id,
            self._editor,
            source_name,
            analysis,
            config,
            self,
        )
        renderer.completed.connect(self._complete_rendering)
        renderer.failed.connect(self._fail_rendering)
        self._renderer = renderer
        renderer.start()

    def cancel_rendering(self) -> None:
        """Cancel the active incremental render, if any."""

        renderer = self._renderer
        self._renderer = None
        if renderer is None:
            return
        renderer.cancel()
        renderer.deleteLater()

    @property
    def is_rendering(self) -> bool:
        return self._renderer is not None

    def set_rendering_paused(self, paused: bool) -> None:
        if self._renderer is not None:
            self._renderer.set_paused(paused)

    def prepend_performance_timings(
        self,
        analysis_seconds: float,
        rendering_seconds: float,
    ) -> None:
        """Place analysis and rendering durations above the output."""

        prepend_performance_timings(
            self._editor,
            analysis_seconds,
            rendering_seconds,
        )

    @Slot(int, float)
    def _complete_rendering(
        self,
        request_id: int,
        rendering_seconds: float,
    ) -> None:
        renderer = self.sender()
        if renderer is not self._renderer:
            return

        self._renderer = None
        renderer.deleteLater()
        self.rendering_completed.emit(request_id, rendering_seconds)

    @Slot(int, str)
    def _fail_rendering(self, request_id: int, message: str) -> None:
        renderer = self.sender()
        if renderer is not self._renderer:
            return

        self._renderer = None
        renderer.deleteLater()
        self.rendering_failed.emit(request_id, message)


def render_analysis(
    view: QPlainTextEdit,
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> None:
    """Render a structured analysis result into a colored Qt text view."""

    view.setUpdatesEnabled(False)
    try:
        view.clear()
        cursor = QTextCursor(view.document())
        cursor.beginEditBlock()
        for text, role, bold in _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
        ):
            _insert(cursor, text, role, bold=bold)

        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def prepend_performance_timings(
    view: QPlainTextEdit,
    analysis_seconds: float,
    rendering_seconds: float,
) -> None:
    """Place diagnostic analysis and rendering durations above the results."""

    view.setUpdatesEnabled(False)
    try:
        cursor = QTextCursor(view.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        _insert(cursor, "Performance timing\n", "heading", bold=True)
        _insert(cursor, f"Analysis time: {analysis_seconds:.3f} s\n", "muted")
        _insert(
            cursor,
            f"Result rendering time: {rendering_seconds:.3f} s\n\n",
            "muted",
        )
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def _iter_analysis_render_operations(
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> Iterator[RenderOperation]:
    """Yield ordered formatting operations without touching Qt widgets."""

    yield f"{APP_VERSION}\n", "heading", True
    yield f"{source_name}\n\n", "muted", False
    if config.combined_view:
        summary_counts = (
            analysis.category_match_counts.items()
            if analysis.category_match_counts is not None
            else ()
        )
    else:
        summary_counts = (
            (key, result.match_count)
            for key, result in analysis.categories.items()
        )

    for key, match_count in summary_counts:
        label = config.label_for(key)
        yield f"{label:<20}", "body", False
        yield (
            f"{match_count:>8} matches\n",
            _match_count_role(match_count),
            False,
        )

    if config.combined_view:
        combined_result = analysis.category(COMBINED_CATEGORY_KEY)
        label = config.label_for(COMBINED_CATEGORY_KEY)
        yield f"\n{label:<20}", "body", False
        yield (
            f"{combined_result.match_count:>8} matches\n",
            _count_role(combined_result),
            False,
        )

    yield (
        f"\n{analysis.line_count:,} source lines  •  "
        f"context {config.context}\n",
        "muted",
        False,
    )

    for presentation in build_category_presentations(analysis, config.limit):
        yield from _iter_category_render_operations(presentation, config)


def _iter_category_render_operations(
    presentation: CategoryPresentation,
    config: LogreaderConfig,
) -> Iterator[RenderOperation]:
    label = config.label_for(presentation.key)
    yield f"\n{RULE}\n", "muted", False
    yield f"{presentation.heading(label)}\n", "heading", True
    yield f"{RULE}\n", "muted", False

    for excerpt_index, excerpt in enumerate(presentation.excerpts):
        for line in excerpt.lines:
            yield from _iter_result_line_render_operations(line)

        if (
            config.separate_entries
            and excerpt_index < len(presentation.excerpts) - 1
        ):
            yield f"{ENTRY_SEPARATOR}\n", "body", False

    limit_message = presentation.limit_message()
    if limit_message is not None:
        yield f"{limit_message}\n", "limit_notice", True


def _iter_result_line_render_operations(
    line: ResultLine,
) -> Iterator[RenderOperation]:
    line_number = f"{line.number:<7}-> "
    if not line.is_match:
        yield line_number, "line_number", True
        yield f"{line.text}\n", "body", False
        return

    yield line_number, "match", True
    position = 0
    for span in line.match_spans:
        yield line.text[position : span.start], "matched_text", False
        yield line.text[span.start : span.end], "match", True
        position = span.end
    yield f"{line.text[position:]}\n", "matched_text", False


def _count_role(result: CategoryResult) -> str:
    return _match_count_role(result.match_count)


def _match_count_role(match_count: int) -> str:
    return "hit_count" if match_count else "muted"


def _insert(
    cursor: QTextCursor,
    text: str,
    role: str,
    *,
    bold: bool = False,
) -> None:
    text_format = QTextCharFormat()
    text_format.setForeground(RESULT_COLORS[role])
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    cursor.insertText(text, text_format)


def _results_editor_style_sheet() -> str:
    return (
        "QPlainTextEdit {"
        f" background: {THEME_COLORS['background']};"
        f" color: {THEME_COLORS['body']};"
        " border: none;"
        f" selection-background-color: {THEME_COLORS['selection']};"
        " padding: 8px;"
        "}"
        "QPlainTextEdit QScrollBar {"
        " scrollbar-leftclick-absolute-position: 1;"
        "}"
        "QPlainTextEdit QScrollBar:vertical {"
        f" background: {THEME_COLORS['scrollbar_track']};"
        " width: 12px;"
        " margin: 0;"
        "}"
        "QPlainTextEdit QScrollBar:horizontal {"
        f" background: {THEME_COLORS['scrollbar_track']};"
        " height: 12px;"
        " margin: 0;"
        "}"
        "QPlainTextEdit QScrollBar::handle:vertical {"
        f" background: {THEME_COLORS['scrollbar_handle']};"
        " min-height: 28px;"
        " border-radius: 5px;"
        " margin: 2px;"
        "}"
        "QPlainTextEdit QScrollBar::handle:vertical:hover {"
        f" background: {THEME_COLORS['scrollbar_handle_hover']};"
        "}"
        "QPlainTextEdit QScrollBar::handle:horizontal {"
        f" background: {THEME_COLORS['scrollbar_handle']};"
        " min-width: 28px;"
        " border-radius: 5px;"
        " margin: 2px;"
        "}"
        "QPlainTextEdit QScrollBar::handle:horizontal:hover {"
        f" background: {THEME_COLORS['scrollbar_handle_hover']};"
        "}"
        "QPlainTextEdit QScrollBar::add-line:vertical,"
        "QPlainTextEdit QScrollBar::sub-line:vertical,"
        "QPlainTextEdit QScrollBar::add-line:horizontal,"
        "QPlainTextEdit QScrollBar::sub-line:horizontal {"
        " height: 0;"
        " width: 0;"
        "}"
        "QPlainTextEdit QScrollBar::add-page:vertical,"
        "QPlainTextEdit QScrollBar::sub-page:vertical,"
        "QPlainTextEdit QScrollBar::add-page:horizontal,"
        "QPlainTextEdit QScrollBar::sub-page:horizontal {"
        " background: transparent;"
        "}"
    )
