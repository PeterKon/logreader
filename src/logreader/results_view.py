"""Qt results panel and incremental rendering for Logreader."""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from heapq import merge
from time import perf_counter
from textwrap import fill
from typing import Callable, Iterator
from uuid import uuid4

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
    QStackedWidget,
    QStackedLayout,
    QStyle,
    QStyleOptionSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import LogreaderConfig
from .bookmarks import ResultsBookmarks
from .core import (
    COMBINED_CATEGORY_KEY,
    AnalysisResult,
    ResultLine,
)
from .presentation import CategoryPresentation, build_category_presentations
from .search_storage import BlockSet, SearchMatches
from .result_source_map import ResultSourceMap
from .results_editor import (
    ExcerptGapBlock, ResultsEditor, StructuralBlock, SummaryBlock, mark_summary, size_excerpt_gap,
)
from .results_model import ResultLocation, ResultsModel, SourceLocation
from .source_search import iter_source_matches
from .source_view import SourceView
from .theme import THEME_COLORS, configure_action_button, configure_clear_button, vertical_resize_icon


RESULT_COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
# Lazily built for the fixed results palette; never mutate a cached format.
_RESULT_FORMATS: dict[tuple[str, bool], QTextCharFormat] = {}
INCREMENTAL_RENDER_BATCH_MS = 8
INCREMENTAL_SEARCH_BATCH_MS = 4
SEARCH_CHUNK_SIZE = 4096
SUMMARY_COLUMNS = 3
SUMMARY_COLUMN_WIDTH = 19
SUMMARY_COLUMN_GAP = 5
SUMMARY_LINE_LENGTH = 100
RESULT_LABEL_OVERRIDES = {"http_4xx": "HTTP 4xx", "http_5xx": "HTTP 5xx"}

RenderOperation = tuple[str, str, bool]
CheckBoxFactory = Callable[[], QCheckBox]
SpinBoxFactory = Callable[[], QSpinBox]


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
        source_map: ResultSourceMap | None = None,
        model: ResultsModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._view = view
        self._source_map = source_map if source_map is not None else (
            view.projection if isinstance(view, ResultsEditor) else None
        )
        self._model = model if model is not None else ResultsModel(analysis, uuid4().hex)
        self._index_work = self._model.prepare()
        self._operations = _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
            on_excerpt=self._record_excerpt,
            on_summary=self._record_summary,
            model=self._model,
        )
        self._cursor: QTextCursor | None = None
        self._started = 0.0
        self._cancelled = False
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_next_batch)

    def _record_summary(self) -> None:
        if isinstance(self._view, ResultsEditor) and self._cursor is not None:
            mark_summary(self._cursor)

    def _record_excerpt(self, source_line: int, length: int) -> None:
        if self._source_map is not None and self._cursor is not None:
            self._source_map.append(self._cursor.blockNumber(), length, source_line)

    def start(self) -> None:
        """Clear the previous document and schedule the first render batch."""

        self._started = perf_counter()
        self._view.setUpdatesEnabled(False)
        self._view.clear()
        if self._source_map is not None:
            self._source_map.clear()
        if isinstance(self._view, ResultsEditor):
            self._view.set_model(self._model)
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
        self._index_work = None
        if isinstance(self._view, ResultsEditor) and self._view.model is self._model:
            self._view.set_model(None)
            self._view.projection.clear()
        self._model = None
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
                if self._index_work is not None:
                    try:
                        next(self._index_work)
                    except StopIteration:
                        self._index_work = None
                        if isinstance(self._view, ResultsEditor):
                            self._view.update_gutter()
                    if batch_elapsed.elapsed() >= INCREMENTAL_RENDER_BATCH_MS:
                        break
                    continue
                try:
                    text, role, bold = next(self._operations)
                except StopIteration:
                    finished = True
                    break

                _insert(
                    self._cursor, text, role, bold=bold,
                    structural=isinstance(self._view, ResultsEditor) and
                    self._view.projection.row(self._cursor.blockNumber()) is None,
                )
                if batch_elapsed.elapsed() >= INCREMENTAL_RENDER_BATCH_MS:
                    break
        except Exception as error:
            self._cursor.endEditBlock()
            self.cancel()
            self.failed.emit(self.request_id, str(error))
            return
        self._cursor.endEditBlock()

        if not finished:
            self._timer.start(0)
            return

        self._cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._view.setTextCursor(self._cursor)
        self._cursor = None
        self._model = None
        self._view.setUpdatesEnabled(True)
        self.completed.emit(
            self.request_id,
            perf_counter() - self._started - self._paused_seconds,
        )


