"""Source display using retained, demand-loaded Qt ranges."""

from array import array
from bisect import bisect_left, bisect_right
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QToolTip,
    QVBoxLayout, QWidget,
)

from .results.range_loading import ReadingMove, SparseLoader
from .results.result_coordinates import TextPoint
from .results.result_scrollbar import ScrollSurface
from .source_editor import SourceEditor
from .source_model import SourcePresentation
from .source_search import SourceMatches, iter_source_matches
from .theme import THEME_COLORS, configure_action_button
from .widgets.input_menus import InputContextMenu, ScrollbarContextMenu


class SourceView(QWidget):
    status_changed = Signal()
    search_status_changed = Signal(str)
    editor_changed = Signal(object)
    retired = Signal()
    ready_changed = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.lines = ()
        self.total_line_count = 0
        self.target_line = None
        self.bookmarked_lines = set()
        self.query = ""
        self.search_status = ""
        self.searched_query = None
        self.matches = SourceMatches()
        self.current_match = None
        self._search_work = self._search_request = self._search_identity = None
        self._pending_navigation = self._pending_sequence = None
        self._pending = SourceMatches()
        self._pending_markers = array("Q")
        self._from_viewport = True
        self._saved_position = None
        self._selection_key = None
        self._screen_geometry = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._advance_search)
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.timeout.connect(self._paint_decorations)
        self.loader = None
        self.editor = None
        self._retiring = 0
        self._active = True
        self._has_snapshot = self._ready = False
        self._materialized = False
        self.status_message = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.navigation_controls = QWidget(self)
        self.navigation_controls.setObjectName("sourceNavigationControls")
        controls = QHBoxLayout(self.navigation_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        separator = QFrame()
        separator.setObjectName("sourceNavigationSeparator")
        separator.setFixedSize(1, 22)
        separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']}; border: none;"
        )
        controls.addWidget(separator)
        self.goto_input = QLineEdit()
        self.goto_input.setObjectName("sourceGoToLine")
        self.goto_input.setAccessibleName("Original source line number")
        self.goto_input.setPlaceholderText("Line number")
        self.goto_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.goto_input.setMaximumWidth(125)
        InputContextMenu(self.goto_input)
        controls.addWidget(self.goto_input)
        self.goto_button = QPushButton("Go to line")
        self.goto_button.setObjectName("sourceGoToLineButton")
        configure_action_button(self.goto_button)
        controls.addWidget(self.goto_button)
        self.goto_input.returnPressed.connect(self.go_to_input)
        self.goto_input.editingFinished.connect(self._format_line_input)
        self.goto_button.clicked.connect(self.go_to_input)

        self._install_editor(SourcePresentation((), 0, uuid4().hex))
        self.reset()

    def _install_editor(self, presentation):
        old = self.editor
        font = old.font() if old is not None else None
        wrapped = old is not None and old.lineWrapMode() != old.LineWrapMode.NoWrap
        if old is not None:
            old.set_context_target(None)
            old.window_changed.disconnect(self._refresh)
            old.updateRequest.disconnect(self._schedule_decorations)
            old.reading_started.disconnect(self._use_viewport_anchor)
            old.navigation.changed.disconnect(self._refresh)
            old.navigation.invalidate()
            old._cancel_wheel()
            old._drag_timer.stop()
            old._rebase_timer.stop()
            previous = self.surface
            self.layout().removeWidget(previous)
            previous.hide()
            old.setObjectName("")
            self._retiring += 1
            # The queued signal runs after Qt deletes the editor and document.
            previous.destroyed.connect(self._retired, Qt.ConnectionType.QueuedConnection)
            previous.deleteLater()
        self.editor = SourceEditor(presentation, self)
        if font is not None:
            self.editor.setFont(font)
        self.editor.set_wrapping(wrapped)
        surface = self.surface = ScrollSurface(self.editor, self)
        self.global_scroll = surface.global_scroll
        for bar in (self.global_scroll, self.editor.horizontalScrollBar()):
            ScrollbarContextMenu(bar)
            bar.sliderPressed.connect(self._use_viewport_anchor)
            bar.actionTriggered.connect(self._use_viewport_anchor)
        self.global_scroll.valueChanged.connect(self._use_viewport_anchor)
        self.layout().addWidget(surface, 1)
        self.editor.window_changed.connect(self._refresh)
        self.editor.updateRequest.connect(self._schedule_decorations)
        self.editor.reading_started.connect(self._use_viewport_anchor)
        self.editor.navigation.changed.connect(self._refresh)
        self.editor_changed.emit(self.editor)
        surface.show()

    def _retired(self):
        self._retiring -= 1
        if not self._retiring:
            self.retired.emit()

    @property
    def has_retiring_editors(self):
        return self._retiring > 0

    @property
    def is_ready(self):
        return self._ready

    def _set_ready(self, ready):
        if ready != self._ready:
            self._ready = ready
            self.ready_changed.emit(ready)

    @property
    def first_line(self):
        return self.total_line_count - len(self.lines) + 1

    @property
    def is_searching(self):
        return self._search_work is not None

    def _replace_snapshot(self, lines, total, snapshot_id, message, *, loaded=False):
        self.cancel_search()
        self._visible_timer.stop()
        self._selection_key = self._saved_position = None
        self._has_snapshot = loaded
        self._set_ready(False)
        if self.loader is not None:
            old = self.loader
            old.cancel()
            self.editor.navigation.needs_loading.disconnect(old._requested)
            self.editor.navigation.changed.disconnect(old.start)
            self.editor.window_changed.disconnect(old._geometry_changed)
            old.deleteLater()
        self.loader = None
        self.lines, self.total_line_count = lines, total
        self.target_line = None
        self.bookmarked_lines.clear()
        self.query = self.search_status = ""
        self.search_status_changed.emit("")
        self._materialized = False
        self.goto_input.clear()
        self.goto_input.setToolTip("Enter a line number to jump to")
        presentation = SourcePresentation(lines, total, snapshot_id)
        if self.editor.presentation.row_count:
            self._install_editor(presentation)
        else:
            self.editor.setExtraSelections([])
            self.editor.set_results(presentation)
        self.editor.setPlaceholderText(message)
        self.global_scroll.set_marker_rows(matches=(), bookmarks=())
        self.global_scroll._painted_option = None
        self.global_scroll.setVisible(bool(lines))
        self.loader = SparseLoader(self.editor, background=False)
        self.loader.is_active = lambda: self._active and self.editor.isVisible()
        self.loader.progressed.connect(self._refresh)
        self.loader.failed.connect(self._refresh)
        self.goto_input.setEnabled(bool(lines))
        self.goto_button.setEnabled(bool(lines))
        self._refresh()
        self.editor.update_gutter()
        self.global_scroll.sync_position()

    def reset(self, message="Source is not loaded yet."):
        self._replace_snapshot((), 0, uuid4().hex, message)

    def set_source(self, lines, total_line_count, *, snapshot_id=None):
        self._replace_snapshot(lines, total_line_count, snapshot_id or uuid4().hex,
                               "Empty source file" if not lines else "", loaded=True)

    def _retained_range(self):
        return f"Available lines: {self.first_line:,}-{self.total_line_count:,}" if self.lines else "Empty source file"

    def ensure_view(self):
        if not self._active or not self.isVisible():
            return
        saved, self._saved_position = self._saved_position, None
        if saved is not None and saved[0] is self.editor.result_set_id:
            _, top, anchor, caret, horizontal = saved
            with self.editor.changing():
                self.editor.anchor, self.editor.caret = anchor, caret
                self.editor._project_selection()
                self.editor.horizontalScrollBar().setValue(horizontal)
            self.editor.navigate_to(top)
        if self.lines and not self._materialized:
            self._materialized = True
            self.editor.navigate_to(TextPoint(0))
        self._schedule_decorations()

    def suspend(self):
        editor = self.editor
        if self._saved_position is None:
            self._saved_position = (editor.result_set_id, editor.top_point(), editor.anchor,
                                    editor.caret, editor.horizontalScrollBar().value())
        self._pending_navigation = self._search_request = None
        editor.navigation.cancel()
        editor._cancel_wheel()
        editor._drag_timer.stop()
        editor._dragging = False
        if self.loader is not None:
            self.loader.set_paused(True)
        self._visible_timer.stop()

    def set_active(self, active):
        self._active = active
        if not active:
            self._search_timer.stop()
            self.suspend()
        else:
            if self.is_searching:
                self._search_timer.start(0)
            if self.isVisible():
                self.loader.set_paused(False)
                self.ensure_view()

    def go_to_line(self, number, *, highlight=True, center=False):
        row = number - self.first_line
        if not 0 <= row < len(self.lines):
            self._show_line_error(f"Line {number:,} is not loaded. {self._retained_range()}")
            return False
        QToolTip.hideText()
        self.goto_input.setToolTip("Enter a line number to jump to")
        self.goto_input.setText(f"{number:,}".replace(",", " "))
        if highlight:
            self.target_line = number
        self._saved_position = None
        self._use_viewport_anchor()
        self._materialized = True
        if center:
            point = TextPoint(row)
            half_screen = max(0, (self.editor.viewport().height() // self.editor.fontMetrics().height() - 1) // 2)
            return self.editor.navigation.request(point, move_caret=True, reveal_column=True,
                movement=ReadingMove(point, -half_screen, False), center=True)
        return self.editor.navigate_to(TextPoint(row), move_caret=True, reveal_column=True)

    def _show_line_error(self, message):
        self.goto_input.setToolTip(message)
        QToolTip.showText(self.goto_input.mapToGlobal(self.goto_input.rect().bottomLeft()), message, self.goto_input)

    def _format_line_input(self):
        value = "".join(self.goto_input.text().split())
        if value.isascii() and value.isdecimal() and len(value) <= 20:
            self.goto_input.setText(f"{int(value):,}".replace(",", " "))

    def go_to_input(self):
        self._format_line_input()
        value = "".join(self.goto_input.text().split())
        if not value.isascii() or not value.isdecimal() or len(value) > 20:
            self._show_line_error(f"Enter a valid line number. {self._retained_range()}")
            return
        self.go_to_line(int(value))

    def _refresh(self, *_args):
        if self.loader is not None and self.loader.error:
            message = self.loader.error
        elif not self._has_snapshot:
            message = self.editor.placeholderText()
        elif self.editor.navigation.pending is not None:
            message = "Preparing view..."
        else:
            count = len(self.lines)
            shown = f"{count:,}" if count == self.total_line_count else f"{count:,} of {self.total_line_count:,}"
            message = f"{shown} {'line' if self.total_line_count == 1 else 'lines'} shown"
        if message != self.status_message:
            self.status_message = message
            self.status_changed.emit()
        if not self._has_snapshot or self.editor.navigation.pending is not None:
            self._set_ready(False)
        elif not self.lines:
            self._set_ready(True)
        elif self.editor.isVisible():
            self._set_ready(self._materialized and self.editor.viewport_evidence()["useful"]
                            and not (self.loader is not None and self.loader.error))
        self._schedule_decorations()

    def _schedule_decorations(self, *_args):
        if self.editor.isVisible() and not self._visible_timer.isActive():
            self._visible_timer.start(0)

    def _paint_decorations(self):
        editor = self.editor
        if not editor.isVisible():
            return
        # Only visible rows and visible columns participate, including on a
        # giant wrapped line. No match causes offscreen insertion or shaping.
        visible = editor.visible_ranges()
        geometry = editor._end_geometry()
        resized = geometry != self._screen_geometry
        self._screen_geometry = geometry
        # Enlarging or unwrapping the view can expose the next unloaded gap.
        # Fill that screen cooperatively while retaining its reading position.
        if (resized and self._active and self._materialized and self.lines and visible
                and editor.navigation.pending is None and not self.loader.paused
                and not editor._pending_wheel and not editor._dragging
                and not self.loader.error and visible[-1][0] + 1 < len(self.lines)
                and not editor._screen_covered and not editor.viewport_evidence()["useful"]):
            editor.navigate_to(editor.top_point())
        bookmarks = {block.blockNumber(): True for row, block, *_ in visible
                     if self.first_line + row in self.bookmarked_lines}
        spans = []
        target = current = None
        for row, block, left, right in visible:
            number = self.first_line + row
            if number == self.target_line and number not in self.bookmarked_lines:
                target = block
            low = bisect_left(self.matches.lines, row)
            high = bisect_right(self.matches.lines, row, lo=low)
            index = max(low, bisect_left(self.matches.starts, left, lo=low, hi=high) - 1)
            for index in range(index, high):
                start, end = self.matches.starts[index], self.matches.ends[index]
                if start > right:
                    break
                if end <= left:
                    continue
                if index == self.current_match:
                    current = block, start, end
                    continue
                if spans and spans[-1][0] == block and spans[-1][2] == start:
                    spans[-1] = block, spans[-1][1], end
                else:
                    spans.append((block, start, end))
        # QTextCursor follows insertions before its block. Stable block identity
        # avoids repainting an unchanged long line on every buffer insertion.
        key = (tuple((b, start, end) for b, start, end in spans),
               target, current,
               tuple(bookmarks))
        if key == self._selection_key:
            return
        self._selection_key = key
        with editor.preserving_reading_position():
            if bookmarks != editor._bookmark_blocks:
                editor.set_bookmarked_blocks(bookmarks)
            selections = []
            if target is not None:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(target)
                selection.format.setBackground(QColor(THEME_COLORS["selection"]))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selections.append(selection)
            for block, start, end in spans:
                selection = self._match_selection(block, start, end, "ui_primary", "#ffffff")
                if block.blockNumber() in bookmarks:
                    selection.format.clearBackground()
                selections.append(selection)
            if current is not None:
                selections.append(self._match_selection(*current, "search_current", THEME_COLORS["background"]))
            editor.setExtraSelections(selections)
        editor._retained_frame = None
        editor.viewport().update()

    @staticmethod
    def _match_selection(block, start, end, background, foreground):
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(block)
        selection.cursor.setPosition(block.position() + start)
        selection.cursor.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
        selection.format.setBackground(QColor(THEME_COLORS[background]))
        selection.format.setForeground(QColor(foreground))
        return selection

    def set_bookmarks(self, lines):
        self.bookmarked_lines = set(lines)
        self.global_scroll.set_marker_rows(bookmarks=(n - self.first_line for n in lines
                                                     if self.first_line <= n <= self.total_line_count))
        self._refresh()

    def set_query(self, query):
        if query == self.query:
            return
        self.cancel_search()
        self.query = query

    def cancel_search(self):
        self._search_timer.stop()
        if self._search_work is not None:
            self._search_work.close()
        self._search_work = self._search_identity = None
        self._pending = SourceMatches()
        self._pending_markers = array("Q")
        self._pending_navigation = self._pending_sequence = None
        if self._search_request is not None and self.editor.navigation.pending is self._search_request:
            self.editor.navigation.cancel()
        self._search_request = None
        self.matches = SourceMatches()
        self.current_match = self.searched_query = None
        self._from_viewport = True
        self.global_scroll.set_marker_rows(matches=array("Q"))
        self._status("")
        self._schedule_decorations()

    def search(self):
        if self.query == self.searched_query:
            self.navigate(True)
            return
        self.cancel_search()
        self.searched_query = self.query
        if not self.query:
            return
        self._search_identity = self.editor.result_set_id
        self._search_work = iter_source_matches(self.lines, self.query)
        self._status("Searching...")
        if self._active:
            self._search_timer.start(0)

    def _advance_search(self):
        if (not self._active or self._search_work is None
                or self._search_identity is not self.editor.result_set_id):
            return
        deadline = perf_counter() + .004
        while perf_counter() < deadline:
            try:
                match = next(self._search_work)
            except StopIteration:
                self._search_work = None
                self.matches, self._pending = self._pending, SourceMatches()
                self.global_scroll.set_marker_rows(matches=self._pending_markers)
                self._pending_markers = array("Q")
                direction, self._pending_navigation = self._pending_navigation, None
                self._status(f"0 / {len(self.matches):,}" if self.matches else "No matches")
                if (direction is not None and self.isVisible()
                        and self._pending_sequence == self.editor.navigation._sequence):
                    self.navigate(direction)
                self._schedule_decorations()
                return
            if match is not None:
                row, start, end = match
                if not self._pending_markers or self._pending_markers[-1] != row:
                    self._pending_markers.append(row)
                self._pending.append(row, start, end)
        self._search_timer.start(1)

    def navigate(self, forward):
        if self.searched_query != self.query:
            self.search()
        if self.is_searching:
            self._pending_navigation = forward
            self._pending_sequence = self.editor.navigation._sequence
            return
        if not self.matches:
            return
        if self.current_match is None or self._from_viewport:
            top = self.editor.top_point()
            low = bisect_left(self.matches.lines, top.row)
            high = bisect_right(self.matches.lines, top.row, lo=low)
            index = bisect_left(self.matches.starts, top.column, lo=low, hi=high)
            if not forward:
                index -= 1
        else:
            index = self.current_match + (1 if forward else -1)
        self.current_match = index % len(self.matches)
        row, column = self.matches.lines[self.current_match], self.matches.starts[self.current_match]
        self._materialized = True
        self.editor.navigate_to(TextPoint(row, column), move_caret=True, reveal_column=True)
        self._search_request = self.editor.navigation.pending
        self._from_viewport = False
        self._status(f"{self.current_match + 1:,} / {len(self.matches):,}")
        self._schedule_decorations()

    def _status(self, text):
        self.search_status = text
        self.search_status_changed.emit(text)

    def _use_viewport_anchor(self, *_args):
        self._from_viewport = True
        self._pending_navigation = None

    def hideEvent(self, event):
        self.suspend()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.loader is not None and self._active:
            self.loader.set_paused(False)
            self.ensure_view()
        self._schedule_decorations()
