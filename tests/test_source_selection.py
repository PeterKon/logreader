import hashlib

from source_test_case import SourceViewCase
from test_progressive_results import PaintObserver
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from logreader.ui.results.result_coordinates import TextPoint
from qt_helpers import wait_for_load


class SourceSelectionTests(SourceViewCase):

    def test_wrapped_source_repaints_after_resizing_while_hidden(self):
        other_path = self.path.with_name("other.log")
        other_path.write_text("INFO: other document\n", encoding="utf-8")
        self.window.load_file(other_path)
        other = self.window._document
        wait_for_load(other)
        self.window._select_document(self.page)
        lines = tuple(f"row {i}: " + "wrapped payload " * 30 for i in range(6000))
        for hidden_by in ("results", "tab"):
            with self.subTest(hidden_by=hidden_by):
                self.window.resize(1000, 850)
                self.stage(lines)
                self.view.set_source_active(True)
                self.view.set_line_wrapping(True)
                self.source.go_to_line(5000)
                self.settle_source()
                editor = self.source.editor
                editor.scroll_visual_lines(1)
                self.settle_source()
                top = editor.top_point()
                self.assertGreater(top.column, 0)
                editor.select(TextPoint(4999, 4), TextPoint(5000, 8))
                selection = editor.anchor, editor.caret, editor.selected_text()
                observer = PaintObserver(editor, editor.viewport())

                if hidden_by == "results":
                    self.view.set_source_active(False)
                else:
                    self.window._select_document(other)
                self.assertFalse(editor.isVisible())
                self.window.resize(1600, 650)
                self.app.processEvents()
                if hidden_by == "results":
                    self.view.set_source_active(True)
                else:
                    self.window._select_document(self.page)
                self.settle_source()

                self.assertTrue(editor.viewport().updatesEnabled())
                self.assertEqual(editor.top_point().row, top.row)
                self.assertEqual((editor.anchor, editor.caret, editor.selected_text()), selection)
                self.assertIs(self.source.lines, lines)
                # Layout readiness alone missed the bug. Require a scheduled
                # paint, without grab()/render() forcing the viewport to draw.
                observer.rows.clear()
                editor.viewport().update()
                for _ in range(100):
                    QTest.qWait(5)
                    if observer.rows:
                        break
                self.assertTrue(observer.rows)

    def test_two_million_line_ctrl_a_copy_retains_exact_snapshot_without_loading_text(self):
        lines = tuple(f"row {i:07d}\tUnicode α😀 trailing  " if i % 13 else ""
                      for i in range(1_999_999)) + ("",)
        expected = "\n".join(lines)
        digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
        self.stage(lines, total=2_100_000)
        self.view.set_source_active(True)
        self.addCleanup(self.app.clipboard().clear)
        for wrapped in (False, True):
            self.view.set_line_wrapping(wrapped)
            self.source.go_to_line(1_900_000)
            self.settle_source()
            editor = self.source.editor
            before = editor.insertion_count, editor.ranges.loaded_count, editor.top_point()
            QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual((editor.anchor, editor.caret), (TextPoint(0), TextPoint(len(lines))))
            QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            actual = self.app.clipboard().text()
            self.assertEqual(actual, expected)
            self.assertEqual(hashlib.sha256(actual.encode("utf-8")).hexdigest(), digest)
            self.assertEqual((editor.insertion_count, editor.ranges.loaded_count, editor.top_point()), before)
            self.assertIs(self.source.lines, self.page.session.lines)
            self.assertFalse(self.source.loader.background)
            self.app.clipboard().clear()

    def test_resize_and_unwrap_fill_newly_exposed_screen_without_moving_selection(self):
        self.stage(tuple(f"row {i}: " + "wrapped words " * 9 for i in range(10000)))
        self.view.set_source_active(True)
        self.window.resize(900, 600)
        self.view.set_line_wrapping(True)
        self.source.go_to_line(5000)
        self.settle_source()
        editor = self.source.editor
        editor.select(TextPoint(4999, 2), TextPoint(5000, 7))
        selection = editor.anchor, editor.caret
        top = editor.top_point()
        for wrapped, height in ((True, 1200), (False, 1200)):
            self.window.resize(900, height)
            self.view.set_line_wrapping(wrapped)
            self.settle_source()
            self.assertTrue(editor.viewport_evidence()["useful"])
            self.assertEqual(editor.top_point(), top)
            self.assertEqual((editor.anchor, editor.caret), selection)
            self.assertFalse(editor.ranges.contains(9000))

    def test_centered_source_bookmark_keeps_caret_and_wrapped_target_visible(self):
        self.stage(tuple(f"row {i}: " + "wrap " * (50 if i % 3 else 2) for i in range(1000)))
        self.view.set_source_active(True)
        for wrapped in (False, True):
            self.view.set_line_wrapping(wrapped)
            self.source.go_to_line(700, center=True)
            self.settle_source()
            editor = self.source.editor
            self.assertEqual(editor.caret, TextPoint(699))
            self.assertTrue(editor.viewport_evidence()["useful"])
            self.assertLess(abs(editor.cursorRect().center().y() - editor.viewport().height() / 2),
                            editor.fontMetrics().height() * 2)
