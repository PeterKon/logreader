import unittest

from source_test_case import SourceViewCase
from PySide6.QtTest import QTest
from logreader.ui.results.result_coordinates import TextPoint
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.source_model import SourcePresentation
from qt_helpers import wait_for_load


class SourceRetentionTests(SourceViewCase):
    def test_source_borrows_snapshot_and_far_jump_keeps_intervening_text_unloaded(self):
        lines = tuple(f"2026-10-21 12:00:00 INFO Source row {i:,} - message" for i in range(1, 120001))
        self.stage(lines, total=170000)
        self.assertIs(self.source.lines, self.page.session.lines)
        self.assertIs(self.source.editor.presentation.lines, lines)
        self.assertEqual(self.source.editor.ranges.loaded_count, 0)
        self.assertIsNone(self.page.session.analysis)
        self.view._source_button.click()
        self.settle_source()
        editor, loader = self.source.editor, self.source.loader
        self.assertFalse(loader.background)
        self.assertTrue(editor.viewport_evidence()["useful"])
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertEqual(editor.source_number(editor._block(0).blockNumber()), 50001)
        initial = editor.ranges.loaded_count
        self.assertLess(initial, 256)

        self.source.goto_input.setText("160000")
        self.source.goto_button.click()
        self.settle_source()
        self.assertEqual(editor.caret.row, 109999)
        self.assertEqual(editor.top_point().row, 109999)
        self.assertEqual(editor._block(109999).text(), lines[109999])
        self.assertTrue(editor.ranges.contains(0))
        self.assertFalse(editor.ranges.contains(60000))
        self.assertGreater(editor.ranges.loaded_count, initial)
        self.assertLess(editor.ranges.loaded_count, 512)
        self.assertTrue(editor.viewport_evidence()["useful"])
        counts = editor.ranges.loaded_count, editor.insertion_count, loader.tick_count
        QTest.qWait(250)
        self.assertEqual((editor.ranges.loaded_count, editor.insertion_count, loader.tick_count), counts)
        self.assertEqual(self.window.statusBar().currentMessage(), "120,000 of 170,000 lines shown - UTF-8")
        self.assertFalse(self.page.session.is_busy)
        self.assertIsNone(self.page.session.analysis)

    def test_global_scrollbar_seeks_and_revisit_does_not_insert_again(self):
        lines = tuple(f"Source row {i}" for i in range(5000))
        self.stage(lines)
        self.view.set_source_active(True)
        self.settle_source()
        self.source.global_scroll.setValue(4000)
        self.settle_source()
        editor = self.source.editor
        self.assertEqual(editor.top_point().row, 4000)
        self.assertFalse(editor.ranges.contains(2000))
        count = editor.insertion_count
        self.source.global_scroll.setValue(0)
        self.settle_source()
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertEqual(editor.insertion_count, count)

    def test_actual_tail_load_and_lower_setting_keep_loaded_snapshot(self):
        self.path.write_text("\n".join(f"line {i}" for i in range(1, 91)), encoding="utf-8")
        self.page.load_file(self.path, max_lines_scanned=12)
        self.view.set_source_active(True)
        wait_for_load(self.page)
        self.settle_source()
        source = self.source
        self.assertEqual((source.first_line, source.total_line_count), (79, 90))
        self.assertIs(source.lines, self.page.session.lines)
        self.assertEqual(len(source.lines), 12)
        self.page.filter_panel._limit_spin.setValue(3)
        self.assertEqual(source.editor.presentation.row_count, 12)
        self.assertTrue(source.go_to_line(90))
        self.settle_source()
        self.assertEqual(source.editor.caret.row, 11)
        self.assertEqual(source.editor._block(11).text(), "line 90")
        self.assertEqual(source.editor.presentation.resolve(SourceLocation(self.page.session.snapshot_id, 79)), 0)
        self.assertIsNone(source.editor.presentation.resolve(SourceLocation("stale", 79)))
        before = source.editor.top_point()
        self.assertFalse(source.go_to_line(78))
        self.assertEqual(source.editor.top_point(), before)

    def test_empty_snapshot_and_smaller_replacement_reset_source_ranges(self):
        self.stage(tuple(f"line {i}" for i in range(1000)))
        self.view.set_source_active(True)
        self.settle_source()
        self.source.go_to_line(900)
        self.settle_source()
        self.stage(())
        self.settle_source()
        self.assertEqual(self.source.editor.ranges.total, 0)
        self.assertEqual(self.source.editor.ranges.loaded_count, 0)
        self.assertEqual(self.source.editor.placeholderText(), "Empty source file")
        self.assertEqual(self.window.statusBar().currentMessage(), "0 lines shown - UTF-8")
        self.assertFalse(self.source.goto_button.isEnabled())
        self.assertFalse(self.source.global_scroll.isVisible())
        self.assertEqual(self.source.editor.toPlainText(), "")
        self.stage(("only line",), total=9)
        self.settle_source()
        self.assertEqual(self.source.first_line, 9)
        self.assertEqual(self.source.editor.ranges.loaded_count, 1)
        self.assertEqual(self.source.editor._block(0).text(), "only line")

    def test_model_construction_does_not_traverse_text(self):
        class Snapshot(tuple):
            def __iter__(self):
                raise AssertionError("Model construction traversed source")
        lines = Snapshot(("first", "last"))
        model = SourcePresentation(lines, 50000, "snapshot")
        self.assertIs(model.lines, lines)
        self.assertEqual(model.row_count, 2)
        self.assertEqual(model.line(0).number, 49999)
        self.assertIs(model.line(1).text, lines[1])


if __name__ == "__main__":
    unittest.main()
