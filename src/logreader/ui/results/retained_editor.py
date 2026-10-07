"""Native results text with retained loaded ranges and logical selections."""
from collections import OrderedDict
from contextlib import contextmanager
from math import ceil
from time import perf_counter
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap, QTextBlock, QTextBlockFormat, QTextCharFormat, QTextCursor
from .result_coordinates import TextPoint, WindowedResultsEditor
from .results_editor import ExcerptGapBlock, ResultsStructureArea, StructuralBlock, SummaryBlock, size_excerpt_gap
from .results_style import _results_editor_style_sheet
from .range_loading import SparseNavigation
from .loaded_ranges import RangeIndex, RetainedBoundary, Span, UnloadedGap
from ..widgets.search_widgets import SearchMarkerScrollBar
from ..widgets.line_number_editor import LineNumberEditor
from ..theme import THEME_COLORS

class LocalMarkerScrollBar(SearchMarkerScrollBar):
    bookmarks_changed = Signal()

    def set_bookmark_blocks(self, blocks, document):
        super().set_bookmark_blocks((block for block in blocks if block >= 0), document)
        self.bookmarks_changed.emit()


class StyledWindowEditor(WindowedResultsEditor):
    viewport_navigated = Signal()
    document_margin = 4


    def keyPressEvent(self, event):
        top = self.top_point()
        super().keyPressEvent(event)
        if self.top_point() != top:
            self.viewport_navigated.emit()


    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() != QEvent.Type.FontChange:
            return
        block = self.document().firstBlock()
        while block.isValid():
            if isinstance(block.userData(), ExcerptGapBlock):
                size_excerpt_gap(block, self.font())
            block = block.next()

    def __init__(self, model, parent=None, **options):
        super().__init__(model, parent, **options)
        self.setObjectName("resultsView")
        self.setStyleSheet(_results_editor_style_sheet())
        self.structure_area = ResultsStructureArea(self)
        self.updateRequest.connect(self._update_structure_area)
        # Bookmarks use the same marker API as the current results editor.
        self.setVerticalScrollBar(LocalMarkerScrollBar(Qt.Orientation.Vertical, self))
        self.verticalScrollBar().valueChanged.connect(self._native_scroll)
        self.update_gutter()


    def set_bookmarked_blocks(self, blocks):
        super().set_bookmarked_blocks({block: preferred for block, preferred in blocks.items() if block >= 0})

    def _write_row(self, cursor, number):
        entry = self.model.entry(number)
        if isinstance(entry, int):
            return super()._write_row(cursor, number)
        for text, role, bold in entry.fragments:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(THEME_COLORS[role]))
            fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            cursor.insertText(text, fmt)
        self._set_row_metadata(cursor.block(), number)


    def selected_text(self):
        start, end = sorted((self.anchor, self.caret))
        fragments = []
        for row in range(start.row, min(end.row + 1, self.model.row_count)):
            if not isinstance(self.model.entry(row), int):
                continue
            text = self.model.line(row).text
            left = start.column if row == start.row else 0
            right = end.column if row == end.row else self._units(row)
            fragments.append(text.encode("utf-16-le", errors="surrogatepass")[left * 2:right * 2]
                             .decode("utf-16-le", errors="surrogatepass"))
            if row < end.row:
                fragments.append("\n")
        return "".join(fragments)