def _iter_model_search_matches(
    model: ResultsModel, projection: ResultSourceMap, document: QTextDocument, query: str,
) -> Iterator[tuple[int, int, int] | None]:
    """Search logical log rows and project only their matches into Qt."""
    last_row = None
    block_number = block_position = 0
    for match in iter_source_matches((line.text for line in model.iter_lines()), query):
        if match is None:
            yield None
            continue
        row, start, end = match
        if row != last_row:
            block_number = projection.block(row)
            block_position = document.findBlockByNumber(block_number).position()
            last_row = row
        yield block_position + start, block_position + end, block_number


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
    bookmarks_cleared = Signal()

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
        self._source_active = False
        self._rendering_paused = False
        self._results_query = ""
        self._snapshot_id = uuid4().hex
        self._return_position = None
        self._search_matches = SearchMatches()
        self._search_match_blocks = array("I")
        self._current_search_match: int | None = None
        self._searched_query: str | None = None
        self._search_from_viewport = True
        self._search_generation = 0
        self._search_work: Iterator[tuple[int, int, int] | None] | None = None
        self._pending_matches = SearchMatches()
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
        configure_action_button(self._maximize_button)
        self._maximize_button.setIcon(self._expand_icon)
        self._maximize_button.setIconSize(QSize(18, 18))
        self._maximize_button.setObjectName("maximizeResultsButton")
        self._maximize_button.setAccessibleName("Maximize results")
        self._maximize_button.setFixedSize(38, 28)
        self._maximize_button.setStyleSheet(
            "QPushButton#maximizeResultsButton {"
            " padding: 0;"
            "}"
            "QToolTip { font-weight: 400; }"
        )
        self._maximize_button.setToolTip("Expand results window")
        self._maximize_button.clicked.connect(self.toggle_maximized)
        header_layout.addWidget(self._maximize_button)
        self._source_button = QPushButton("Go to source")
        self._source_button.setObjectName("sourceToggleButton")
        self._source_button.setToolTip("Open the original file")
        configure_action_button(self._source_button)
        self._source_button.clicked.connect(self.toggle_source)
        header_layout.addWidget(self._source_button)
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
        self._source_search_count = QLabel()
        self._source_search_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._source_search_count.setMinimumWidth(84)
        self._count_stack = QStackedWidget()
        self._count_stack.setObjectName("searchCountStack")
        self._count_stack.addWidget(self._search_count_label)
        self._count_stack.addWidget(self._source_search_count)
        self._search_count_label.hide()
        header_layout.addWidget(self._count_stack)

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
            "Enable/disable line-wrapping"
        )
        self._line_wrap_check.toggled.connect(self.set_line_wrapping)
        header_layout.addWidget(self._line_wrap_check)
        panel_layout.addWidget(header)

        self._editor = ResultsEditor(self)
        self._source_map = self._editor.projection
        self._editor.setObjectName("resultsView")
        self._editor.setReadOnly(True)
        # Rendering is programmatic; retaining undo commands only wastes memory.
        self._editor.setUndoRedoEnabled(False)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
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
        self._editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._editor.customContextMenuRequested.connect(self._results_context_menu)
        self.source_view = SourceView(
            self, highlighter_factory=SearchMatchHighlighter,
            scrollbar_factory=SearchMarkerScrollBar, editor_style=_results_editor_style_sheet(),
        )
        self.source_view.search_status_changed.connect(self._source_search_count.setText)
        self._view_stack = QStackedLayout()
        self._view_stack.addWidget(self._editor)
        self._view_stack.addWidget(self.source_view)
        panel_layout.addLayout(self._view_stack, 1)
        self.bookmarks = ResultsBookmarks(self)
        panel_layout.insertWidget(1, self.bookmarks.strip)
        self._editor.gutter.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._editor.gutter.customContextMenuRequested.connect(
            lambda point: self._results_context_menu(
                self._editor.viewport().mapFromGlobal(self._editor.gutter.mapToGlobal(point))
            )
        )

    @property
    def source_active(self) -> bool:
        return self._source_active

    def set_source(
        self, lines: tuple[str, ...], total_line_count: int, *, snapshot_id: str | None = None,
    ) -> None:
        snapshot_id = snapshot_id if snapshot_id is not None else uuid4().hex
        if self._snapshot_id != snapshot_id:
            self.reset_for_loaded_file("")
        self._snapshot_id = snapshot_id
        self.source_view.set_source(lines, total_line_count)
        if self._source_active:
            self.source_view.ensure_page()
        self.bookmarks.refresh()

    def toggle_source(self) -> None:
        self.set_source_active(not self._source_active)

    def set_source_active(self, active: bool) -> None:
        if active == self._source_active:
            return
        if active:
            self._results_query = self._search_input.text()
        self._source_active = active
        self._view_stack.setCurrentWidget(self.source_view if active else self._editor)
        self._count_stack.setCurrentWidget(self._source_search_count if active else self._search_count_label)
        if not active:
            self._search_count_label.setVisible(bool(self._searched_query))
        self._source_button.setText("Go to results" if active else "Go to source")
        self._source_button.setToolTip("Open the results window" if active else "Open the original file")
        with QSignalBlocker(self._search_input), QSignalBlocker(self._line_wrap_check):
            self._search_input.setText(self.source_view.query if active else self._results_query)
            editor = self.source_view.editor if active else self._editor
            self._line_wrap_check.setChecked(editor.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap)
        self._search_input.setAccessibleName("Search retained source" if active else "Search results")
        self._search_input.setToolTip("Search for matches in the original file" if active else "Search for matches in the results")
        if active:
            self.source_view.ensure_page()
        elif self._return_position is not None:
            position, anchor, vertical, horizontal = self._return_position
            cursor = QTextCursor(self._editor.document())
            cursor.setPosition(anchor)
            cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
            self._editor.setTextCursor(cursor)
            self._editor.verticalScrollBar().setValue(vertical)
            self._editor.horizontalScrollBar().setValue(horizontal)
            self._return_position = None
        self.focus_editor()
        self.bookmarks.refresh()

    def source_line_at(self, point) -> int | None:
        location = self.result_location_at(point)
        return location.source.line if location is not None else None

    @property
    def model(self) -> ResultsModel | None:
        return self._editor.model

    def result_location_at(self, point) -> ResultLocation | None:
        """Resolve text under the pointer to a layout-independent location."""
        if self.is_rendering or self.model is None or not self.model.ready:
            return None
        block = self._editor.cursorForPosition(point).block()
        rect = self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset())
        if not rect.top() <= point.y() < rect.bottom():
            return None
        row = self._source_map.row(block.blockNumber())
        return self.model.location(row) if row is not None else None

    def show_result_location(self, location: ResultLocation | SourceLocation) -> bool:
        """Reveal an exact source line, preferring its original result category."""
        if self.is_rendering or self.model is None:
            return False
        row = self.model.resolve(location)
        if row is None:
            return False
        block = self._source_map.block(row)
        self._return_position = None
        self.set_source_active(False)
        cursor = QTextCursor(self._editor.document().findBlockByNumber(block))
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self._use_viewport_search_anchor()
        self.focus_editor()
        return True

    def show_source_line(
        self, number: int, *, highlight: bool = True, center_page: bool = False,
    ) -> None:
        cursor = self._editor.textCursor()
        self._return_position = (
            cursor.position(), cursor.anchor(),
            self._editor.verticalScrollBar().value(), self._editor.horizontalScrollBar().value(),
        )
        self.set_source_active(True)
        self.source_view.go_to_line(number, highlight=highlight, center_page=center_page)

    def _results_context_menu(self, point) -> None:
        location = self.result_location_at(point)
        number = location.source.line if location is not None else None
        menu = self._editor.createStandardContextMenu()
        menu.addSeparator()
        action = menu.addAction("Show source line")
        action.setEnabled(number is not None)
        if number is not None:
            action.triggered.connect(lambda: self.show_source_line(number))
        if location is not None:
            menu.addSeparator()
            self.bookmarks.add_menu_actions(menu, location)
        menu.exec(self._editor.viewport().mapToGlobal(point))
        menu.deleteLater()

    @property
    def editor(self) -> QPlainTextEdit:
        """Return the read-only editor displaying formatted results."""

        return self._editor

    @property
    def is_maximized(self) -> bool:
        return self._maximized

    def reset_for_loaded_file(self, source_name: str) -> None:
        """Clear old output while the newly staged source awaits analysis."""

        self.cancel_rendering()
        self._snapshot_id = uuid4().hex
        self.bookmarks.clear()
        self._source_map.clear()
        self._return_position = None
        self._results_query = ""
        self.source_view.reset()
        self._search_input.clear()
        self._clear_search_results()
        self._editor.clear()
        self._editor.setPlaceholderText("")

    def focus_editor(self) -> None:
        self._search_input.deselect()
        self._search_input.clearFocus()
        (self.source_view.editor if self._source_active else self._editor).setFocus()

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
        (self.source_view.editor if self._source_active else self._editor).setLineWrapMode(line_wrap_mode)

    @Slot(str)
    def _invalidate_search_results(self, _query: str) -> None:
        """Clear stale matches without searching while the user types."""

        if self._source_active:
            self.source_view.set_query(_query)
        else:
            self._results_query = _query
            self._clear_search_results()

    @Slot()
    def search_results(self) -> None:
        """Highlight a new query, or navigate down for an unchanged search."""

        if self._source_active:
            self.source_view.search()
            return
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
        """Search result content; generated presentation text is excluded."""

        query = self._results_query
        self._clear_search_results()
        self._searched_query = query
        if not query:
            return

        self._search_work = (
            _iter_model_search_matches(self.model, self._source_map, self._editor.document(), query)
            if self.model is not None and self.model.ready else
            _iter_search_matches(self._editor.document(), query)
        )
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
                self._search_matches = self._pending_matches
                self._pending_matches = SearchMatches()
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
                self._pending_matches.append(start, end)
                if not self._pending_blocks or self._pending_blocks[-1] != block:
                    self._pending_blocks.append(block)
        self._search_timer.start(1)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.cancel_search()
        self.source_view.reset()
        super().closeEvent(event)

    def cancel_search(self) -> None:
        """Invalidate pending batches and release their document references."""
        if self.is_searching:
            self._searched_query = None
            self._search_count_label.hide()
        self._search_generation += 1
        self._search_timer.stop()
        self._search_work = None
        self._pending_matches = SearchMatches()
        self._pending_blocks = array("I")
        self._pending_navigation = None
        self._search_highlighter.cancel()

    def _clear_search_results(self) -> None:
        self.cancel_search()
        self._search_matches = SearchMatches()
        self._search_match_blocks = array("I")
        self._current_search_match = None
        self._searched_query = None
        self._search_from_viewport = True
        self._search_count_label.hide()
        self._search_highlighter.set_matches(self._search_matches)
        self._search_marker_scrollbar.set_match_blocks(
            self._search_match_blocks,
            None,
        )
        self._editor.setExtraSelections([])

    @Slot()
    def find_next(self) -> None:
        """Move to the next result-search match, wrapping at the end."""

        if self._source_active:
            self.source_view.navigate(True)
        else:
            self._navigate_search(forward=True)

    @Slot()
    def find_previous(self) -> None:
        """Move to the previous result-search match, wrapping at the start."""

        if self._source_active:
            self.source_view.navigate(False)
        else:
            self._navigate_search(forward=False)

    def _navigate_search(self, *, forward: bool) -> None:
        if self._renderer is not None:
            return
        if self._searched_query != self._results_query:
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
                self._search_matches.starts,
                anchor.position(),
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
        self._source_map.clear()
        self._return_position = None
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
            source_map=self._source_map,
            model=ResultsModel(analysis, self._snapshot_id),
        )
        renderer.completed.connect(self._complete_rendering)
        renderer.failed.connect(self._fail_rendering)
        self._renderer = renderer
        renderer.start()
        self.set_rendering_paused(self._rendering_paused)
        self.bookmarks.refresh()

    def cancel_rendering(self) -> None:
        """Cancel the active incremental render, if any."""

        renderer = self._renderer
        self._renderer = None
        if renderer is None:
            return
        renderer.cancel()
        self._editor.set_model(None)
        self._source_map.clear()
        renderer.deleteLater()
        self.bookmarks.refresh()

    @property
    def is_rendering(self) -> bool:
        return self._renderer is not None

    def set_rendering_paused(self, paused: bool) -> None:
        # A hidden page can defer rendering before a renderer even exists.
        # That deferral must not pause the next renderer when the page opens.
        self._rendering_paused = paused if self._renderer is not None else False
        if self._renderer is not None:
            # Source is another view of the active document; finish its results
            # so analysis can complete without requiring a view switch.
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
        self.bookmarks.refresh()

    def prepend_scan_limit_warning(self, limit: int, total: int) -> None:
        message = fill(
            f"WARNING: Only {limit:,} of this file’s {total:,} lines were scanned because of the "
            '"Max lines scanned" setting. The scanner reads from the end/tail of the file, '
            f'so these results cover the last {limit:,} lines. The earlier lines were not '
            'scanned, and any matches in those lines are not included in these results.',
            width=100,
        ) + "\n\n" + fill(
            'If you want the entire file to be scanned, increase "Max lines scanned" '
            f'to at least {total:,} and press Analyze again. Do note that increasing this '
            'setting will cause more lines to be loaded and scanned. This can increase '
            'analysis and rendering time and will also consume more system memory.',
            width=100,
        )
        _prepend_result_header(self._editor, (
            ("WARNING: ", "warning", True),
            (message[len("WARNING: "):] + "\n\n", "muted", False),
        ))
        self.bookmarks.refresh()

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
        self.bookmarks.refresh()
        self.rendering_completed.emit(request_id, rendering_seconds)

    @Slot(int, str)
    def _fail_rendering(self, request_id: int, message: str) -> None:
        renderer = self.sender()
        if renderer is not self._renderer:
            return

        self._renderer = None
        self._editor.set_model(None)
        self._source_map.clear()
        renderer.deleteLater()
        self.bookmarks.refresh()
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
        model = ResultsModel(analysis, uuid4().hex)
        for _ in model.prepare():
            pass
        if isinstance(view, ResultsEditor):
            view.set_model(model)
        cursor = QTextCursor(view.document())
        cursor.beginEditBlock()
        for text, role, bold in _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
            model=model,
            on_summary=(lambda: mark_summary(cursor)) if isinstance(view, ResultsEditor) else None,
            on_excerpt=(lambda number, length: view.projection.append(
                cursor.blockNumber(), length, number,
            )) if isinstance(view, ResultsEditor) else None,
        ):
            _insert(
                cursor, text, role, bold=bold,
                structural=isinstance(view, ResultsEditor) and
                view.projection.row(cursor.blockNumber()) is None,
            )

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

    _prepend_result_header(view, (
        ("Performance timing\n", "heading", True),
        (f"Analysis time: {analysis_seconds:.3f} s\n", "muted", False),
        (f"Result rendering time: {rendering_seconds:.3f} s\n\n", "muted", False),
    ))


