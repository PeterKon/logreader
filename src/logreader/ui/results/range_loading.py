"""Cooperative range loading and generation-guarded navigation."""

from dataclasses import dataclass
from time import perf_counter

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .result_coordinates import TextPoint
from .result_navigation import NavigationRequest, ProgressiveNavigation
from .result_paints import flush_view_paints


@dataclass(frozen=True, slots=True)
class ReadingMove:
    origin: TextPoint
    delta: int
    keep_x: bool


@dataclass(frozen=True, slots=True)
class RangeRequest(NavigationRequest):
    reading: bool = False
    movement: ReadingMove | None = None


class SparseNavigation(ProgressiveNavigation):
    def cancel(self):
        # Cancellation also invalidates surrounding work after navigation has
        # completed. A pending pointer alone cannot protect that queued work.
        self._sequence += 1
        self.loading_text = False
        super().cancel()

    def valid(self, request):
        return (request is not None and request is self.pending and request.result_set_id is self.result_set_id
                and request.sequence == self._sequence)

    def request(self, point, *, move_caret=False, anchor=None, reveal_column=False,
                result_set_id=None, reading=False, movement=None):
        if self.result_set_id is None or (result_set_id is not None and result_set_id is not self.result_set_id):
            return False
        if not self.editor.presentation.row_count:
            return False
        self.cancel()
        row = max(0, min(self.editor.presentation.row_count - 1, point.row))
        point = TextPoint(row, max(0, min(self.editor._units(row), point.column)))
        self.editor._cancel_wheel()
        request = RangeRequest(self.result_set_id, self._sequence, point, move_caret,
                               anchor, reveal_column, perf_counter(), reading, movement)
        self.pending = request
        self.loading_text = (not self.editor.ranges.contains(point.row)
                             or (movement is not None and self.editor._movement_gap is not None))
        # The loader can finish a cached screen inside this signal. Do not
        # publish a waiting state, or queue a turn, for immediate navigation.
        self.needs_loading.emit()
        if self.valid(request):
            self.changed.emit()
        return True

    def request_reading(self, origin, delta, *, move_caret=False, anchor=None):
        return self.request(origin, move_caret=move_caret, anchor=anchor, reading=True,
                            movement=ReadingMove(origin, delta, move_caret))


    def ready(self, request, point=None, *, top=None, immediate=False):
        if self.valid(request):
            self.resolved_point = point or request.point
            self.resolved_top = top or self.resolved_point
            self.ready_geometry = self.editor._end_geometry()
            self._ready = request, perf_counter()
            if immediate:
                self._finish(*self._ready)
            else:
                self.timer.start(0)

    def _finish(self, request, available_at):
        if not self.valid(request):
            return
        geometry = self.editor._end_geometry()
        if geometry != self.ready_geometry:
            self.timer.stop()
            self._ready = None
            self.needs_loading.emit()
            return
        point = self.resolved_point
        self.timer.stop()
        self._ready = None
        started = perf_counter()
        self._applying = True
        try:
            with self.editor.changing():
                # No event pumping occurs between validation and application.
                # Keep pending until application finishes so synchronous signals
                # cannot accidentally resurrect or complete a superseded job.
                self.editor.apply_navigation(request, point, top=self.resolved_top)
        finally:
            self._applying = False
        if not self.valid(request):
            return
        self.pending = None
        finished = perf_counter()
        measurement = dict(sequence=request.sequence, row=point.row, column=point.column,
                           reading=request.reading,
                           insertion_wait_ms=(available_at - request.started) * 1000,
                           dispatch_wait_ms=(started - available_at) * 1000,
                           layout_scroll_ms=(finished - started) * 1000,
                           request_to_layout_ms=(finished - request.started) * 1000)
        self.measurements.append(measurement)
        self.changed.emit()
        self.completed.emit(measurement)


