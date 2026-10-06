"""Logical selection and native text interaction."""

from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass
from time import perf_counter
from math import ceil
from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QMenu, QPlainTextEdit
from logreader.ui.widgets.line_number_editor import LineNumberEditor
from logreader.ui.results.results_model import ResultsModel
from logreader.ui.source_search import utf16_length
from logreader.ui.theme import THEME_COLORS


@dataclass(frozen=True, order=True, slots=True)
class TextPoint:
    row: int
    column: int = 0  # UTF-16 units, as used by Qt. (row_count, 0) means EOF.


class WindowedResultsEditor(LineNumberEditor):
    window_changed = Signal()
    _wheel_idle_timeout = 0.120
    _wrapped_retention_factor = 8

    def __init__(self, model: ResultsModel, parent=None, *, max_rows=256, max_units=131072):
        if not model.ready:
            raise ValueError("Prepare the results model before displaying it")
        if max_rows < 16 or max_units < 1024:
            raise ValueError("The window must provide a useful scrolling buffer")
        self.model = model
        self.max_rows, self.max_units = max_rows, max_units
        self.window_start = self.window_end = 0
        self.anchor = self.caret = TextPoint(0)
        self._guard = True
        self._dragging = self._extending = False
        self._drag_point = QPoint()
        self._wheel_remainder = 0.0
        self._pending_wheel = deque()
        self._wheel_last_input = 0.0
        self._applying_wheel = False
        self._max_horizontal = 0
        self._row_revision = 0
        self.replacements = 0
        self.reused_windows = 0
        self.replacement_ms = []
        self.live_documents = self.live_layouts = 0
        self.created_documents = self.destroyed_documents = 0
        self.peak_live_documents = self.peak_live_layouts = 0
        self.peak_blocks = self.peak_units = 0
        self.oversize_windows = 0
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCenterOnScroll(True)
        self.setStyleSheet(
            f"QPlainTextEdit {{background:{THEME_COLORS['background']};"
            f"color:{THEME_COLORS['body']}; border:0; padding:0;"
            f"selection-background-color:{THEME_COLORS['selection']};}}"
        )
        self._formats = {}
        for role, bold in (("body", False), ("matched_text", False), ("match", True)):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(THEME_COLORS[role]))
            fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            self._formats[role] = fmt
        self._rebase_timer = QTimer(self)
        self._rebase_timer.setSingleShot(True)
        self._rebase_timer.timeout.connect(self.rebase_if_needed)
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(25)
        self._drag_timer.timeout.connect(self._drag_tick)
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.timeout.connect(self._flush_wheel)
        self.selectionChanged.connect(self._native_selection)
        self.cursorPositionChanged.connect(self._native_selection)
        self.verticalScrollBar().valueChanged.connect(self._native_scroll)
        self._guard = False

    @contextmanager
    def changing(self):
        previous = self._guard
        self._guard = True
        try:
            yield
        finally:
            self._guard = previous


    def largest_source_number(self):
        return self.model.max_source_line

    def _units(self, row):
        return utf16_length(self.model.line(row).text)

    def _screen_rows(self):
        return max(1, ceil(self.viewport().height() / max(1, self.fontMetrics().height())))


    def _document_destroyed(self, *_args):
        self.live_documents -= 1
        self.destroyed_documents += 1

    def _layout_destroyed(self, *_args):
        self.live_layouts -= 1


    def _write_row(self, cursor, number):
        line = self.model.line(number)
        role = "matched_text" if line.is_match else "body"
        position = 0
        for span in line.match_spans:
            cursor.insertText(line.text[position:span.start], self._formats[role])
            cursor.insertText(line.text[span.start:span.end], self._formats["match"])
            position = span.end
        cursor.insertText(line.text[position:], self._formats[role])
        self._set_row_metadata(cursor.block(), number)


    def point_y(self, point):
        block = self._block(point.row)
        line = block.layout().lineForTextPosition(point.column)
        return self.blockBoundingGeometry(block).translated(self.contentOffset()).top() + line.y()


    def _project_selection(self):
        if not self.window_end:
            return
        with self.changing():
            cursor = QTextCursor(self.document())
            cursor.setPosition(self._qt_position(self.anchor))
            cursor.setPosition(self._qt_position(self.caret), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def _native_selection(self):
        if self._guard:
            return
        cursor = self.textCursor()
        self.caret = self._native_point(cursor.position())
        if not (self._dragging or self._extending):
            self.anchor = self._native_point(cursor.anchor())

    def select(self, anchor, caret):
        top = self.top_point()
        self.anchor, self.caret = anchor, caret
        self.set_top(top)


    def createMimeDataFromSelection(self):  # noqa: N802
        mime = QMimeData()
        mime.setText(self.selected_text())
        return mime

    def copy(self):
        if self.anchor != self.caret:
            QApplication.clipboard().setMimeData(self.createMimeDataFromSelection())


    def _cancel_wheel(self):
        self._wheel_timer.stop()
        self._pending_wheel.clear()
        self._wheel_last_input = 0.0
        self._wheel_remainder = 0.0


    def wheelEvent(self, event):  # noqa: N802
        if event.angleDelta().x() or event.modifiers() & (
                Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            self._cancel_wheel()
            super().wheelEvent(event)
            return
        if event.phase() == Qt.ScrollPhase.ScrollEnd:
            self._cancel_wheel()
            event.accept()
            return
        now = perf_counter()
        if now - self._wheel_last_input >= self._wheel_idle_timeout:
            self._cancel_wheel()
        self._wheel_last_input = now
        if event.pixelDelta().y():
            self._wheel_remainder -= event.pixelDelta().y() / self.fontMetrics().height()
        else:
            self._wheel_remainder -= event.angleDelta().y() / 120 * QApplication.wheelScrollLines()
        steps = int(round(self._wheel_remainder, 9))
        self._wheel_remainder -= steps
        if steps and self.model.row_count:
            pending = self._pending_wheel[0] if self._pending_wheel else 0
            if pending * steps < 0:
                pending = 0
            limit = 2 * max(1, min(12, self._screen_rows()))
            pending = max(-limit, min(limit, pending + steps))
            if self.lineWrapMode() == self.LineWrapMode.NoWrap:
                current = self.top_point().row
                pending = max(-current, min(self.model.row_count - 1 - current, pending))
            self._pending_wheel.clear()
            if pending:
                self._pending_wheel.append(pending)
            else:
                self._wheel_timer.stop()
            if self._pending_wheel and not self._wheel_timer.isActive():
                self._wheel_timer.start(0)
        event.accept()

    def set_wrapping(self, enabled):
        top = self.top_point()
        with self.changing():
            self.setLineWrapMode(self.LineWrapMode.WidgetWidth if enabled else self.LineWrapMode.NoWrap)
            self._max_horizontal = 0
            self._layout_window()
            self.set_top(top)

    def resizeEvent(self, event):  # noqa: N802
        top = self.top_point() if self.window_end else None
        horizontal = self.horizontalScrollBar().value()
        with self.changing():
            super().resizeEvent(event)
            if top is not None:
                self._layout_window()
                self.set_top(top, cancel_wheel=False)
                self.horizontalScrollBar().setValue(horizontal)

    def keyPressEvent(self, event):  # noqa: N802
        self._cancel_wheel()
        if not self.model.row_count:
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.selectAll()
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            previous_top = self.top_point()
            step = -1 if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 1
            if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                step *= max(1, self.viewport().height() // self.fontMetrics().height() - 1)
            with self.changing():
                target = self._advance(self.caret, step, keep_x=True)
                self.caret = target
                if not shift:
                    self.anchor = target
                if self.window_start <= previous_top.row < self.window_end:
                    self.set_top(previous_top)
                    y = self.point_y(target)
                    if y < 0:
                        self.set_top(target)
                    elif y + self.fontMetrics().height() > self.viewport().height():
                        page = max(1, self.viewport().height() // self.fontMetrics().height())
                        self.set_top(self._advance(target, -(page - 1)))
                else:
                    self.set_top(target)
            return
        if control and key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            target = TextPoint(0) if key == Qt.Key.Key_Home else TextPoint(
                self.model.row_count - 1, self._units(self.model.row_count - 1))
            self.caret = target
            if not shift:
                self.anchor = target
            self.set_top(target)
            return
        self._extending = shift
        super().keyPressEvent(event)
        self._extending = False

    def mousePressEvent(self, event):  # noqa: N802
        self._cancel_wheel()
        self._extending = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._dragging = False
        super().mousePressEvent(event)
        self._extending = False
        self._dragging = event.button() == Qt.MouseButton.LeftButton

    def mouseMoveEvent(self, event):  # noqa: N802
        self._drag_point = event.position().toPoint()
        if self._dragging and not 0 <= self._drag_point.y() < self.viewport().height():
            self._drag_timer.start()
            return
        self._drag_timer.stop()
        super().mouseMoveEvent(event)


    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_timer.stop()
        super().mouseReleaseEvent(event)
        self._dragging = False

    def contextMenuEvent(self, event):  # noqa: N802
        menu = self.createStandardContextMenu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    def createStandardContextMenu(self, *args):  # noqa: N802
        menu = QMenu(self)
        action = menu.addAction("Copy\tCtrl+C", self.copy)
        action.setEnabled(self.anchor != self.caret)
        menu.addAction("Select All\tCtrl+A", self.selectAll)
        return menu

    def closeEvent(self, event):  # noqa: N802
        self._cancel_wheel()
        self._rebase_timer.stop()
        self._drag_timer.stop()
        super().closeEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._cancel_wheel()
        super().hideEvent(event)
