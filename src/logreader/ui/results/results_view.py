"""Production results controls over a progressively filled native document."""
from array import array
from bisect import bisect_left
from math import ceil
from time import perf_counter
from uuid import uuid4
from PySide6.QtCore import QPoint, QSignalBlocker, Qt, QTimer, Signal, QThreadPool, Slot
from PySide6.QtGui import QColor, QKeySequence, QTextCharFormat, QTextCursor, QTextLayout
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget, QHBoxLayout
from .results_controls import ResultsControls
from .result_coordinates import TextPoint
from .retained_editor import SparseResultsEditor
from .result_scrollbar import SparsePositionScrollBar
from .range_loading import SparseLoader
from .result_presentation import PresentationModel
from .result_preparation import PreparationWorker
from .result_headers import scan_limit_operations
from .results_model import ResultsModel
from logreader.config import LogreaderConfig
from logreader.core import AnalysisResult
from logreader.ui.source_search import SourceMatches, iter_source_matches
from logreader.ui.theme import THEME_COLORS
from logreader.ui.widgets.input_menus import ScrollbarContextMenu
from logreader.ui.widgets.line_number_editor import LineNumberEditor

class LogicalMatches(SourceMatches):
    def __getitem__(self, index):
        return self.lines[index], self.starts[index], self.ends[index]


class SparseProjection:
    def __init__(self, editor):
        self.editor = editor

    def block(self, row):
        number = self.editor.ranges.block_for(self.editor.presentation.display_row(row))
        return -1 if number is None else number

    def row(self, number):
        display = self.editor.ranges.logical_at(number)
        if not isinstance(display, int):
            return None
        entry = self.editor.presentation.entry(display)
        return entry if isinstance(entry, int) else None

    def source_line(self, number):
        row = self.row(number)
        return self.editor.presentation.logical.line(row).number if row is not None else None


class DecoratedSparseEditor(SparseResultsEditor):
    bookmarks_changed = Signal()

    def __init__(self, *args, **kwargs):
        self.logical_bookmarks = False
        super().__init__(*args, **kwargs)

    def set_bookmarked_blocks(self, blocks):
        if self.logical_bookmarks:
            # ResultsBookmarks also reports unloaded destinations as -1. Its
            # logical items, rather than this native projection, own identity.
            self.bookmarks_changed.emit()
        else:
            super().set_bookmarked_blocks(blocks)