class ProgressiveResultsEditor(StyledWindowEditor):
    rows_appended = Signal()

    def update_gutter(self, *_args):
        LineNumberEditor.update_gutter(self)
        if hasattr(self, "structure_area"):
            viewport = self.viewport().geometry()
            left = self.gutter.geometry().left()
            geometry = QRect(left, viewport.top(), viewport.right() - left + 1, viewport.height())
            if self.structure_area.geometry() != geometry:
                self.structure_area.setGeometry(geometry)
                self.structure_area.raise_()
                self.structure_area.update()

    def _update_structure_area(self, rect, dy):
        if dy:
            self.structure_area.update()
        else:
            self.structure_area.update(QRect(0, rect.y(), self.structure_area.width(), rect.height()))

    def __init__(self, presentation, parent=None, *, layout_mode="visible", cache_units=1048576,
                 restore_mode="needed", buffered_tail=True, quiet_append=True):
        self.presentation = presentation
        self.layout_mode = layout_mode
        self.cache_units = cache_units
        self.restore_mode = restore_mode
        self.buffered_tail = buffered_tail
        self.quiet_append = quiet_append
        self._screen_covered = False
        self._cached_rows = OrderedDict()
        self._cached_units = 0
        self._layout_key = None
        self._layout_rows = 0
        self.layout_visits = 0
        self.append_ms = []
        super().__init__(presentation, parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(self.document_margin)
        self.document().setMaximumBlockCount(0)
        self.document().setUndoRedoEnabled(False)
        self.created_documents = self.live_documents = self.live_layouts = 1
        self.peak_live_documents = self.peak_live_layouts = 1
        self.document().destroyed.connect(self._document_destroyed)
        self.document().documentLayout().destroyed.connect(self._layout_destroyed)
        self.navigation = SparseNavigation(self)
        self.horizontalScrollBar().valueChanged.connect(self._reading_input)
        self.horizontalScrollBar().sliderPressed.connect(self._reading_input)
        self.horizontalScrollBar().actionTriggered.connect(self._reading_input)

    @property
    def result_set_id(self):
        return self.navigation.result_set_id


    def navigate_to(self, point, **options):
        return self.navigation.request(point, **options)

    def go_to_location(self, location, *, column=0, result_set_id=None):
        if result_set_id is not None and result_set_id is not self.result_set_id:
            return False
        row = self.presentation.resolve(location)
        if row is None:
            return False
        return self.navigate_to(TextPoint(row, column), move_caret=True,
                                reveal_column=True, result_set_id=result_set_id)

    def go_to_search_result(self, location, column, *, result_set_id):
        if result_set_id is not self.result_set_id:
            return False
        return self.go_to_location(location, column=column, result_set_id=result_set_id)

    def _reading_input(self, *_args):
        if not self._guard and hasattr(self, "navigation"):
            self.navigation.cancel()

    def wheelEvent(self, event):  # noqa: N802
        if not event.angleDelta().isNull() or not event.pixelDelta().isNull():
            self._reading_input()
        super().wheelEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self._reading_input()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.navigation.cancel()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            row = 0 if key == Qt.Key.Key_Home else self.presentation.row_count - 1
            point = TextPoint(row, 0 if key == Qt.Key.Key_Home else self._units(row))
            anchor = self.anchor if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else None
            self.navigate_to(point, move_caret=True, anchor=anchor)
            event.accept()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                   Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self._reading_input()
        super().keyPressEvent(event)

    def _native_selection(self):
        self._reading_input()
        super()._native_selection()


    def _set_row_metadata(self, block, number):
        self._row_revision += 1
        block.setUserState(self._row_revision)
        entry = self.model.entry(number)
        gap = not isinstance(entry, int) and entry.kind == "gap"
        prepared_gap = isinstance(block.userData(), ExcerptGapBlock)
        block.setUserData(None)
        # These blocks are new, not recycled window rows. Resetting even an
        # unchanged block character format also dirties the preceding separator
        # in Qt, invalidating a completed giant line at the append boundary.
        cursor = QTextCursor(block)
        if not gap and cursor.blockCharFormat() != QTextCharFormat():
            cursor.setBlockCharFormat(QTextCharFormat())
        if block.layout().formats():
            block.layout().setFormats([])
        if isinstance(entry, int):
            return
        if entry.kind == "summary":
            block.setUserData(SummaryBlock(first=entry.first, last=entry.last))
        elif entry.kind == "gap":
            block.setUserData(ExcerptGapBlock())
            if not prepared_gap:
                size_excerpt_gap(block, self.font())
        else:
            block.setUserData(StructuralBlock())

    def _layout_window(self):
        self._layout_visible()

    def set_top(self, point, *, force=False, cancel_wheel=True):
        if not self._guard and hasattr(self, "navigation") and not self.navigation._applying:
            return self.navigate_to(point)
        if cancel_wheel and not self._applying_wheel:
            self._cancel_wheel()
        if not self.window_end:
            return
        row = max(0, min(self.window_end - 1, point.row))
        point = TextPoint(row, max(0, min(self._units(row), point.column)))
        horizontal = self.horizontalScrollBar().value()
        with self.changing():
            self._layout_window()
            self._project_selection()
            self._set_top_local(point)
            self.horizontalScrollBar().setValue(horizontal)
        self.window_changed.emit()

    def _ensure_window(self, row):
        self._prepare_block(row)

    def _prepare_block(self, row):
        block = self._block(row)
        if not block.isValid():
            return block
        if self.cache_units:
            block.layout().setCacheEnabled(True)
            if row not in self._cached_rows:
                units = block.length()
                self._cached_rows[row] = units
                self._cached_units += units
            self._cached_rows.move_to_end(row)
        if not block.layout().lineCount():
            self.layout_visits += 1
        self.document().documentLayout().ensureBlockLayout(block)
        return block


    def _update_ranges(self):
        self.verticalScrollBar().setRange(0, max(0, self.document().lineCount() - 1))
        self._max_horizontal = max(0, ceil(self.document().documentLayout().documentSize().width())
                                   - self.viewport().width())
        if self.lineWrapMode() == self.LineWrapMode.NoWrap:
            self.horizontalScrollBar().setMaximum(self._max_horizontal)


    def _flush_wheel(self):
        if not self._pending_wheel:
            return
        if perf_counter() - self._wheel_last_input >= self._wheel_idle_timeout:
            self._cancel_wheel()
            return
        steps = max(-12, min(12, self._pending_wheel[0]))
        self._pending_wheel[0] -= steps
        if not self._pending_wheel[0]:
            self._pending_wheel.popleft()
        self._applying_wheel = True
        try:
            self.scroll_visual_lines(steps)
            point = self.top_point()
            at_end = False
            if point.row == self.window_end - 1:
                block = self._prepare_block(point.row)
                last = block.layout().lineAt(block.layout().lineCount() - 1)
                at_end = point.column == last.textStart()
            if (steps < 0 and point == TextPoint(0)) or (steps > 0 and at_end):
                self._pending_wheel.clear()
        finally:
            self._applying_wheel = False
        if self._pending_wheel:
            self._wheel_timer.start(16)

    def _project_selection(self):
        if self.restore_mode == "needed":
            cursor = self.textCursor()
            if (cursor.anchor(), cursor.position()) == (self._qt_position(self.anchor), self._qt_position(self.caret)):
                return
        super()._project_selection()


    def rebase_if_needed(self):
        pass

    def _native_scroll(self, *_args):
        if not self._guard:
            self._reading_input()
            if self.layout_mode == "visible":
                with self.changing():
                    self._layout_visible()
            self.window_changed.emit()


    def selectAll(self):  # noqa: N802
        self.select(TextPoint(0), TextPoint(self.presentation.row_count))

    def selected_text(self):
        start, end = sorted((self.anchor, self.caret))
        if start == TextPoint(0) and end == TextPoint(self.presentation.row_count):
            return "".join(line.text + "\n" for line in self.presentation.logical.iter_lines())
        return super().selected_text()


class SparseResultsEditor(ProgressiveResultsEditor):
    painted = Signal(object)
    insertion_history_limit = 256

    def __init__(self, presentation, parent=None):
        self.ranges = RangeIndex(presentation.row_count)
        self.insertions = []
        self.insertion_count = self.inserted_rows = 0
        self.paint_observer = False
        self._retained_frame = None
        self._retained_frame_key = None
        self._frame_offset = QPointF()
        self.frame_captures = self.frame_reuses = 0
        self._movement_gap = None
        self._drag_loading = None
        self._visible_rows = set()
        self._visible_geometry = None
        self._prepared_layouts = OrderedDict()
        self._gap_pixels = 2048
        self._covered_edit = False
        self._context_insertion_id = None
        self._end_screen = None
        self._gap_format = None
        super().__init__(presentation, parent)
        # QObject destruction can leave Python wrapper cycles alive. Drop the
        # large result graph when Qt retires the editor, without forcing GC.
        self.destroyed.connect(lambda: self._release_result_data())
        self.blockCountChanged.disconnect(self.update_gutter)
        self.blockCountChanged.connect(self._block_count_changed)
        self.model = presentation
        # These inherited bounds delimit the logical model, not availability.
        self.window_end = presentation.row_count
        with self.changing():
            cursor = QTextCursor(self.document())
            if presentation.row_count:
                self._write_gap(cursor, Span(0, presentation.row_count, False))
                cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            # One hidden EOF guard avoids Qt's eager append-at-EOF layout path.
            cursor.block().setVisible(False)
            cursor.block().setLineCount(0)

    def _release_result_data(self):
        # Only Python attributes: the native editor is being destroyed.
        self.presentation = self.model = None
        self._retained_frame = None

    def set_results(self, presentation):
        self.navigation.reset()
        self._cancel_wheel()
        self._drag_timer.stop()
        self._dragging = self._extending = False
        self._drag_loading = None
        with self.changing():
            self.presentation = self.model = presentation
            self.ranges = RangeIndex(presentation.row_count)
            self.window_start, self.window_end = 0, presentation.row_count
            self.anchor = self.caret = TextPoint(0)
            self._retained_frame = None
            self._cached_rows.clear()
            self._prepared_layouts.clear()
            self._visible_rows.clear()
            self._visible_geometry = None
            self._cached_units = self.layout_visits = self._max_horizontal = 0
            self._screen_covered = False
            self._end_screen = None
            self.insertions.clear()
            self.insertion_count = self.inserted_rows = 0
            self.document().clear()
            cursor = QTextCursor(self.document())
            if presentation.row_count:
                self._write_gap(cursor, Span(0, presentation.row_count, False))
                cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            cursor.block().setVisible(False)
            cursor.block().setLineCount(0)
            self.set_bookmarked_blocks({})
            self.update_gutter()
        self.window_changed.emit()

    def position_for(self, point):
        if point.row == self.presentation.row_count and point.column == 0:
            return self.document().characterCount() - 1
        number = self.ranges.block_for(point.row)
        if number is None:
            return None
        block = self.document().findBlockByNumber(number)
        return block.position() + max(0, min(point.column, block.length() - 1))

    def location_at(self, position):
        block = self.document().findBlock(position)
        row = self.ranges.logical_at(block.blockNumber())
        if isinstance(row, (UnloadedGap, RetainedBoundary)):
            return row
        return TextPoint(self.presentation.row_count if row is None else row,
                         0 if row is None else position - block.position())

    def _block(self, row):
        if not 0 <= row < self.ranges.total:
            return QTextBlock()
        number = self.ranges.block_for(row)
        return QTextBlock() if number is None else self.document().findBlockByNumber(number)

    def _qt_position(self, point):
        position = self.position_for(point)
        if position is not None:
            return position
        return self.document().findBlockByNumber(self.ranges.block_for(point.row, project_gap=True)).position()

    def _native_point(self, position):
        point = self.location_at(position)
        if isinstance(point, UnloadedGap):
            return TextPoint(point.start)
        return TextPoint(point.row) if isinstance(point, RetainedBoundary) else point

    def source_number(self, block):
        row = self.ranges.logical_at(block)
        return self.presentation.line(row).number or None if isinstance(row, int) else None

    def top_point(self):
        if not self.ranges.loaded_count:
            return TextPoint(0)
        visual = self.verticalScrollBar().value()
        block = self.document().findBlockByLineNumber(visual)
        if not block.isValid():
            block = self.firstVisibleBlock()
        row = self.ranges.logical_at(block.blockNumber())
        if not isinstance(row, int):
            return TextPoint(row.start if isinstance(row, UnloadedGap) else
                             row.row if isinstance(row, RetainedBoundary) else self.presentation.row_count)
        self.document().documentLayout().ensureBlockLayout(block)
        index = max(0, min(block.layout().lineCount() - 1, visual - block.firstLineNumber()))
        return TextPoint(row, block.layout().lineAt(index).textStart())

    def _write_gap(self, cursor, span):
        cursor.setBlockFormat(QTextBlockFormat())
        # A fixed hidden pad and one empty block separate islands. Its height prevents native paint
        # from exposing a later island across missing text. No placeholder is
        # selectable log text, and the size never scales with missing rows.
        cursor.setBlockCharFormat(QTextCharFormat())
        cursor.insertText(" " * 64, QTextCharFormat())
        cursor.block().setUserData(StructuralBlock())
        cursor.block().setVisible(False)
        cursor.block().setLineCount(0)
        font = QFont(self.font())
        font.setPixelSize(self._gap_pixels)
        fmt = QTextCharFormat()
        fmt.setFont(font)
        # Set the format when creating the blank block. Changing it later
        # dirties Qt's preceding paragraph separator, even if that preceding
        # line is a retained giant row. The pad is reused when this gap fills.
        cursor.insertBlock(QTextBlockFormat(), fmt)
        cursor.block().setUserData(StructuralBlock())
        cursor.block().setVisible(True)
        cursor.block().setLineCount(1)

    def _write_row(self, cursor, number):
        entry = self.presentation.entry(number)
        if not isinstance(entry, int) and entry.kind != "gap":
            return super()._write_row(cursor, number)
        # _fill_gap creates each source block with empty formats and no user
        # data. Accessing/resetting its layout here only allocates wrappers for
        # untouched offscreen text. The reused first gap pad is empty as well.
        block = cursor.block()
        block.setUserData(None)
        self._row_revision += 1
        block.setUserState(self._row_revision)
        if isinstance(entry, int):
            line = self.presentation.logical.line(entry)
            role = "matched_text" if line.is_match else "body"
            position = 0
            for span in line.match_spans:
                if span.start > position:
                    cursor.insertText(line.text[position:span.start], self._formats[role])
                cursor.insertText(line.text[span.start:span.end], self._formats["match"])
                position = span.end
            if position < len(line.text):
                cursor.insertText(line.text[position:], self._formats[role])
        else:
            font = self.font()
            if self._gap_format is None or self._gap_format[0] != font:
                target = max(1, QFontMetricsF(font).height() - 4)
                gap_font = QFont(font)
                size = max(1, round(target))
                gap_font.setPixelSize(size)
                while size > 1 and QFontMetricsF(gap_font).height() > target:
                    size -= 1
                    gap_font.setPixelSize(size)
                fmt = QTextCharFormat()
                fmt.setFont(gap_font)
                self._gap_format = QFont(font), fmt
            cursor.setBlockCharFormat(self._gap_format[1])
            block.setUserData(ExcerptGapBlock())

    def insert_range(self, start, end):
        if not 0 <= start <= end <= self.ranges.total:
            raise ValueError("Range is outside the prepared result")
        inserted = 0
        identity = self.result_set_id
        # Snapshot only intervals. Repeated/overlapping requests never rewrite
        # retained text, and distant edits use separate native transactions.
        for left, right in self.ranges.gaps:
            if self.result_set_id is not identity:
                break
            a, b = max(start, left), min(end, right)
            if a < b:
                self._fill_gap(a, b)
                inserted += b - a
        return inserted

    def _block_count_changed(self, *_args):
        if not self._covered_edit:
            self.update_gutter()

    def set_context_target(self, block):
        if block != self._context_target:
            self._retained_frame = None
        super().set_context_target(block)

    def _context_contents_changed(self, position, removed, added):
        if (self._context_insertion_id is not None
                and self._context_insertion_id is self.result_set_id
                and self._context_target is not None and self._context_target.isValid()):
            return
        super()._context_contents_changed(position, removed, added)

    @contextmanager
    def _retaining_context_target(self):
        previous = self._context_insertion_id
        self._context_insertion_id = self.result_set_id
        try:
            yield
        finally:
            self._context_insertion_id = previous

    @contextmanager
    def _retaining_gutter(self, covered):
        previous = self._covered_edit
        self._covered_edit = covered
        try:
            yield
        finally:
            self._covered_edit = previous

    def _fill_gap(self, start, end):
        started = perf_counter()
        top = self.top_point()
        horizontal = self.horizontalScrollBar().value()
        had_text = self.ranges.contains(top.row)
        covered = had_text and self.viewport_evidence()["useful"]
        if covered and start < top.row:
            self._retain_frame()
        number = self.ranges.block_for(start, project_gap=True)
        block = self.document().findBlockByNumber(number)
        # Block-count notifications need no repaint when the visible source
        # stays unchanged. Explicit navigation and resize updates remain live.
        with self._retaining_context_target(), self._retaining_gutter(covered), self.changing():
            blocker = QSignalBlocker(self.document().documentLayout()) if covered else None
            cursor = QTextCursor(block)
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            parts = self.ranges.fill(start, end)
            first = True
            for span in parts:
                if span.guard_before:
                    if not first:
                        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                    first = False
                    # Qt's changeEnd uses charsRemoved + charsAdded, so a
                    # replacement invalidates beyond its new text by the old
                    # marker's length. An empty guard is too short. This fixed
                    # hidden pad exceeds every marker supported by Qt's int
                    # document positions, without scaling with missing rows.
                    cursor.insertText(" " * 128, QTextCharFormat())
                    cursor.block().setUserData(StructuralBlock())
                    cursor.block().setVisible(False)
                    cursor.block().setLineCount(0)
                for row in range(span.start, span.end) if span.loaded else (None,):
                    if not first:
                        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                    first = False
                    cursor.block().setVisible(True)
                    cursor.block().setLineCount(1)
                    if row is None:
                        self._write_gap(cursor, span)
                    else:
                        self._write_row(cursor, row)
            cursor.endEditBlock()
            if blocker is not None:
                blocker.unblock()
            self._update_ranges()
            self._project_selection()
            # Looking up the old scrollbar value after a preceding insertion
            # would lay out an unrelated newly inserted row. Restore through
            # the retained logical block directly, without that lookup.
            if had_text:
                self._restore_top_if_changed(top)
            if self.horizontalScrollBar().value() != horizontal:
                self.horizontalScrollBar().setValue(horizontal)
            if not covered:
                self._layout_visible()
                self.update_gutter()
        self.insertion_count += 1
        self.inserted_rows += end - start
        self.insertions.append(dict(sequence=self.insertion_count, start=start, end=end,
                                    ms=(perf_counter() - started) * 1000, loaded=self.ranges.loaded_count))
        # Keep recent scalar diagnostics, not a growing series of complete
        # range snapshots. Totals remain exact after old records are evicted.
        if len(self.insertions) > self.insertion_history_limit:
            del self.insertions[:len(self.insertions) - self.insertion_history_limit]
        self.window_changed.emit()
        self.rows_appended.emit()

    def layout_geometry(self):
        return (self.viewport().width(), self.font().toString(), self.lineWrapMode(),
                self.devicePixelRatioF(), self.tabStopDistance())

    def remember_layout(self, row, block, geometry):
        self._prepared_layouts[row] = geometry, block.userState()
        self._prepared_layouts.move_to_end(row)
        if len(self._prepared_layouts) > 512:
            self._prepared_layouts.popitem(last=False)

    def _layout_visible(self):
        block = self.firstVisibleBlock()
        visible = set()
        geometry = self.layout_geometry()
        self._screen_covered = False
        while block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            row = self.ranges.logical_at(block.blockNumber())
            if not isinstance(row, int):
                break
            self._prepare_block(row)
            self.remember_layout(row, block, geometry)
            visible.add(row)
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if rect.bottom() >= self.viewport().height():
                self._screen_covered = True
                break
            block = block.next()
        self._visible_rows = visible
        self._visible_geometry = geometry
        self._trim_layout_cache()
        self._update_ranges()

    def _trim_layout_cache(self, keep_row=None):
        for row in list(self._cached_rows):
            if self._cached_units <= self.cache_units and len(self._cached_rows) <= 256:
                break
            if row in self._visible_rows or row == keep_row:
                continue
            layout = self._block(row).layout()
            layout.setCacheEnabled(False)
            layout.beginLayout()
            layout.endLayout()
            self._cached_units -= self._cached_rows.pop(row)

    def _end_geometry(self):
        return (self.viewport().size(), self.font().toString(), self.lineWrapMode(),
                self.devicePixelRatioF(), self.tabStopDistance())

    def end_top(self):
        if self._end_screen is not None and self._end_screen[0] == self._end_geometry():
            return self._end_screen[1]
        return None

    def remember_end_top(self, point):
        visual_line = (self._block(point.row).layout().lineForTextPosition(point.column).lineNumber()
                       if point.column else 0)
        self._end_screen = self._end_geometry(), point, visual_line

    def end_scroll_maximum(self):
        point = self.end_top()
        return point.row + self._end_screen[2] if point is not None else None

    def at_bottom(self):
        point = self.end_top()
        return point is not None and point == self.top_point()

    def set_top(self, point, **options):
        if not self._guard and hasattr(self, "navigation") and not self.navigation._applying:
            return self.navigate_to(point)
        if self.ranges.contains(point.row):
            point = min(point, self.end_top() or point)
            return super().set_top(point, **options)

    @contextmanager
    def preserving_reading_position(self):
        point = self.top_point()
        identity = self.result_set_id
        horizontal = self.horizontalScrollBar().value()
        with self.changing():
            try:
                yield
            finally:
                if identity is self.result_set_id and self.ranges.contains(point.row):
                    # Superseded requests may never reach a navigation paint.
                    # Bound their layout cache without preparing the old view.
                    if self._cached_units > self.cache_units or len(self._cached_rows) > 256:
                        pending = self.navigation.pending
                        destination = self.navigation.resolved_top if self.navigation._ready else (
                            pending.point if pending else None)
                        # A single oversized destination must survive until
                        # navigation, just as an oversized visible row does.
                        self._trim_layout_cache(destination.row if destination else None)
                        self._update_ranges()
                    self._restore_top_if_changed(point)
                    if self.horizontalScrollBar().value() != horizontal:
                        self.horizontalScrollBar().setValue(horizontal)

    def _restore_top_if_changed(self, point):
        block = self._block(point.row)
        if not block.layout().lineCount():
            block = self._prepare_block(point.row)
        line = block.layout().lineForTextPosition(min(point.column, block.length() - 1))
        desired = block.firstLineNumber() + line.lineNumber()
        if self.verticalScrollBar().value() != desired or self.firstVisibleBlock() != block:
            self._set_top_local(point, refresh=False)

    def _set_top_local(self, point, *, refresh=True):
        block = self._prepare_block(point.row)
        line = block.layout().lineForTextPosition(min(point.column, block.length() - 1))
        self._update_ranges()
        # Native setTopBlock otherwise computes a pixel scroll by laying out
        # the blocks between its old block number and the relocated block.
        # During this synchronous coordinate correction there is no scrolling
        # to animate. Keep native positions, but skip that geometry traversal.
        desired = block.firstLineNumber() + line.lineNumber()
        bar = self.verticalScrollBar()
        if bar.value() != desired or self.firstVisibleBlock() != block:
            viewport = self.viewport()
            enabled = viewport.updatesEnabled()
            viewport.setUpdatesEnabled(False)
            try:
                if bar.value() == desired:
                    # Replacing two marker blocks with one source row can
                    # leave the same visual value but a different top block.
                    # Force Qt to resolve that value again, without traversing
                    # intervening geometry or dispatching a reading action.
                    bar.setValue(desired - 1 if desired else min(1, bar.maximum()))
                bar.setValue(desired)
            finally:
                viewport.setUpdatesEnabled(enabled)
        if refresh:
            self._layout_visible()
            # Suppressing Qt's pixel-scroll path also suppresses its usual
            # gutter damage notification. Request normal paints explicitly;
            # neither selection nor screenshot capture should be necessary.
            self.gutter.update()
            self.structure_area.update()

    def _advance(self, point, delta, *, keep_x=False):
        self._movement_gap = None
        if not self.ranges.contains(point.row):
            self._movement_gap = point.row
            return point
        start, end = next((a, b) for a, b in self.ranges.loaded_ranges if a <= point.row < b)
        row = point.row
        block = self._prepare_block(row)
        line = block.layout().lineForTextPosition(min(point.column, block.length() - 1))
        x = line.cursorToX(point.column)
        x = x[0] if isinstance(x, tuple) else x
        index = line.lineNumber() + delta
        while index < 0 and row > start:
            row -= 1
            block = self._prepare_block(row)
            index += block.layout().lineCount()
        while index >= block.layout().lineCount() and row + 1 < end:
            index -= block.layout().lineCount()
            row += 1
            block = self._prepare_block(row)
        if index < 0 and start > 0:
            self._movement_gap = start - 1
        elif index >= block.layout().lineCount() and end < self.ranges.total:
            self._movement_gap = end
        line = block.layout().lineAt(max(0, min(index, block.layout().lineCount() - 1)))
        return TextPoint(row, line.xToCursor(x) if keep_x else line.textStart())

    def _available_screen(self, point):
        height = 0
        for row in range(point.row, self.ranges.total):
            if not self.ranges.contains(row):
                return False
            block = self._prepare_block(row)
            height += self.blockBoundingRect(block).height()
            if row == point.row:
                height -= block.layout().lineForTextPosition(point.column).y()
            if height >= self.viewport().height():
                return True
        return point == TextPoint(0) or self.end_top() is not None

    def apply_navigation(self, request, point, *, top=None):
        self._retained_frame = None
        if request.move_caret:
            self.anchor = request.anchor if request.anchor is not None else point
            self.caret = point
        if request.reading and request.move_caret:
            self._show_caret(point)
        else:
            self.set_top(top or point)
        if self._dragging and request is self._drag_loading and self.navigation.valid(request):
            self._drag_loading = None
            self._extend_drag_selection()
        if (self.navigation.valid(request) and request.reveal_column
                and self.lineWrapMode() == self.LineWrapMode.NoWrap):
            line = self._block(point.row).layout().lineForTextPosition(point.column)
            x = line.cursorToX(point.column)
            x = x[0] if isinstance(x, tuple) else x
            self.horizontalScrollBar().setValue(max(0, round(x - self.viewport().width() / 3)))

    def _show_caret(self, target):
        top = self.top_point()
        self._project_selection()
        self._set_top_local(top)
        y = self.point_y(target)
        if y < 0:
            self.set_top(target)
        elif y + self.fontMetrics().height() > self.viewport().height():
            page = max(1, self.viewport().height() // self.fontMetrics().height())
            self.set_top(self._advance(target, -(page - 1)))
        self.window_changed.emit()

    def _read_move(self, origin, delta, *, move_caret=False, anchor=None):
        with self.changing():
            target = self._advance(origin, delta, keep_x=move_caret)
            missing = self._movement_gap
            if missing is None and self._available_screen(target):
                if move_caret:
                    self.anchor = anchor if anchor is not None else target
                    self.caret = target
                    self._show_caret(target)
                else:
                    self.set_top(target)
                self.viewport_navigated.emit()
                return
        # Waiting retains the old screen. The movement is resolved by visual
        # lines after adjacent text arrives, including wrapped boundary rows.
        self.navigation.request_reading(origin, delta, move_caret=move_caret, anchor=anchor)

    def scroll_visual_lines(self, delta):
        self._reading_input()
        if delta and self.ranges.loaded_count:
            self._read_move(self.top_point(), delta)

    def select(self, anchor, caret):
        self._reading_input()
        with self.preserving_reading_position():
            self.anchor, self.caret = anchor, caret
            self._project_selection()
        self.viewport().update()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if not self.ranges.total:
            event.accept()
            return
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End) and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            # Qt's read-only Home/End scroll to the native document ends,
            # which can be unloaded markers. Keep their whole-result scope.
            row = 0 if key == Qt.Key.Key_Home else self.ranges.total - 1
            self.navigate_to(TextPoint(row, 0 if key == Qt.Key.Key_Home else self._units(row)))
            event.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self._cancel_wheel()
            self._reading_input()
            if self.ranges.loaded_count:
                step = -1 if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 1
                if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                    step *= max(1, self._screen_rows() - 1)
                anchor = self.anchor if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else None
                origin = self.caret
                if not self.ranges.contains(origin.row):
                    origin = self.top_point()
                self._read_move(origin, step, move_caret=True, anchor=anchor)
            event.accept()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.ranges.loaded_count:
            self._reading_input()
            cursor = self.textCursor()
            forward = key == Qt.Key.Key_Right
            control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self.anchor != self.caret and not shift and not control:
                point = max(self.anchor, self.caret) if forward else min(self.anchor, self.caret)
                if point.row == self.ranges.total:
                    point = TextPoint(point.row - 1, self._units(point.row - 1))
                self.navigation.request(point, reading=True, move_caret=True)
                event.accept()
                return
            operation = (QTextCursor.MoveOperation.NextWord if forward else QTextCursor.MoveOperation.PreviousWord) if control else (
                QTextCursor.MoveOperation.NextCharacter if forward else QTextCursor.MoveOperation.PreviousCharacter)
            cursor.movePosition(operation)
            point = self.location_at(cursor.position())
            if isinstance(point, (UnloadedGap, RetainedBoundary)) or (
                    isinstance(point, TextPoint) and abs(point.row - self.caret.row) > 1):
                row = self.caret.row + (1 if forward else -1)
                if 0 <= row < self.ranges.total:
                    self.navigation.request(TextPoint(row, 0 if forward else self._units(row)),
                        reading=True, move_caret=True, anchor=self.anchor if shift else None)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self._drag_loading = None
        point = self.location_at(self.cursorForPosition(event.position().toPoint()).position())
        if isinstance(point, UnloadedGap):
            self._reading_input()
            self.navigation.request(TextPoint(point.start), reading=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def _extend_drag_selection(self):
        forward = self._drag_point.y() >= self.viewport().height()
        point = QPoint(self._drag_point.x(), self.viewport().height() - 1 if forward else 0)
        location = self.location_at(self.cursorForPosition(point).position())
        if isinstance(location, TextPoint) and self.ranges.contains(location.row):
            with self.preserving_reading_position():
                self.caret = location
                self._project_selection()

    def _drag_tick(self):
        if not self._dragging:
            return
        delta = 3 if self._drag_point.y() >= self.viewport().height() else -3
        pending = self.navigation.pending
        if pending is not None and pending is self._drag_loading:
            if pending.movement is not None and pending.movement.delta == delta:
                return
        self.scroll_visual_lines(delta)
        self._drag_loading = self.navigation.pending
        if self._drag_loading is None:
            self._extend_drag_selection()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_loading is not None and 0 <= event.position().y() < self.viewport().height():
            if self.navigation.pending is self._drag_loading:
                self.navigation.cancel()
            self._drag_loading = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_loading is not None and self.navigation.pending is self._drag_loading:
            self.navigation.cancel()
        self._drag_loading = None
        had_selection = self.textCursor().hasSelection()
        super().mouseReleaseEvent(event)
        cursor = self.textCursor()
        if event.button() == Qt.MouseButton.LeftButton and had_selection and not cursor.hasSelection():
            # Qt defers a click inside a selection until release. Its signals
            # run while _dragging still protects the logical anchor; synchronize
            # this collapse after release without replacing unloaded endpoints.
            self.anchor = self.caret = self._native_point(cursor.position())

    def _refresh_end_screen(self, was_bottom):
        if (self._end_screen is not None and self.end_top() is None
                and self.navigation.pending is None):
            if was_bottom:
                self.navigate_to(TextPoint(self.ranges.total - 1))
            elif self.ranges.total - 1 in self._visible_rows and self.top_point() != TextPoint(0):
                self.navigate_to(self.top_point())

    def set_wrapping(self, enabled):
        was_bottom = self.at_bottom() and self.top_point() != TextPoint(0)
        super().set_wrapping(enabled)
        self._refresh_end_screen(was_bottom)

    def resizeEvent(self, event):  # noqa: N802
        was_bottom = (self._end_screen is not None and self._end_screen[1] != TextPoint(0)
                      and self._end_screen[1] == self.top_point())
        super().resizeEvent(event)
        self._refresh_end_screen(was_bottom)
        if self.viewport().height() > self._gap_pixels:
            self._gap_pixels = self.viewport().height() * 2
            with self.changing():
                for start, _ in self.ranges.gaps:
                    block = self.document().findBlockByNumber(self.ranges.block_for(start, project_gap=True) + 1)
                    fmt = QTextCharFormat(block.charFormat())
                    font = QFont(self.font())
                    font.setPixelSize(self._gap_pixels)
                    fmt.setFont(font)
                    QTextCursor(block).setBlockCharFormat(fmt)

    def viewport_evidence(self):
        block = self.firstVisibleBlock()
        rows = []
        bottom = 0
        missing = False
        while block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            row = self.ranges.logical_at(block.blockNumber())
            if not isinstance(row, int):
                missing = True
                break
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            rows.append(row)
            bottom = rect.bottom()
            if bottom >= self.viewport().height():
                break
            block = block.next()
        at_end = bool(rows) and rows[-1] == self.presentation.row_count - 1
        return dict(top=self.top_point().row, rows=rows, bottom=bottom,
                    useful=bool(rows) and not missing and (bottom >= self.viewport().height() or at_end))

    def paintEvent(self, event):  # noqa: N802
        if self._retained_frame is not None and self._frame_key() == self._retained_frame_key:
            painter = QPainter(self.viewport())
            painter.drawPixmap(-self._frame_offset, self._retained_frame)
            painter.end()
            self.frame_reuses += 1
        else:
            self._retained_frame = None
            super().paintEvent(event)
        if self.paint_observer:
            self.painted.emit(dict(at=perf_counter(), **self.viewport_evidence()))

    def _frame_key(self):
        return (self.top_point(), self.anchor, self.caret, self.horizontalScrollBar().value(),
                self.viewport().size(), self.font().toString(), self.lineWrapMode(),
                self.devicePixelRatioF(), self.palette().cacheKey(), self.hasFocus(), self._pixel_phase())

    def _pixel_phase(self):
        origin = self.viewport().mapTo(self.window(), QPoint())
        scale = self.devicePixelRatioF()
        return (origin.x() * scale % 1, origin.y() * scale % 1)

    def _retain_frame(self):
        if not self.isVisible():
            self._retained_frame = None
            return
        key = self._frame_key()
        if self._retained_frame is not None and key == self._retained_frame_key:
            return
        # Coordinate-only restoration dirties the entire native viewport.
        # Repainting a giant unwrapped row on every offscreen commit is costly
        # even with shaped glyphs cached. Keep one bounded image of this exact
        # unchanged viewport, invalidated by reading/selection/geometry/style.
        self._retained_frame = None
        scale = self.devicePixelRatioF()
        x, y = self._pixel_phase()
        self._frame_offset = QPointF(x / scale, y / scale)
        frame = QPixmap(ceil(self.viewport().width() * scale + x), ceil(self.viewport().height() * scale + y))
        frame.setDevicePixelRatio(scale)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        # Render on the same physical pixel grid as the native viewport in the
        # window. A local grab at fractional scale changes glyph rasterization.
        painter.translate(self._frame_offset)
        self.viewport().render(painter, QPoint())
        painter.end()
        self._retained_frame = frame
        self._retained_frame_key = key
        self.frame_captures += 1

    def _reading_input(self, *_args):
        if not self._guard:
            self._retained_frame = None
        super()._reading_input(*_args)
