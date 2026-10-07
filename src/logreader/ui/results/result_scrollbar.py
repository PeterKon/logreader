"""Logical result positions and search/bookmark markers."""
from array import array
from bisect import bisect_left
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider, QAbstractSlider
from .result_coordinates import TextPoint
from .results_style import _results_editor_style_sheet
from ..theme import THEME_COLORS

class GlobalMarkerScrollBar(QScrollBar):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.match_rows = array("I")
        self.bookmark_rows = array("I")
        self._marker_cache = {}

    def set_marker_rows(self, *, matches=None, bookmarks=None):
        if matches is not None:
            self.match_rows = matches
        if bookmarks is not None:
            self.bookmark_rows = array("I", sorted(set(bookmarks)))
        self._marker_cache.clear()
        self.update()

    def _marker_rows_for_groove(self, groove, *, bookmarks=False):
        extent = self._marker_extent()
        key = (*groove.getRect(), self.minimum(), extent)
        cached = self._marker_cache.get(bookmarks)
        if cached is not None and cached[0] == key:
            return cached[1]
        blocks = self.bookmark_rows if bookmarks else self.match_rows
        span = max(1, extent - self.minimum())
        height = max(0, groove.height() - 1)
        rows = []
        index = 0
        # The global scrollbar uses display rows even when text is wrapped.
        # Skip all matches sharing a pixel so painting stays bounded by height.
        while index < len(blocks) and not groove.isEmpty():
            pixel = min(height, max(0, (blocks[index] - self.minimum()) * height // span))
            rows.append(groove.top() + pixel)
            if pixel == height:
                break
            next_row = self.minimum() + ((pixel + 1) * span + height - 1) // height
            index = bisect_left(blocks, next_row, lo=index + 1)
        result = tuple(rows)
        self._marker_cache[bookmarks] = (key, result)
        return result

    def _marker_extent(self):
        return self.maximum()

    def _paint_bar(self, event):
        super().paintEvent(event)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return option

    def paintEvent(self, event):
        option = self._paint_bar(event)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, option,
            QStyle.SubControl.SC_ScrollBarGroove, self)
        if groove.isEmpty():
            return
        slider = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, option,
            QStyle.SubControl.SC_ScrollBarSlider, self)
        painter = QPainter(self)
        painter.setClipRect(groove)
        for bookmarks, color in ((False, "ui_primary"), (True, "bookmark_marker")):
            for row in self._marker_rows_for_groove(groove, bookmarks=bookmarks):
                if not slider.top() <= row <= slider.bottom():
                    painter.fillRect(groove.left() + 2, row, max(1, groove.width() - 4),
                                     1, QColor(THEME_COLORS[color]))