class ResultsView(ResultsControls):
    loading_status_changed = Signal(str)
    results_prepared = Signal()
    retired = Signal()

    def __init__(self, parent=None, **options):
        self.logical = None
        self._closed = False
        self._formats = {}
        self._overlays = {}
        self._bookmark_rows = {}
        self._bookmark_projection = None
        self._selection_key = None
        self._revision = 0
        self._search_identity = self._search_request = None
        self._pending_sequence = self._source_destination = None
        self.format_updates = self.decoration_passes = self.search_steps = 0
        self._preparation_generation = 0
        self._preparing = {}
        self._render_request_id = None
        self._prepared_result = None
        self._paused_at = None
        self._paused_seconds = 0.0
        self._retiring = 0
        self.loading_status = ""
        self._performance_text = ""
        super().__init__(parent, **options)
        self._search_matches = LogicalMatches()
        self._pending_matches = LogicalMatches()
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.timeout.connect(self._paint_decorations)
        self._navigation_status_timer = QTimer(self)
        self._navigation_status_timer.setSingleShot(True)
        self._navigation_status_timer.timeout.connect(self._progress)
        self._install_empty()
        self.destroyed.connect(lambda: setattr(self, "logical", None))

    def _empty_presentation(self):
        model = ResultsModel(AnalysisResult(0, {}, 0, {}), self._snapshot_id)
        for _ in model.prepare():
            pass
        presentation = PresentationModel(model, LogreaderConfig(), defer=True)
        presentation.ready = True
        return presentation

    def _install_empty(self):
        self._install_presentation(self._empty_presentation())
        self.logical = None
        self._editor.setPlaceholderText("")
        self._set_loading_status("")

    @property
    def has_retiring_results(self):
        return self._retiring > 0

    @Slot()
    def _retired(self):
        self._retiring -= 1
        if not self._retiring:
            self.retired.emit()

    def _install_presentation(self, presentation):
        old = self._editor
        font = old.font()
        wrapped = old.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap
        had_focus = old.hasFocus()
        if hasattr(self, "loader"):
            self.loader.cancel()
            old.navigation.invalidate()
            old._cancel_wheel()
            old._drag_timer.stop()
            previous = self.surface
        else:
            previous = old
        self._visible_timer.stop()
        self._navigation_status_timer.stop()
        self._formats.clear()
        self._overlays.clear()
        self._bookmark_rows.clear()
        self._selection_key = self._return_position = self._bookmark_projection = None
        self._view_stack.removeWidget(previous)
        previous.hide()
        old.setObjectName("")
        if hasattr(old, "presentation") and old.presentation.row_count:
            self._retiring += 1
            # QObject emits destroyed before deleting its children. Submit a
            # replacement read only after the editor and document are gone.
            previous.destroyed.connect(self._retired, Qt.ConnectionType.QueuedConnection)
        previous.deleteLater()
        self.logical = presentation.logical
        self._editor = DecoratedSparseEditor(presentation, self)
        editor = self._editor
        editor.setFont(font)
        self.surface = QWidget(self)
        row = QHBoxLayout(self.surface)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(editor, 1)
        self.global_scroll = SparsePositionScrollBar(editor, self.surface)
        row.addWidget(self.global_scroll)
        self._view_stack.insertWidget(0, self.surface)
        self._view_stack.setCurrentWidget(self.source_view if self.source_active else self.surface)
        self._source_map = SparseProjection(editor)
        self.loader = SparseLoader(editor)
        self.loader.is_active = lambda: not self._closed and not self._rendering_paused
        self.loader.progressed.connect(self._progress)
        self.loader.completed.connect(self._loaded)
        self.loader.failed.connect(self._loading_failed)
        editor.navigation.changed.connect(self._progress)
        editor.navigation.completed.connect(self._navigation_complete)
        editor.rows_appended.connect(self._progress)
        editor.logical_bookmarks = True
        editor.bookmarks_changed.connect(self._bookmarks_changed)
        editor.window_changed.connect(self._schedule_decorations)
        editor.updateRequest.connect(self._schedule_decorations)
        editor.viewport_navigated.connect(self._use_viewport_search_anchor)
        self._search_marker_scrollbar = editor.verticalScrollBar()
        for bar in (self.global_scroll, editor.horizontalScrollBar()):
            ScrollbarContextMenu(bar)
            bar.sliderPressed.connect(self._use_viewport_search_anchor)
            bar.actionTriggered.connect(self._use_viewport_search_anchor)
        editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        editor.customContextMenuRequested.connect(self._results_context_menu)
        editor.gutter.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        editor.gutter.customContextMenuRequested.connect(lambda point: self._results_context_menu(
            editor.viewport().mapFromGlobal(editor.gutter.mapToGlobal(point))))
        editor.set_wrapping(wrapped)
        if had_focus:
            editor.setFocus()

    def start_rendering(self, request_id, source_name, analysis, config, *, scan_limit=None):
        self.cancel_rendering()
        self._performance_text = ""
        self._render_request_id = request_id
        self._render_started = perf_counter()
        self._paused_at = None
        self._paused_seconds = 0.0
        self._clear_search_results()
        generation = self._preparation_generation
        headers = scan_limit_operations(*scan_limit) if scan_limit is not None else ()
        worker = PreparationWorker(generation, analysis, self._snapshot_id, config, header_operations=headers)
        worker.signals.completed.connect(self._prepared)
        worker.signals.failed.connect(self._preparation_failed)
        worker.signals.finished.connect(self._preparation_finished)
        self._preparing[generation] = worker
        self._renderer = worker
        self._set_loading_status("Preparing results…")
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object)
    def _prepared(self, generation, prepared):
        if self._closed or generation != self._preparation_generation or self._render_request_id is None:
            return
        self._renderer = None
        if self._rendering_paused:
            self._prepared_result = generation, prepared
            return
        self._clear_search_results()
        self._install_presentation(prepared.presentation)
        editor = self._editor
        total = editor.presentation.row_count
        end = self.loader._commit_end(0, min(total, 64)) if total else 0
        if end:
            editor.insert_range(0, end)
            with editor.changing():
                editor.set_top(TextPoint(0))
        self.bookmarks.refresh()
        self._progress()
        self.results_prepared.emit()
        # A signal handler may have replaced or closed the result set.
        if not self._closed and generation == self._preparation_generation:
            self.loader.start()

    @Slot(int)
    def _preparation_finished(self, generation):
        self._preparing.pop(generation, None)

    @Slot(int, str)
    def _preparation_failed(self, generation, message):
        if generation == self._preparation_generation:
            self._loading_failed(message)

    def _loading_failed(self, message):
        request_id = self._render_request_id
        self.cancel_rendering()
        self._set_loading_status(f"Loading failed: {message}")
        if request_id is not None:
            self.rendering_failed.emit(request_id, message)

    def _loaded(self):
        if isinstance(self.sender(), SparseLoader) and self.sender() is not self.loader:
            return
        request_id = self._render_request_id
        if request_id is None or not self.loader.done:
            return
        self._render_request_id = None
        elapsed = perf_counter() - self._render_started - self._paused_seconds
        self._progress()
        self.bookmarks.refresh()
        self.rendering_completed.emit(request_id, elapsed)

    @property
    def is_rendering(self):
        return self._render_request_id is not None

    @property
    def results_ready(self):
        return self.logical is not None and self.logical.ready

    def cancel_rendering(self):
        self._preparation_generation += 1
        self._render_request_id = None
        self._renderer = None
        self._prepared_result = None
        for worker in self._preparing.values():
            worker.cancel()
        if hasattr(self, "loader"):
            self.loader.set_paused(True)
        self._rendering_paused = False

    def set_rendering_paused(self, paused):
        if paused and self._paused_at is None and self.is_rendering:
            self._paused_at = perf_counter()
        elif not paused and self._paused_at is not None:
            self._paused_seconds += perf_counter() - self._paused_at
            self._paused_at = None
        self._rendering_paused = paused
        self.loader.set_paused(paused)
        if not paused and self._prepared_result is not None:
            prepared, self._prepared_result = self._prepared_result, None
            self._prepared(*prepared)

    def reset_for_loaded_file(self, source_name):
        self.cancel_rendering()
        self._performance_text = ""
        self.cancel_search()
        self._snapshot_id = uuid4().hex
        self.bookmarks.clear()
        self._results_query = ""
        self._searched_query = None
        self.source_view.reset()
        with QSignalBlocker(self._search_input):
            self._search_input.clear()
        self._install_empty()
        self._clear_search_results()

    def _set_loading_status(self, text):
        if text != self.loading_status:
            self.loading_status = text
            self.loading_status_changed.emit(text)

    def _progress(self):
        self._navigation_status_timer.stop()
        if self._closed or self.logical is None:
            return
        editor = self._editor
        pending = editor.navigation.pending
        waiting = False
        if pending is not None:
            remaining = .12 - (perf_counter() - pending.started)
            waiting = editor.navigation.loading_text or remaining <= 0
            if not waiting:
                self._navigation_status_timer.start(max(1, ceil(remaining * 1000)))
        if waiting:
            prefix = "Loading requested area" if editor.navigation.loading_text else "Preparing view"
        elif self.loader.done:
            self._set_loading_status(f"Results loaded{self._performance_text}")
            return
        else:
            prefix = "Background loading"
        percentage = (100 if self.loader.done else
                      max(1, min(99, editor.ranges.loaded_count * 100 // editor.presentation.row_count)))
        # Figure spaces reserve the same width as digits in the status font.
        self._set_loading_status(f"{prefix}: {percentage:\u2007>3}%{self._performance_text}")

    def search_results(self):
        if self.source_active:
            self.source_view.search()
        elif self.results_ready:
            if self._searched_query != self._search_input.text():
                self._refresh_search_matches()
            else:
                self.find_next()

    def result_location_at(self, point):
        if not self.results_ready:
            return None
        block = self._editor.cursorForPosition(point).block()
        rect = self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset())
        if not rect.top() <= point.y() < rect.bottom():
            return None
        row = self._source_map.row(block.blockNumber())
        return self.model.location(row) if row is not None else None

    def prepend_performance_timings(self, analysis_seconds, rendering_seconds):
        self._performance_text = f" | Analysis: {analysis_seconds:.3f} s | Rendering: {rendering_seconds:.3f} s"
        self._progress()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._pending_navigation = None
            self._editor.navigation.cancel()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Copy):
            (self.source_view.editor if self.source_active else self._editor).copy()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.SelectAll):
            (self.source_view.editor if self.source_active else self._editor).selectAll()
            event.accept()
        else:
            super().keyPressEvent(event)

    @property
    def model(self):
        return self.logical

    def set_line_wrapping(self, enabled):
        if self.source_active:
            self.source_view.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap)
        else:
            self._editor.set_wrapping(enabled)
            self._schedule_decorations()

    def _navigation_complete(self, _measurement):
        self._schedule_decorations()

    def show_result_location(self, location, *, result_set_id=None):
        editor = self._editor
        if self._closed or self.model is None or (result_set_id is not None and result_set_id is not editor.result_set_id):
            return False
        if self.model.resolve(location) is None:
            return False
        self._return_position = None
        self.set_source_active(False)
        self._use_viewport_search_anchor()
        return editor.go_to_location(location, result_set_id=editor.result_set_id)

    def show_source_line(self, number, *, highlight=True, center_page=False):
        self._source_destination = number, highlight, center_page
        if self.source_active:
            self.source_view.go_to_line(number, highlight=highlight, center_page=center_page)
            self._source_destination = None
        else:
            self.set_source_active(True)

    def set_source_active(self, active):
        if self._closed or active == self._source_active:
            return
        editor = self._editor
        if active:
            self._results_query = self._search_input.text()
            self._return_position = (editor.result_set_id, editor.top_point(), editor.anchor,
                                     editor.caret, editor.horizontalScrollBar().value())
            editor.navigation.cancel()
            self._pending_navigation = None
            self._visible_timer.stop()
        self._source_active = active
        self._view_stack.setCurrentWidget(self.source_view if active else self.surface)
        self._count_stack.setCurrentWidget(self._source_search_count if active else self._search_count_label)
        self._search_count_label.setVisible(bool(self._searched_query) and not active)
        self._source_button.setText("Go to results" if active else "Go to source")
        self._source_button.setProperty("sourceActive", active)
        self._source_button.setToolTip("Open the results window" if active else "Open the original file")
        self._source_button.style().unpolish(self._source_button)
        self._source_button.style().polish(self._source_button)
        self._source_button.update()
        with QSignalBlocker(self._search_input), QSignalBlocker(self._line_wrap_check):
            self._search_input.setText(self.source_view.query if active else self._results_query)
            shown_editor = self.source_view.editor if active else editor
            self._line_wrap_check.setChecked(shown_editor.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap)
        self._search_input.setAccessibleName("Search retained source" if active else "Search results")
        self._search_input.setToolTip("Search for matches in the original file" if active else "Search for matches in the results")
        if active:
            destination, self._source_destination = self._source_destination, None
            if destination is None:
                self.source_view.ensure_page()
            else:
                number, highlight, center = destination
                self.source_view.go_to_line(number, highlight=highlight, center_page=center)
        else:
            saved, self._return_position = self._return_position, None
            if saved is not None and saved[0] is editor.result_set_id:
                _, top, anchor, caret, horizontal = saved
                with editor.changing():
                    editor.anchor, editor.caret = anchor, caret
                    editor._project_selection()
                    editor.horizontalScrollBar().setValue(horizontal)
                editor.navigate_to(top)
            self._schedule_decorations()
        self.loader.start()
        self.bookmarks.refresh()
        self.focus_editor()

    def _invalidate_search_results(self, query):
        if self.source_active:
            self.source_view.set_query(query)
            return
        self._results_query = query
        self._clear_search_results()

    def _clear_search_results(self):
        self.cancel_search()
        self._search_matches = LogicalMatches()
        self._current_search_match = None
        self._searched_query = None
        self._search_from_viewport = True
        self._revision += 1
        self.global_scroll.set_marker_rows(matches=array("Q"))
        self._search_count_label.hide()
        self._editor.setExtraSelections([])
        self._selection_key = None
        self._schedule_decorations(force=True)

    def cancel_search(self):
        self._search_generation += 1
        self._search_timer.stop()
        if self._search_work is not None:
            self._search_work.close()
        self._search_work = None
        self._pending_matches = LogicalMatches()
        self._pending_blocks = array("Q")
        self._pending_navigation = None
        self._search_identity = None
        if hasattr(self, "global_scroll") and self._editor.navigation.pending is self._search_request:
            self._editor.navigation.cancel()
        self._search_request = None

    def _refresh_search_matches(self):
        self._clear_search_results()
        self._searched_query = self._results_query
        if not self._searched_query or not self.results_ready:
            return
        self._search_identity = self._editor.result_set_id
        self._search_work = iter_source_matches((line.text for line in self.model.iter_lines()), self._searched_query)
        self._search_count_label.setText("Searching…")
        self._search_count_label.show()
        self._search_timer.start(0)

    def _advance_search(self, generation):
        if (self._closed or generation != self._search_generation or self._search_work is None
                or self._search_identity is not self._editor.result_set_id):
            return
        deadline = perf_counter() + .004
        while perf_counter() < deadline:
            self.search_steps += 1
            try:
                match = next(self._search_work)
            except StopIteration:
                self._search_work = None
                self._search_matches, self._pending_matches = self._pending_matches, LogicalMatches()
                self.global_scroll.set_marker_rows(matches=self._pending_blocks)
                self._pending_blocks = array("Q")
                self._revision += 1
                direction, self._pending_navigation = self._pending_navigation, None
                if (direction is not None and not self.source_active
                        and self._pending_sequence == self._editor.navigation._sequence):
                    self._navigate_search(forward=direction)
                self._update_count()
                self._schedule_decorations(force=True)
                return
            if match is not None:
                row, start, end = match
                if not len(self._pending_matches) or self._pending_matches.lines[-1] != row:
                    self._pending_blocks.append(self._editor.presentation.display_row(row))
                self._pending_matches.append(row, start, end)
        self._search_timer.start(1)

    def _navigate_search(self, *, forward):
        if self._closed:
            return
        if self._searched_query != self._results_query:
            self._refresh_search_matches()
        if self.is_searching:
            self._pending_navigation = forward
            self._pending_sequence = self._editor.navigation._sequence
            return
        if not len(self._search_matches):
            return
        editor = self._editor
        if self._current_search_match is None or self._search_from_viewport:
            top = editor.top_point()
            index = bisect_left(self._search_matches, (top.row, top.column),
                key=lambda item: (editor.presentation.display_row(item[0]), item[1]))
            current = (index if forward else index - 1) % len(self._search_matches)
        else:
            current = (self._current_search_match + (1 if forward else -1)) % len(self._search_matches)
        row, start, _ = self._search_matches[current]
        self._current_search_match = current
        editor.go_to_search_result(self.model.location(row), start, result_set_id=editor.result_set_id)
        self._search_request = editor.navigation.pending
        self._search_from_viewport = False
        self._update_count()
        self._schedule_decorations(force=True)

    def _update_count(self):
        if not self.is_searching:
            current = 0 if self._current_search_match is None else self._current_search_match + 1
            self._search_count_label.setText(f"{current} / {len(self._search_matches)}" if len(self._search_matches) else "No matches")
            self._search_count_label.setVisible(bool(self._searched_query) and not self.source_active)

    def _bookmarks_changed(self):
        rows = {}
        if self.model is None:
            return
        for source, bookmark in self.bookmarks.items.items():
            if bookmark.source_only:
                continue
            preferred = self.model.resolve(bookmark.location)
            for row in self.model.rows_for_source(source):
                rows[self._editor.presentation.display_row(row)] = row == preferred
        self._bookmark_rows = rows
        self.global_scroll.set_marker_rows(bookmarks=rows)
        self._bookmark_projection = None
        self._schedule_decorations(force=True)

    def _schedule_decorations(self, *_args, force=False):
        if self._closed or self.source_active:
            return
        if not (force or self._searched_query or self._bookmark_rows or self._formats):
            return
        if not self._visible_timer.isActive():
            self._visible_timer.start(0)

    def _visible_ranges(self):
        editor = self._editor
        height, width = editor.viewport().height(), editor.viewport().width()
        block = editor.firstVisibleBlock()
        visible = []
        while block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            display = editor.ranges.logical_at(block.blockNumber())
            if not isinstance(display, int):
                break
            rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
            if rect.top() >= height:
                break
            row = self._source_map.row(block.blockNumber())
            if row is not None and rect.bottom() > 0:
                if editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap:
                    y = max(0, min(height - 1, round(rect.top() + editor.fontMetrics().height() / 2)))
                    left = editor.cursorForPosition(QPoint(0, y)).positionInBlock()
                    right = editor.cursorForPosition(QPoint(width - 1, y)).positionInBlock()
                else:
                    left = 0 if rect.top() >= 0 else editor.cursorForPosition(QPoint(0, 0)).positionInBlock()
                    right = block.length() - 1 if rect.bottom() <= height else editor.cursorForPosition(QPoint(width - 1, height - 1)).positionInBlock()
                visible.append((display, row, block, max(0, left - 2), right + 2))
            block = block.next()
        return visible

    def _paint_decorations(self):
        if self._closed or self.source_active or not self._editor.isVisible():
            return
        self.decoration_passes += 1
        editor = self._editor
        visible = self._visible_ranges()
        shown = {display for display, *_ in visible}
        changed = False
        wrap = editor.lineWrapMode()
        match_format = QTextCharFormat()
        match_format.setBackground(QColor(THEME_COLORS["ui_primary"]))
        match_format.setForeground(QColor("#ffffff"))
        with editor.preserving_reading_position():
            # Formats stay bounded by a viewport, not by visited or loaded rows.
            # Resolve each block again: filling an earlier gap changes numbers.
            for display in tuple(self._formats):
                if display not in shown or not self._searched_query:
                    block = editor._block(display)
                    if block.isValid() and block.layout().formats():
                        block.layout().setFormats([])
                        changed = True
                    del self._formats[display]
                    self._overlays.pop(display, None)
            for display, row, block, left, right in visible:
                if not self._searched_query or self.is_searching:
                    continue
                cached = self._formats.get(display)
                version = (self._revision, wrap, block)
                if cached and cached[:3] == version and cached[3] <= left and cached[4] >= right:
                    continue
                padding = max(256, (right - left) // 2) if wrap != QPlainTextEdit.LineWrapMode.NoWrap else 0
                cover_left, cover_right = max(0, left - padding), right + padding
                formats = []
                index = max(0, bisect_left(self._search_matches, (row, cover_left, -1)) - 1)
                while index < len(self._search_matches):
                    match_row, start, end = self._search_matches[index]
                    if match_row > row or (match_row == row and start > cover_right):
                        break
                    if match_row == row and end > cover_left:
                        if formats and formats[-1].start + formats[-1].length == start:
                            formats[-1].length = end - formats[-1].start
                        else:
                            span = QTextLayout.FormatRange()
                            span.start, span.length, span.format = start, end - start, match_format
                            formats.append(span)
                    index += 1
                if block.length() > 8192 and len(formats) <= 8:
                    # QTextLayout.setFormats invalidates even color-only
                    # shaping of an entire giant line. Native paint selections
                    # over the visible part reuse that line's existing layout.
                    # Many disjoint selections make every native paint costly,
                    # so use cached layout formats for that case instead.
                    if block.layout().formats():
                        block.layout().setFormats([])
                    self._overlays[display] = tuple((span.start, span.length) for span in formats)
                    self.format_updates += 1
                    changed = True
                else:
                    self._overlays.pop(display, None)
                    if formats or block.layout().formats():
                        block.layout().setFormats(formats)
                        editor.document().markContentsDirty(block.position(), block.length())
                        self.format_updates += 1
                        changed = True
                self._formats[display] = (*version, cover_left, cover_right)
            projection = tuple((display, block.blockNumber(), self._bookmark_rows[display])
                               for display, _, block, _, _ in visible if display in self._bookmark_rows)
            if projection != self._bookmark_projection:
                self._bookmark_projection = projection
                LineNumberEditor.set_bookmarked_blocks(editor, {number: preferred for _, number, preferred in projection})
                changed = True
            current = None
            if self._current_search_match is not None and self._current_search_match < len(self._search_matches):
                row, start, end = self._search_matches[self._current_search_match]
                for display, logical, block, left, right in visible:
                    if row == logical and end > left and start <= right:
                        current = (display, block, start, end)
                        break
            overlays = tuple((display, block, self._overlays[display], display in self._bookmark_rows)
                             for display, _, block, _, _ in visible if display in self._overlays)
            selection_key = current, overlays
            if selection_key != self._selection_key:
                self._selection_key = selection_key
                selections = []
                for _, block, spans, bookmarked in overlays:
                    for start, length in spans:
                        selection = QTextEdit.ExtraSelection()
                        selection.cursor = QTextCursor(block)
                        selection.cursor.setPosition(block.position() + start)
                        selection.cursor.setPosition(block.position() + start + length, QTextCursor.MoveMode.KeepAnchor)
                        selection.format = QTextCharFormat(match_format)
                        if bookmarked:
                            selection.format.clearBackground()
                        selections.append(selection)
                if current is not None:
                    _, block, start, end = current
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(block)
                    position = block.position()
                    selection.cursor.setPosition(position + start)
                    selection.cursor.setPosition(position + end, QTextCursor.MoveMode.KeepAnchor)
                    selection.format.setBackground(QColor(THEME_COLORS["search_current"]))
                    selection.format.setForeground(QColor(THEME_COLORS["background"]))
                    selections.append(selection)
                editor.setExtraSelections(selections)
                changed = True
        if changed:
            editor._retained_frame = None
            editor.viewport().update()

    def closeEvent(self, event):  # noqa: N802
        self._closed = True
        self.cancel_search()
        self._visible_timer.stop()
        self._formats.clear()
        self._overlays.clear()
        self._bookmark_rows.clear()
        self._search_matches = LogicalMatches()
        self._selection_key = self._return_position = None
        self.source_view.reset()
        self.cancel_rendering()
        self._editor.navigation.invalidate()
        super().closeEvent(event)
