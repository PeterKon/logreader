"""Qt results panel and incremental rendering for Logreader."""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from textwrap import fill
from typing import Callable, Iterator
from uuid import uuid4

from PySide6.QtCore import (
    QElapsedTimer,
    QSignalBlocker,
    QSize,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
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
    QSpinBox,
    QStackedWidget,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...config import LogreaderConfig
from ..bookmarks import ResultsBookmarks
from ...core import AnalysisResult
from ...search_storage import SearchMatches
from ..widgets.search_widgets import SearchMatchHighlighter, SearchMarkerScrollBar
from .result_source_map import ResultSourceMap
from .results_editor import ResultsEditor
from .results_renderer import (
    IncrementalAnalysisRenderer, render_analysis, prepend_performance_timings, _prepend_result_header,
)
from .results_model import ResultLocation, ResultsModel, SourceLocation
from ..source_search import iter_source_matches
from ..source_view import SourceView
from ..widgets.input_menus import InputContextMenu, ScrollbarContextMenu
from ..theme import THEME_COLORS, configure_action_button, configure_clear_button, vertical_resize_icon


INCREMENTAL_SEARCH_BATCH_MS = 4
SEARCH_CHUNK_SIZE = 4096
CheckBoxFactory = Callable[[], QCheckBox]
SpinBoxFactory = Callable[[], QSpinBox]


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
        InputContextMenu(self._search_input, undo=True)
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
        self._search_navigation.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
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
            ScrollbarContextMenu(scrollbar)
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
        panel_layout.insertWidget(1, self.bookmarks.bar)
        self._editor.gutter.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._editor.gutter.customContextMenuRequested.connect(
            lambda point: self._results_context_menu(
                self._editor.viewport().mapFromGlobal(self._editor.gutter.mapToGlobal(point))
            )
        )
        source_editor = self.source_view.editor
        source_editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        source_editor.customContextMenuRequested.connect(self._source_context_menu)
        source_editor.gutter.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        source_editor.gutter.customContextMenuRequested.connect(
            lambda point: self._source_context_menu(
                source_editor.viewport().mapFromGlobal(source_editor.gutter.mapToGlobal(point))
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
        self._exec_line_context_menu(self._editor, point, location, show_source=True)

    def _exec_line_context_menu(self, editor, point, location, *, show_source=False) -> None:
        source = location.source if isinstance(location, ResultLocation) else location
        menu = editor.createStandardContextMenu()
        editor.set_context_target(editor.cursorForPosition(point).block() if source else None)
        try:
            if source is not None:
                menu.addSeparator()
                menu.addAction(f"Line {source.line:,}").setEnabled(False)
            if show_source:
                if source is None:
                    menu.addSeparator()
                action = menu.addAction("Show in source")
                action.setEnabled(source is not None)
                if source is not None:
                    action.triggered.connect(lambda: self.show_source_line(source.line)
                                             if source.snapshot_id == self._snapshot_id else None)
            if location is not None:
                self.bookmarks.add_menu_actions(menu, location)
            menu.exec(editor.viewport().mapToGlobal(point))
        finally:
            editor.set_context_target(None)
            menu.deleteLater()

    def source_location_at(self, point) -> SourceLocation | None:
        editor = self.source_view.editor
        if not self.source_view.lines:
            return None
        block = editor.cursorForPosition(point).block()
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        if not rect.top() <= point.y() < rect.bottom():
            return None
        number = editor.source_number(block.blockNumber())
        if not (self.source_view.first_line + self.source_view.page_start <= number <
                self.source_view.first_line + self.source_view.page_end):
            return None
        return SourceLocation(self._snapshot_id, number)

    def _source_context_menu(self, point) -> None:
        location = self.source_location_at(point)
        self._exec_line_context_menu(self.source_view.editor, point, location)

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