class ProgressivePositionScrollBar(GlobalMarkerScrollBar):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._navigating = False
        style = _results_editor_style_sheet()
        self.setStyleSheet(style[style.index("QPlainTextEdit QScrollBar"):].replace("QPlainTextEdit ", ""))
        # Display rows are stable before insertion and independent of which
        # wrapped blocks Qt has visited. Page size is deliberately approximate.
        self.setRange(0, max(0, editor.presentation.row_count - 1))
        self.valueChanged.connect(self._seek)
        self.actionTriggered.connect(self._action)
        self.sliderPressed.connect(editor._cancel_wheel)
        self.sliderPressed.connect(editor.navigation.cancel)
        self.sliderReleased.connect(self.sync_position)
        editor.window_changed.connect(self.sync_position)
        editor.navigation.changed.connect(self.sync_position)
        self.sync_position()

    def sync_position(self):
        # Qt owns the pointer-to-thumb mapping throughout a drag. In particular,
        # never feed a clamped loaded row back into an unloaded drag destination.
        if self.isSliderDown() or self._navigating:
            return
        with QSignalBlocker(self):
            request = self.editor.navigation.pending
            self.setValue(request.point.row if request else self.editor.top_point().row)
            self.setPageStep(max(1, self.editor.viewport().height() // self.editor.fontMetrics().height()))

    def _seek(self, row):
        self._navigating = True
        try:
            self.editor.navigate_to(TextPoint(row))
        finally:
            self._navigating = False
        self.sync_position()

    def _action(self, action):
        actions = QAbstractSlider.SliderAction
        steps = {actions.SliderSingleStepSub.value: -1, actions.SliderSingleStepAdd.value: 1,
                 actions.SliderPageStepSub.value: -max(1, self.editor._screen_rows() - 1),
                 actions.SliderPageStepAdd.value: max(1, self.editor._screen_rows() - 1)}
        if action in steps:
            # Arrow buttons and page keys retain native visual-line movement even
            # though thumb travel represents logical rows.
            self.editor.scroll_visual_lines(steps[action])
            self.sync_position()

    def mousePressEvent(self, event):  # noqa: N802
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        control = QStyle.ComplexControl.CC_ScrollBar
        hit = self.style().hitTestComplexControl(control, option, event.position().toPoint(), self)
        if event.button() == Qt.MouseButton.LeftButton and hit in (
                QStyle.SubControl.SC_ScrollBarAddPage, QStyle.SubControl.SC_ScrollBarSubPage):
            groove = self.style().subControlRect(control, option, QStyle.SubControl.SC_ScrollBarGroove, self)
            slider = self.style().subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, self)
            row = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.position().toPoint().y() - groove.top() - slider.height() // 2,
                max(0, groove.height() - slider.height()), option.upsideDown)
            # Put the thumb under the pointer before Qt handles this press, so
            # the same held click starts a native drag instead of a page action.
            with QSignalBlocker(self):
                self.setValue(row)
            super().mousePressEvent(event)
            # sliderPressed cancels obsolete navigation. Issue the new request
            # afterwards so the snap survives that cancellation.
            self._seek(row)
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        self.editor.wheelEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.sync_position()


class SparsePositionScrollBar(ProgressivePositionScrollBar):
    def __init__(self, editor, parent=None):
        self._painted_option = None
        super().__init__(editor, parent)
        self.setVisible(editor.presentation.row_count > 0)

    def _paint_bar(self, event):
        if (self.editor.end_top() is None and self.editor._end_screen is not None
                and self._painted_option is not None and not self.isSliderDown()
                and not self._navigating):
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            option.subControls = QStyle.SubControl.SC_All
            # Keep the last painted geometry until cooperative measurement
            # finishes, but still repaint the track, including newly exposed area.
            # Disabling updates lets the parent's background flash through.
            for field in ("rect", "minimum", "maximum", "pageStep",
                          "sliderPosition", "sliderValue"):
                setattr(option, field, getattr(self._painted_option, field))
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(THEME_COLORS["scrollbar_track"]))
            self.style().drawComplexControl(QStyle.ComplexControl.CC_ScrollBar,
                                           option, painter, self)
            painter.end()
            return option
        option = super()._paint_bar(event)
        self._painted_option = QStyleOptionSlider(option)
        return option

    def _marker_extent(self):
        return max(0, self.editor.presentation.row_count - 1)

    def sync_position(self):
        if self.isSliderDown() or self._navigating:
            return
        editor = self.editor
        end = editor.end_top()
        maximum = editor.end_scroll_maximum()
        # Keep the measured thumb geometry while a resize is being measured.
        # Falling back to the full row count makes short results visibly jump.
        if maximum is None and editor._end_screen is not None:
            return
        with QSignalBlocker(self):
            self.setRange(0, maximum if maximum is not None else max(0, editor.presentation.row_count - 1))
            request = editor.navigation.pending
            point = request.point if request else editor.top_point()
            value = point.row
            if end is not None and point.row == end.row:
                # The final logical row may still contain several screens of
                # wrapped text. Its remaining travel uses visual-line steps.
                if request and request.movement:
                    value += request.movement.delta
                elif point.column:
                    layout = editor._block(point.row).layout()
                    if layout.lineCount():
                        value += layout.lineForTextPosition(point.column).lineNumber()
            self.setValue(value)
            self.setPageStep(max(1, editor.viewport().height() // editor.fontMetrics().height()))
        if maximum is not None:
            self.setVisible(maximum > 0)

    def _seek(self, row):
        end = self.editor.end_top()
        if end is None or row <= end.row:
            return super()._seek(row)
        self._navigating = True
        try:
            self.editor.navigation.request_reading(TextPoint(end.row), row - end.row)
        finally:
            self._navigating = False
        self.sync_position()