class SparseLoader(QObject):
    progressed = Signal()
    completed = Signal()
    failed = Signal(str)

    def __init__(self, editor, *, background=True, interval_ms=1, max_rows=64,
                 max_units=65536, budget_ms=8, buffer_rows=16,
                 background_rows=192, background_budget_ms=6, background_max_rows=1024):
        super().__init__(editor)
        self.editor = editor
        self.result_set_id = editor.result_set_id
        self.background = background
        self.interval_ms = interval_ms
        self.max_rows, self.max_units, self.budget_ms = max_rows, max_units, budget_ms
        self.buffer_rows = buffer_rows
        self.background_rows = background_rows
        self.background_budget_ms = background_budget_ms
        self.background_max_rows = background_max_rows
        self.paused = self.cancelled = False
        self.error = None
        self.request = self.buffer = None
        self.row = self.height = 0
        self.ticks = []
        self.operations = []
        self.tick_count = self.operation_count = self.overruns = 0
        self._reported_done = False
        self.is_active = editor.isVisible
        # Wheel/native reading and priority work share bounded preparation
        # records. A previously visible screen needs no loader visit either.
        self._prepared = editor._prepared_layouts
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        editor.navigation.needs_loading.connect(self._requested)
        editor.navigation.changed.connect(self.start)

    @property
    def done(self):
        return self.editor.ranges.loaded_count == self.editor.ranges.total and not self.editor.ranges.gaps

    def valid(self, generation=None):
        return (not self.cancelled and self.editor.result_set_id is self.result_set_id
                and self.result_set_id is not None
                and (generation is None or generation == self.editor.navigation._sequence))

    def _requested(self):
        if not self.valid():
            return
        # An explicit destination resumes paused loading. A failed loader can
        # still navigate within retained text.
        self.paused = False
        request = self.editor.navigation.pending
        self.buffer = None
        if request is not None and request.movement is None:
            screen = self._cached_screen(request.point)
            if screen is not None and self.valid(request.sequence):
                top, after = screen
                if not self.done:
                    self.buffer = [request.sequence, top.row - 1, after, 0, 0, 0]
                self.editor.navigation.ready(request, top=top, immediate=True)
        self.start()

    def _layout_geometry(self):
        return self.editor.layout_geometry()

    def _cached_screen(self, point):
        # Read cached geometry only. In particular, neither _prepare_block nor
        # blockBoundingRect belongs in an input-handler readiness check: both
        # can shape a giant line. A miss keeps the normal cooperative budgets.
        editor = self.editor
        geometry = self._layout_geometry()
        if editor._visible_geometry != geometry:
            return None
        end_top = editor.end_top()
        top = min(point, end_top or point)
        height = 0
        deadline = perf_counter() + .001
        # Screen coverage is independent of the insertion budget. The deadline
        # still bounds this read-only scan for tall viewports.
        for row in range(top.row, editor.ranges.total):
            if perf_counter() >= deadline:
                return None
            block = editor._block(row)
            if not block.isValid():
                return None
            prepared = self._prepared.get(row)
            if prepared is not None and prepared != (geometry, block.userState()):
                return None
            layout = block.layout()
            # Qt can lay out adjacent rows during painting without registering
            # them here. Nonempty native layouts remain usable: Qt clears them
            # on content/geometry changes, and cache eviction clears them too.
            if not layout.lineCount():
                return None
            height += layout.boundingRect().height()
            if row == top.row:
                height -= layout.lineForTextPosition(top.column).y()
            if height >= editor.viewport().height():
                return top, row + 1
            if row + 1 == editor.ranges.total and end_top is not None:
                return top, row + 1
        return None

    def start(self):
        if (self.valid() and not self.paused and self.is_active()
                and not self.timer.isActive()
                and (self.editor.navigation.pending is not None
                     or (not self.error and (self.buffer is not None or (self.background and not self.done))))):
            self.timer.start(self.interval_ms)

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.timer.stop()
            self.buffer = None
            self.editor.navigation.cancel()
        else:
            self.start()
        self.progressed.emit()

    def cancel(self):
        self.cancelled = True
        self.timer.stop()
        self.buffer = None

    def retry(self):
        if self.valid():
            self.error = None
            self.set_paused(False)

    def _commit_end(self, row, limit):
        units = self.editor._units(row) + 1
        end = row + 1
        while end < min(limit, row + self.max_rows):
            size = self.editor._units(end) + 1
            if units + size > self.max_units:
                break
            units += size
            end += 1
        return end

    def _record_operation(self, kind, row, rows, units, started):
        ms = (perf_counter() - started) * 1000
        overrun = ms > self.budget_ms or units > self.max_units
        self.overruns += int(overrun)
        self.operation_count += 1
        self.operations.append(dict(kind=kind, row=row, rows=rows, units=units, ms=ms, overrun=overrun))
        # Diagnostics must not become another result-sized retained structure.
        if len(self.operations) > 2048:
            del self.operations[:1024]
        self._touched_rows.update(range(row, row + rows))
        self._rows = len(self._touched_rows)
        self._row_operations += rows
        self._units += units

    def _spent(self):
        return (self._units >= self.max_units or (perf_counter() - self._started) * 1000 >= self.budget_ms)

    def _insert(self, start, end, generation, *, units=None):
        if not self.valid(generation) or self.paused:
            return False
        if self.error:
            self.editor.navigation.cancel()
            return False
        # Computing a batch can call the model. Recheck after it, immediately
        # before touching the native document, and again after emitted signals.
        if units is None:
            units = sum(self.editor._units(row) + 1 for row in range(start, end))
        if not self.valid(generation) or self.paused:
            return False
        started = perf_counter()
        self.editor.insert_range(start, end)
        self._record_operation("insert", start, end - start, units, started)
        return self.valid(generation) and not self.paused

    def _ensure(self, row, generation, *, screen=False):
        editor = self.editor
        if row not in self._touched_rows and self._rows >= self.max_rows:
            return None
        geometry = self._layout_geometry()
        block = editor._block(row)
        if block.isValid():
            key = geometry, block.userState()
            if block.layout().lineCount() and self._prepared.get(row) == key:
                # A newer drag request may overlap work from the previous one.
                # Keep that preparation; revisiting retained layout consumes no
                # text budget. Bound traversal by the row and elapsed budgets.
                self._prepared.move_to_end(row)
                self._touched_rows.add(row)
                self._rows = len(self._touched_rows)
                self._row_operations += 1
                return block
        size = block.length() if block.isValid() else editor._units(row) + 1
        if self._rows and self._units + size > self.max_units:
            return None
        if not editor.ranges.contains(row):
            editor.navigation.loading_text = True
            if self._spent():
                return None
            span = editor.ranges.spans[editor.ranges.span_at(row)]
            limit = min(span.end, row + editor._screen_rows() + 4) if screen else row + 1
            # Batch short wrapped rows too. One native edit per source row
            # can consume the whole turn before a useful screen is prepared.
            # The text budget bounds overscan when fewer long rows suffice.
            end = self._commit_end(row, limit)
            if not self.valid(generation) or self.paused:
                return None
            # Respect the *remaining* turn budgets, except one indivisible row.
            while end > row + 1 and (end - row + self._rows > self.max_rows or
                    sum(editor._units(n) + 1 for n in range(row, end)) + self._units > self.max_units):
                end -= 1
            if not self._insert(row, end, generation):
                return None
        if (self._spent() or not self.valid(generation)
                or (self._rows and self._units + size > self.max_units)):
            return None
        started = perf_counter()
        with editor.changing():
            block = editor._prepare_block(row)
        editor.remember_layout(row, block, geometry)
        self._record_operation("layout", row, 1, block.length(), started)
        return block if self.valid(generation) else None

    def _resolve_movement(self, request):
        editor = self.editor
        while not self._spent():
            block = self._ensure(self.motion_row, request.sequence)
            if block is None:
                return False
            layout = block.layout()
            count = layout.lineCount()
            if self.motion_column is not None:
                line = layout.lineForTextPosition(min(self.motion_column, block.length() - 1))
                base = line.lineNumber()
                x = line.cursorToX(self.motion_column)
                self.motion_x = x[0] if isinstance(x, tuple) else x
            else:
                base = count if self.motion_delta < 0 else 0
            index = base + self.motion_delta
            if index < 0 and self.motion_row > 0:
                self.motion_row -= 1
                self.motion_delta, self.motion_column = index, None
            elif index >= count and self.motion_row + 1 < editor.ranges.total:
                self.motion_row += 1
                self.motion_delta, self.motion_column = index - count, None
            else:
                line = layout.lineAt(max(0, min(index, count - 1)))
                column = line.xToCursor(self.motion_x) if request.movement.keep_x else line.textStart()
                self.target = TextPoint(self.motion_row, column)
                self.row, self.height = self.target.row, 0
                return True
        return False

    def _priority(self, request):
        editor = self.editor
        if request is not self.request:
            self.request = request
            self.buffer = None
            self.target = None if request.movement else request.point
            self.row, self.height = request.point.row, 0
            if request.movement:
                self.motion_row = request.movement.origin.row
                self.motion_column = request.movement.origin.column
                self.motion_delta = request.movement.delta
                self.motion_x = 0
            self.geometry = None
        if self.target is None and not self._resolve_movement(request):
            return
        geometry = editor._end_geometry()
        if geometry != self.geometry:
            self.screen_start = min(self.target, editor.end_top() or self.target)
            self.row, self.height = self.screen_start.row, 0
            self.back_row = None
            self.geometry = geometry
        while self.row < editor.ranges.total and self.height < editor.viewport().height() and not self._spent():
            block = self._ensure(self.row, request.sequence, screen=True)
            if block is None:
                return
            height = editor.blockBoundingRect(block).height()
            if self.row == self.screen_start.row:
                height -= block.layout().lineForTextPosition(self.screen_start.column).y()
            self.height += height
            self.row += 1
        top = self.screen_start
        if self.row == editor.ranges.total:
            # EOF is a destination, not permission to scroll its last row to
            # the top. Prepare just the preceding screen, under the same turn
            # budgets, while keeping the requested caret independent of it.
            if self.back_row is None:
                block = self._ensure(self.screen_start.row, request.sequence)
                if block is None:
                    return
                self.height += block.layout().lineForTextPosition(self.screen_start.column).y()
                self.back_row = self.screen_start.row - 1
            while self.height < editor.viewport().height() and self.back_row >= 0:
                if self._spent():
                    return
                block = self._ensure(self.back_row, request.sequence)
                if block is None:
                    return
                self.height += editor.blockBoundingRect(block).height()
                self.back_row -= 1
            block = self._ensure(self.back_row + 1, request.sequence)
            if block is None:
                return
            layout = block.layout()
            excess = max(0, self.height - editor.viewport().height())
            # Native scrolling advances in visual lines. Round up so the last
            # line stays visible, with less than one line of spare space.
            index, stop = 0, layout.lineCount()
            while index < stop:
                middle = (index + stop) // 2
                if layout.lineAt(middle).y() < excess:
                    index = middle + 1
                else:
                    stop = middle
            top = (TextPoint(self.back_row + 1, layout.lineAt(index).textStart())
                   if index < layout.lineCount() else TextPoint(self.back_row + 2))
            editor.remember_end_top(top)
            top = min(self.screen_start, top)
        if (self.valid(request.sequence) and editor.navigation.valid(request)
                and (self.height >= editor.viewport().height() or self.row == editor.ranges.total)):
            # Navigate before bounded overscan, so a large adjacent line cannot
            # delay an already useful destination. Superseding input drops it.
            self.buffer = None if self.done else [request.sequence, top.row - 1, self.row, 0, 0, 0]
            editor.navigation.ready(request, self.target, top=top)

    def _surrounding(self, generation):
        editor = self.editor
        # Alternate before/after; total text and row limits bound this job,
        # independently of how long background completion ultimately takes.
        while self.buffer and not self._spent() and self._rows < self.max_rows and self.valid(generation):
            _, before, after, count, units, side = self.buffer
            if count >= self.buffer_rows * 2:
                self.buffer = None
                return
            row = before if side == 0 else after
            self.buffer[1 if side == 0 else 2] += -1 if side == 0 else 1
            self.buffer[3] += 1
            self.buffer[5] = 1 - side
            if not 0 <= row < editor.ranges.total or editor.ranges.contains(row):
                continue
            size = editor._units(row) + 1
            if units + size > self.max_units:
                self.buffer = None
                return
            if self._units + size > self.max_units:
                # Try this same row at the next yield, without losing it.
                self.buffer = [generation, before, after, count, units, side]
                return
            self.buffer[4] += size
            if not self._insert(row, row + 1, generation):
                return

    def _background_fill(self, generation):
        editor = self.editor
        limit_ms = min(self.budget_ms, self.background_budget_ms)
        previous_ms = 0
        while (self.valid(generation) and not self.paused and self.background and not self.error
               and editor.navigation.pending is None and editor.ranges.gaps
               and self._rows < self.background_max_rows):
            elapsed = (perf_counter() - self._started) * 1000
            # Reserve time for a comparable commit before starting another.
            # One indivisible row/edit can exceed the target and is measured.
            if self._rows and (elapsed + previous_ms * 1.15 >= limit_ms
                               or self._units >= self.max_units):
                break
            first, last = editor.ranges.gaps[0]
            end, units = first, 0
            for row in range(first, min(last, first + self.background_rows,
                                        first + self.background_max_rows - self._rows)):
                size = editor._units(row) + 1
                if self._units + units + size > self.max_units and (end > first or self._rows):
                    break
                end, units = row + 1, units + size
            if end == first:
                break
            started = perf_counter()
            if not self._insert(first, end, generation, units=units):
                break
            previous_ms = (perf_counter() - started) * 1000

    def _tick(self):
        editor = self.editor
        if not self.valid() or self.paused or not self.is_active():
            return
        generation = editor.navigation._sequence
        if self.buffer and self.buffer[0] != generation:
            self.buffer = None
        request = editor.navigation.pending
        if request is not None and editor.navigation._ready is not None:
            return
        self._started = perf_counter()
        self._rows = self._units = 0
        # Inserting and preparing the same row is one visited row. Charging it
        # twice forced a useful short-line screen to require two turns even
        # when it fit the time and text budgets, starving rapid held drags.
        self._touched_rows = set()
        self._row_operations = 0
        before = editor.ranges.loaded_count
        phase = "priority" if request else "buffer" if self.buffer else "background"
        try:
            if request:
                # Earlier wrapped layouts can change native line coordinates.
                # Preserve the reading point once per cooperative turn, only
                # if those coordinates actually changed, not once per row.
                with editor.preserving_reading_position():
                    self._priority(request)
            elif self.buffer and not self.error:
                self._surrounding(generation)
            elif self.background and not self.error and editor.ranges.gaps:
                self._background_fill(generation)
            if not self.valid(generation):
                return
            flush_view_paints(editor)
        except Exception as error:
            if self.valid(generation):
                self.error = str(error)
                self.buffer = None
                editor.navigation.cancel()
                self.timer.stop()
                self.failed.emit(self.error)
        finally:
            if self.valid():
                self.tick_count += 1
                self.ticks.append(dict(phase=phase, ms=(perf_counter() - self._started) * 1000,
                                       inserted=editor.ranges.loaded_count - before,
                                       rows=self._rows, row_operations=self._row_operations,
                                       units=self._units, generation=generation))
                if len(self.ticks) > 4096:
                    del self.ticks[:2048]
                self.progressed.emit()
        if self.valid() and self.done and not self._reported_done:
            self._reported_done = True
            self.completed.emit()
        self.start()
