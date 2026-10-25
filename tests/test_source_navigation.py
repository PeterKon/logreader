import unittest

from source_test_case import SourceViewCase
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider, QPushButton
from logreader.ui.results.result_coordinates import TextPoint
from logreader.ui.source_search import utf16_length
import test_progressive_results as existing


class SourceInteractionTests(SourceViewCase):
    wheel = existing.ProgressiveResultsTests.wheel
    finish_wheel = existing.ProgressiveResultsTests.finish_wheel
    wait_jump = existing.ProgressiveResultsTests.wait_jump
    jump = existing.ProgressiveResultsTests.jump
    quiet = existing.ProgressiveResultsTests.quiet
    state = existing.ProgressiveResultsTests.state

    def open_source(self, lines, *, wrapped=False, total=None):
        self.stage(tuple(lines), total=total)
        self.view.set_source_active(True)
        self.view.set_line_wrapping(wrapped)
        self.settle_source()
        self.source.loader.buffer_rows = 0
        self.source.editor.setFocus()
        return self.source.editor

    def at(self, point):
        self.source.editor.navigate_to(point, move_caret=True)
        self.settle_source()

    def test_copy_all_and_unloaded_endpoints_keep_exact_snapshot_text(self):
        lines = tuple("" if i % 11 == 0 else f"row {i:04} \tα😀\u00a0omega  " for i in range(800))
        editor = self.open_source(lines)
        self.at(TextPoint(650))
        first, last = 210, 390
        left = utf16_length(lines[first].split("😀")[0])
        right = utf16_length(lines[last].split("😀")[0] + "😀")
        expected = "\n".join([lines[first][lines[first].index("😀"):], *lines[first+1:last],
                              lines[last][:lines[last].index("😀") + 1]])
        points = TextPoint(first, left), TextPoint(last, right)
        self.assertFalse(editor.ranges.contains(first))
        self.assertFalse(editor.ranges.contains(last))
        self.addCleanup(self.app.clipboard().clear)
        for pair in (points, tuple(reversed(points))):
            editor.select(*pair)
            count = editor.insertion_count
            QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(self.app.clipboard().text(), expected)
            self.assertEqual(editor.insertion_count, count)
            editor.navigate_to(TextPoint(300))
            self.settle_source()
            self.assertEqual((editor.anchor, editor.caret), pair)
            self.assertEqual(editor.selected_text(), expected)
        for ending in ("last\t😀", ""):
            contents = lines[:-1] + (ending,)
            editor = self.open_source(contents)
            self.at(TextPoint(650))
            count = editor.insertion_count
            top = editor.top_point()
            QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual((editor.anchor, editor.caret), (TextPoint(0), TextPoint(len(contents))))
            QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(self.app.clipboard().text(), "\n".join(contents))
            self.assertEqual(editor.top_point(), top)
            self.assertEqual(editor.insertion_count, count)
            editor.select(TextPoint(799, 2 if ending else 0), TextPoint(len(contents)))
            self.assertEqual(editor.selected_text(), ending[2:] if ending else "")

    def test_wheel_crosses_unloaded_boundaries_in_both_directions(self):
        for direction in (1, -1):
            editor = self.open_source(f"row {i}" for i in range(1600))
            self.quiet(self.source)
            editor.insert_range(800, 804)
            editor.insert_range(1100, 1120)
            with editor.changing():
                editor.set_top(TextPoint(800))
            self.assertFalse(editor.ranges.contains(804 if direction > 0 else 799))
            self.wheel(editor, angle=-120 * direction)
            self.finish_wheel(editor)
            self.settle_source()
            self.assertEqual(editor.top_point().row, 800 + direction * QApplication.wheelScrollLines())
            self.assertTrue(editor.viewport_evidence()["useful"])
            self.assertFalse(editor.ranges.contains(1000))

    def test_keys_cross_wrapped_boundaries_and_preserve_shift_anchor(self):
        for key, delta in ((Qt.Key.Key_Down, 1), (Qt.Key.Key_Up, -1),
                           (Qt.Key.Key_PageDown, 1), (Qt.Key.Key_PageUp, -1)):
            editor = self.open_source((f"row {i} " + "wrapped payload " * 30 for i in range(1000)), wrapped=True)
            self.quiet(self.source)
            editor.insert_range(500, 501)
            block = editor._prepare_block(500)
            origin = TextPoint(500, block.layout().lineAt(block.layout().lineCount()-1).textStart() if delta > 0 else 0)
            with editor.changing():
                editor.anchor = editor.caret = origin
                editor.set_top(origin)
            QTest.keyClick(editor, key, Qt.KeyboardModifier.ShiftModifier)
            self.settle_source()
            self.assertEqual(editor.anchor, origin)
            self.assertGreater((editor.caret.row - 500) * delta, 0)
            self.assertLess(abs(editor.caret.row - 500), editor._screen_rows() + 1)
            self.assertTrue(editor.ranges.contains(editor.caret.row))
            self.assertIsInstance(editor.location_at(editor.textCursor().position()), TextPoint)

    def test_horizontal_keys_and_document_endpoints_skip_no_source_lines(self):
        editor = self.open_source(f"row {i} α😀" for i in range(1600))
        self.quiet(self.source)
        editor.insert_range(800, 802)
        editor.insert_range(1100, 1120)
        for forward in (True, False):
            origin = TextPoint(801, editor._units(801)) if forward else TextPoint(800)
            with editor.changing():
                editor.anchor = editor.caret = origin
                editor.set_top(TextPoint(800))
            QTest.keyClick(editor, Qt.Key.Key_Right if forward else Qt.Key.Key_Left)
            self.settle_source()
            self.assertEqual(editor.caret.row, 802 if forward else 799)
        QTest.keyClick(editor, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
        self.settle_source()
        self.assertEqual(editor.caret, TextPoint(0))
        QTest.keyClick(editor, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.settle_source()
        self.assertEqual(editor.anchor, TextPoint(0))
        self.assertEqual(editor.caret, TextPoint(1599, editor._units(1599)))
        self.assertEqual(editor.selected_text(), "\n".join(self.source.lines))
        self.assertFalse(editor.ranges.contains(600))

    def test_real_scrollbar_drag_and_revisit_preserve_logical_selection(self):
        editor = self.open_source(f"row {i} α😀" for i in range(6000))
        editor.select(TextPoint(100, 2), TextPoint(400, 8))
        selected = editor.selected_text()
        bar = self.source.global_scroll
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        slider = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                           QStyle.SubControl.SC_ScrollBarSlider, bar)
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=slider.center())
        for fraction in (.75, .55, .9):
            QTest.mouseMove(bar, QPoint(bar.width()//2, round(bar.height()*fraction)))
            self.assertTrue(bar.isSliderDown())
            self.assertIsNotNone(editor.navigation.pending)
        destination = bar.value()
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(bar.width()//2, round(bar.height()*.9)))
        self.settle_source()
        self.assertEqual(editor.top_point().row, destination)
        self.assertEqual((editor.anchor, editor.caret), (TextPoint(100, 2), TextPoint(400, 8)))
        self.assertEqual(editor.selected_text(), selected)
        count = editor.insertion_count
        for row in (0, destination, 0, destination):
            editor.navigate_to(TextPoint(row))
            self.settle_source()
        self.assertEqual(editor.insertion_count, count)
        self.assertFalse(editor.ranges.contains(3000))

    def test_shift_click_extends_selection_across_unloaded_text(self):
        lines = tuple("" if i % 7 == 0 else f"row {i:04}:\tUnicode α😀 and trailing spaces  " for i in range(1600))
        editor = self.open_source(lines)
        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 25))
        anchor = editor.anchor
        self.source.global_scroll.setValue(1200)
        self.settle_source()
        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier, QPoint(200, 70))
        self.assertEqual(editor.anchor, anchor)
        self.assertGreaterEqual(editor.caret.row, 1200)
        self.assertFalse(editor.ranges.contains(600))
        start, end = sorted((editor.anchor, editor.caret))
        expected = "\n".join([
            lines[start.row].encode("utf-16-le")[start.column * 2:].decode("utf-16-le"),
            *lines[start.row+1:end.row],
            lines[end.row].encode("utf-16-le")[:end.column * 2].decode("utf-16-le"),
        ])
        self.assertEqual(editor.selected_text(), expected)

    def test_mouse_selection_loads_adjacent_rows_and_stops_on_release(self):
        for direction in (1, -1):
            editor = self.open_source(f"row {i:04}: α😀 whitespace  " for i in range(1600))
            self.quiet(self.source)
            editor.insert_range(800, 830)
            with editor.changing():
                editor.set_top(TextPoint(800))
            QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(120, 25))
            anchor = editor.anchor
            outside = QPoint(170, editor.viewport().height() + 20 if direction > 0 else -20)
            QTest.mouseMove(editor.viewport(), outside)
            QTest.qWait(300)
            self.assertTrue(editor._dragging)
            self.assertEqual(editor.anchor, anchor)
            self.assertGreater((editor.top_point().row - 800) * direction, 6)
            self.assertGreater((editor.caret.row - 800) * direction, 6)
            self.assertTrue(editor.ranges.contains(editor.caret.row))
            QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=outside)
            self.settle_source()
            state = self.state(editor)
            count = editor.insertion_count
            QTest.qWait(60)
            self.assertEqual(self.state(editor), state)
            self.assertEqual(editor.insertion_count, count)
            self.assertIsNone(editor.navigation.pending)
            self.assertEqual(editor.location_at(editor.textCursor().anchor()), editor.anchor)
            self.assertEqual(editor.location_at(editor.textCursor().position()), editor.caret)
            self.assertIn("α😀", editor.selected_text())

    def test_wrap_zoom_and_resize_keep_selection_and_long_line_position(self):
        lines = [f"row {i}: ordinary source" for i in range(900)]
        lines[450] = "row 450: \tα😀 " + "long payload 0123456789 " * 1500
        editor = self.open_source(lines, total=10000900)
        self.at(TextPoint(450, 0))
        points = TextPoint(450, 13), TextPoint(450, 110)
        editor.select(*points)
        selected = editor.selected_text()
        self.source.target_line = None
        self.source._refresh()
        horizontal = editor.horizontalScrollBar()
        horizontal.setValue(750)
        self.assertGreater(horizontal.value(), 0)
        self.assertEqual(editor.top_point().row, 450)
        self.view.set_line_wrapping(True)
        self.settle_source()
        self.assertEqual(editor.top_point().row, 450)
        self.assertEqual((editor.anchor, editor.caret), points)
        self.assertEqual(editor.selected_text(), selected)
        self.assertFalse(editor.horizontalScrollBar().isVisible())
        for operation in (lambda: self.view.zoom(2), lambda: self.window.resize(1000, 780), self.view.reset_zoom):
            operation()
            self.settle_source()
            self.assertEqual(editor.top_point().row, 450)
            self.assertEqual((editor.anchor, editor.caret), points)
            self.assertEqual(editor.selected_text(), selected)
            self.assertTrue(editor.viewport_evidence()["useful"])
        self.view.set_line_wrapping(False)
        self.settle_source()
        self.assertEqual((editor.anchor, editor.caret), points)
        self.assertFalse(editor.ranges.contains(200))
        self.assertEqual(editor.font(), self.view._editor.font())
        self.assertEqual(editor.document().documentMargin(), self.view._editor.document().documentMargin())
        self.assertEqual(editor.gutter.geometry().left(), self.view._editor.gutter.geometry().left())
        self.assertFalse(any(self.source.findChild(QPushButton, f"source{name}Page") for name in ("First", "Previous", "Next", "Last")))

    def test_wrapped_bottom_does_not_scroll_over_hidden_spacers(self):
        self.window.resize(820, 800)
        editor = self.open_source((f"row {i}: " + "wrapped text " * 12 for i in range(2000)), wrapped=True)
        self.source.global_scroll.setValue(self.source.global_scroll.maximum())
        self.settle_source()
        QTest.qWait(20)
        self.assertTrue(editor.at_bottom())
        self.assertFalse(editor.ranges.contains(1000))
        self.assertEqual(editor.horizontalScrollBar().maximum(), 0)
        self.assertEqual(editor.horizontalScrollBar().value(), 0)
        self.assertFalse(editor.horizontalScrollBar().isVisible())
        self.assertFalse(self.source.surface.corner.isVisible())
        self.view.set_line_wrapping(False)
        self.settle_source()
        self.assertGreater(editor.horizontalScrollBar().maximum(), 0)
        self.assertTrue(editor.horizontalScrollBar().isVisible())

if __name__ == "__main__":
    unittest.main()