def _prepend_result_header(view: QPlainTextEdit, operations: tuple[RenderOperation, ...]) -> None:
    """Insert notices above the summary while preserving source row mapping."""
    blocks_before = view.document().blockCount()
    first_was_structural = isinstance(view.document().firstBlock().userData(), StructuralBlock)
    first_data = view.document().firstBlock().userData()
    first_summary = (first_data.first, first_data.last) if isinstance(first_data, SummaryBlock) else None
    view.setUpdatesEnabled(False)
    try:
        cursor = QTextCursor(view.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        for text, role, bold in operations:
            _insert(cursor, text, role, bold=bold, structural=True)
        # Inserting at the start splits the old first block; Qt leaves its user
        # data on the inserted block, so restore the displaced row's identity.
        cursor.block().setUserData(
            SummaryBlock(first=first_summary[0], last=first_summary[1]) if first_summary else
            StructuralBlock() if first_was_structural else None
        )
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        if isinstance(view, ResultsEditor):
            view.projection.header_blocks += view.document().blockCount() - blocks_before
            view.update_gutter()
        view.setUpdatesEnabled(True)


def _iter_analysis_render_operations(
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
    *,
    on_excerpt: Callable[[int, int], None] | None = None,
    on_summary: Callable[[], None] | None = None,
    model: ResultsModel | None = None,
) -> Iterator[RenderOperation]:
    """Yield ordered formatting operations without touching Qt widgets."""

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

    positive_entries = []
    zero_entries = []
    # Stable ordering keeps presets first, then custom literals, then regexes.
    ordered_counts = sorted(
        summary_counts,
        key=lambda item: 2 if item[0].startswith("regex_") else
        1 if item[0].startswith("custom_") else 0,
    )
    for key, match_count in ordered_counts:
        label = RESULT_LABEL_OVERRIDES.get(key, config.label_for(key))
        if match_count == 0:
            zero_entries.append((label, None))
        else:
            positive_entries.append((label, match_count))

    total_matches = sum(result.match_count for result in analysis.categories.values())
    yield f"Matches ({total_matches:,} total):\n", "heading", True
    if positive_entries:
        yield from _iter_positive_summary_entries(positive_entries)
    else:
        yield "0", "muted", False
    yield "\n", "body", False

    if zero_entries:
        yield "\nNo matches:\n", "heading", False
        yield from _iter_summary_entries(zero_entries)
        yield "\n", "muted", False

    if on_summary is not None:
        on_summary()

    presentations = (
        (section.presentation for section in model.sections)
        if model is not None else build_category_presentations(analysis)
    )
    for presentation in presentations:
        yield from _iter_category_render_operations(
            presentation, config, on_excerpt=on_excerpt,
        )


def _iter_positive_summary_entries(
    entries: list[tuple[str, int]],
) -> Iterator[RenderOperation]:
    """Fill three 19-character columns per row, with five spaces between them.

    Oversized entries keep their full label and count, extending only their row.
    """
    for index, (label, count) in enumerate(entries):
        if index:
            yield "\n" if index % SUMMARY_COLUMNS == 0 else " " * SUMMARY_COLUMN_GAP, "muted", False
        count_text = str(count)
        padding = " " * max(1, SUMMARY_COLUMN_WIDTH - len(label) - len(count_text))
        yield label + padding, _match_count_role(count), False
        yield count_text, "body", False


def _iter_summary_entries(
    entries: list[tuple[str, int | None]],
) -> Iterator[RenderOperation]:
    """Wrap plain-text lists at entry boundaries, preserving oversized entries."""
    line_length = 0
    for label, count in entries:
        count_text = "" if count is None else str(count)
        entry_length = len(label) + (1 + len(count_text) if count is not None else 0)
        if line_length:
            if line_length + 2 + entry_length > SUMMARY_LINE_LENGTH:
                yield "\n", "muted", False
                line_length = 0
            else:
                yield ", ", "muted", False
                line_length += 2
        if count is None:
            yield label, "muted", False
        else:
            yield f"{label} ", _match_count_role(count), False
            yield count_text, "body", False
        line_length += entry_length


def _iter_category_render_operations(
    presentation: CategoryPresentation,
    config: LogreaderConfig,
    *,
    on_excerpt: Callable[[int, int], None] | None = None,
) -> Iterator[RenderOperation]:
    if presentation.key == COMBINED_CATEGORY_KEY:
        yield "\n", "body", False
    else:
        label = RESULT_LABEL_OVERRIDES.get(presentation.key, config.label_for(presentation.key))
        yield f"\n{presentation.heading(label)}\n\n", "heading", True

    for excerpt_index, excerpt in enumerate(presentation.excerpts):
        if on_excerpt is not None and excerpt.lines:
            on_excerpt(excerpt.lines[0].number, len(excerpt.lines))
        for line in excerpt.lines:
            yield from _iter_result_line_render_operations(line)

        if (
            config.separate_entries
            and excerpt_index < len(presentation.excerpts) - 1
        ):
            yield "\n", "excerpt_gap", False



def _iter_result_line_render_operations(
    line: ResultLine,
) -> Iterator[RenderOperation]:
    if not line.is_match:
        yield f"{line.text}\n", "body", False
        return

    position = 0
    for span in line.match_spans:
        if span.start > position:
            yield line.text[position : span.start], "matched_text", False
        yield line.text[span.start : span.end], "match", True
        position = span.end
    yield f"{line.text[position:]}\n", "matched_text", False


def _match_count_role(match_count: int) -> str:
    return "hit_count" if match_count else "muted"


def _insert(
    cursor: QTextCursor,
    text: str,
    role: str,
    *,
    bold: bool = False,
    structural: bool = False,
) -> None:
    excerpt_gap = role == "excerpt_gap"
    if excerpt_gap:
        role = "body"
    key = (role, bold)
    text_format = _RESULT_FORMATS.get(key)
    if text_format is None:
        text_format = QTextCharFormat()
        text_format.setForeground(RESULT_COLORS[role])
        if bold:
            text_format.setFontWeight(QFont.Weight.Bold)
        _RESULT_FORMATS[key] = text_format
    first = cursor.block()
    cursor.insertText(text, text_format)
    # Mark completed structural blocks, including the starting block of a
    # partial formatting operation. The final empty block may be filled with
    # source text next, so leave its identity to that next insertion.
    block = first
    while block.isValid() and block.position() < cursor.position():
        block.setUserData(StructuralBlock() if structural else None)
        block = block.next()
    if excerpt_gap:
        first.setUserData(ExcerptGapBlock())
        size_excerpt_gap(first, cursor.document().defaultFont())


def _results_editor_style_sheet() -> str:
    return (
        "QPlainTextEdit {"
        f" background: {THEME_COLORS['background']};"
        f" color: {THEME_COLORS['body']};"
        " border: none;"
        f" selection-background-color: {THEME_COLORS['selection']};"
        " padding: 8px 8px 8px 4px;"
        "}"
        "QPlainTextEdit#resultsView { padding-top: 2px; }"
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
