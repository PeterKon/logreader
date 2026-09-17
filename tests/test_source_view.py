import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.file_loader import LoadedLog
from logreader.qt_app import LogreaderWindow
from logreader.source_search import iter_source_matches, utf16_length
from logreader.source_view import SOURCE_PAGE_CHARACTERS, SOURCE_PAGE_LINES
from logreader.work_queue import WorkQueue


class SourceSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_chunked_search_agrees_with_qt_for_unicode_case_and_overlaps(self):
        lines = (
            "😀 NEEDLE needle Straße STRASSE İ i ı I Σ σ ς",
            "a" * 4095 + "😀needle NEEDLE" + "a" * 4100,
            "a" * 8200,
            "", "é É e\u0301 E\u0301", "a\tb\tc",
        )
        for query in ("needle", "😀n", "aa", "a" * 5000, "straße", "i", "σ", "é", "a\tb"):
            with self.subTest(query=query[:20]):
                expected = []
                document = QTextDocument()
                for row, text in enumerate(lines):
                    document.setPlainText(text)
                    position = 0
                    while True:
                        match = document.find(query, position)
                        if match.isNull():
                            break
                        expected.append((row, match.selectionStart(), match.selectionEnd()))
                        position = match.selectionEnd()
                actual = [match for match in iter_source_matches(lines, query) if match is not None]
                self.assertEqual(actual, expected)

    def test_sparse_long_lines_yield_without_materializing_the_file(self):
        work = iter_source_matches(("x" * 100_000, "target"), "target")
        self.assertIsNone(next(work))
        self.assertIsNone(next(work))
        work.close()


class SourceViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "source.log"
        self.path.write_text("ERROR: initial\n", encoding="utf-8")
        self.window = LogreaderWindow()
        self.window.resize(1080, 800)
        self.window.show()
        self.window.load_file(self.path)
        self.page = self.window._document
        self.view = self.page.results_view
        self.source = self.view.source_view
        self.wait(lambda: self.page.session.has_document)

    def tearDown(self):
        self.window.close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self, predicate):
        for _ in range(2000):
            if predicate():
                return
            QTest.qWait(5)
        self.fail("Source operation did not finish")

    def wait_source_search(self):
        self.wait(lambda: not self.source.is_searching
                  and self.source._page_work is None
                  and not self.source.highlighter._highlight_timer.isActive())

    def stage(self, lines, total=None):
        lines = tuple(lines)
        self.page.stage_loaded_log(self.path, LoadedLog(lines, "UTF-8", total))
        return lines

    def render(self, config=None):
        config = config or LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        self.view.start_rendering(1, str(self.path), analyze_lines(
            self.page.session.lines, config.search_patterns(), combined=config.combined_view,
            line_offset=self.page.session.total_line_count - len(self.page.session.lines),
        ), config)
        self.wait(lambda: not self.view.is_rendering)

    def test_toggle_before_analysis_is_adjacent_and_reuses_bounded_source(self):
        lines = self.stage((f"row {i} " + "x" * 300 for i in range(4000)), total=9000)
        self.assertIs(self.source.lines, lines)
        self.assertEqual(self.source.editor.toPlainText(), "")
        self.assertTrue(self.view._source_button.isEnabled())
        self.assertGreater(self.view._source_button.x(), self.view._maximize_button.x())
        self.assertEqual(self.view._source_button.text(), "Go to source")
        self.view._source_button.click()
        self.assertTrue(self.view.source_active)
        self.assertEqual(self.view._source_button.text(), "Go to results")
        self.assertLessEqual(self.source.editor.blockCount(), SOURCE_PAGE_LINES)
        self.assertLessEqual(len(self.source.editor.toPlainText()), SOURCE_PAGE_CHARACTERS)
        self.assertEqual(self.source.editor.toPlainText(), "\n".join(lines[:self.source.page_end]))
        self.assertTrue(self.source.editor.isReadOnly())
        self.assertFalse(self.source.editor.document().isUndoRedoEnabled())
        self.assertIn("5,001", self.source.range_label.text())
        self.assertIsNone(self.page.session.analysis)
        self.view._source_button.click()
        self.assertFalse(self.view.source_active)
        self.assertEqual(self.view.editor.toPlainText(), "")

    def test_source_navigation_uses_source_background_for_bar_and_controls(self):
        background = "#0d1117"
        controls_bar = self.source.findChild(QWidget, "sourceNavigationHeader")

        self.assertIsNotNone(controls_bar)
        self.assertIn(background, controls_bar.styleSheet())
        self.assertIn(background, self.source.page_navigation.styleSheet())
        self.assertIn(background, self.source.line_navigation.styleSheet())

    def test_analyze_completes_without_leaving_source_view(self):
        self.stage((f"ERROR: row {i}" for i in range(200)))
        self.view.set_source_active(True)
        self.source.go_to_line(100)
        self.wait_source_search()
        position = self.source.editor.textCursor().position()
        scroll = self.source.editor.verticalScrollBar().value()
        finished = QSignalSpy(self.page.analysis_finished)

        for run in range(2):
            self.assertTrue(self.window._analyze_button.isEnabled())
            self.window._analyze_button.click()
            self.wait(lambda: finished.count() == run + 1)
            self.assertFalse(self.page.session.is_busy)
            self.assertFalse(self.page.busy_visible)
            self.assertFalse(self.view.is_rendering)
            self.assertTrue(self.view.source_active)
            self.assertEqual(self.source.editor.textCursor().position(), position)
            self.assertEqual(self.source.editor.verticalScrollBar().value(), scroll)
            self.assertIn("ERROR: row 199", self.view.editor.toPlainText())
            self.assertEqual(self.page.status_message, "All 200 lines scanned - UTF-8")

        self.view.set_source_active(False)
        self.assertIn("ERROR: row 199", self.view.editor.toPlainText())

    def test_switching_to_source_during_rendering_still_completes(self):
        finished = QSignalSpy(self.page.analysis_finished)
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.window._analyze_button.click()
            workers[0].run()
        self.assertTrue(self.view.is_rendering)
        self.view.set_source_active(True)
        self.wait(lambda: finished.count() == 1)
        self.assertTrue(self.view.source_active)
        self.assertFalse(self.page.session.is_busy)
        self.assertIn("ERROR: initial", self.view.editor.toPlainText())

    def test_source_can_be_opened_while_loading_and_empty_files_are_supported(self):
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.page.load_file(self.path)
            self.view.toggle_source()
            self.assertTrue(self.view._source_button.isEnabled())
            self.assertIn("Loading", self.source.editor.placeholderText())
            self.assertEqual(self.source.range_label.text(), "")
            workers[0].run()
        self.assertTrue(self.view.source_active)
        self.assertIn("ERROR: initial", self.source.editor.toPlainText())
        self.stage(())
        self.assertIn("Empty source", self.source.editor.placeholderText())
        self.assertEqual(self.source.range_label.text(), "")
        self.assertFalse(self.source.go_to_line(1))
        self.view.toggle_source()
        self.assertFalse(self.view.source_active)

    def test_mapping_handles_context_duplicates_headers_and_timing_insertion(self):
        lines = self.stage(("before", "ERROR: needle " + "x" * 200,
                            "after", "other", "ERROR: second"), total=10005)
        config = LogreaderConfig(context=1, combined_view=False,
                                enabled_patterns=("error_colon",), custom_patterns=("needle",))
        self.render(config)
        self.view.prepend_performance_timings(.1, .2)
        mapping = self.view._source_map
        block = self.view.editor.document().begin()
        mapped = []
        while block.isValid():
            original = mapping.source_line(block.blockNumber())
            if original is not None:
                self.assertIn(lines[original - 10001], block.text())
                mapped.append(original)
            block = block.next()
        self.assertGreater(mapped.count(10002), 1)
        self.assertIn(10001, mapped)
        self.assertIsNone(mapping.source_line(0))
        self.view.set_line_wrapping(True)
        block = self.view.editor.document().findBlockByNumber(mapping.starts[0] + mapping.header_blocks + 1)
        cursor = QTextCursor(block)
        self.view.editor.setTextCursor(cursor)
        self.view.editor.ensureCursorVisible()
        self.app.processEvents()
        point = self.view.editor.cursorRect(cursor).center()
        self.assertEqual(self.view.source_line_at(point), 10002)
        self.view.show_source_line(10002)
        self.assertEqual(self.source.target_line, 10002)
        self.assertEqual(self.source.editor.textCursor().block().text(), lines[1])
        self.assertTrue(self.source.editor.extraSelections())
        self.view.toggle_source()
        self.view.reset_for_loaded_file("replacement")
        self.assertIsNone(self.view._source_map.source_line(block.blockNumber()))

    def test_switching_preserves_results_search_selection_and_scroll(self):
        self.stage(f"ERROR: result {i} needle " + "x" * 200 for i in range(300))
        self.render()
        self.view._search_input.setText("needle")
        self.view.search_results()
        self.wait(lambda: not self.view.is_searching and not self.view._search_highlighter._highlight_timer.isActive())
        matches = self.view._search_matches
        cursor = self.view.editor.document().find("result 120")
        self.view.editor.setTextCursor(cursor)
        self.view.editor.ensureCursorVisible()
        before = (cursor.position(), cursor.anchor(), self.view.editor.verticalScrollBar().value())
        output = self.view.editor.toPlainText()
        self.view.show_source_line(121)
        self.view._search_input.setText("result 299")
        self.view.search_results()
        self.wait_source_search()
        self.view.find_next()
        self.assertEqual(self.source.current_match, 0)
        self.assertEqual(self.source.target_line, 121)
        self.view.set_line_wrapping(True)
        self.view.toggle_source()
        self.assertEqual(self.view._search_input.text(), "needle")
        self.assertIs(self.view._search_matches, matches)
        self.assertEqual(self.view.editor.toPlainText(), output)
        cursor = self.view.editor.textCursor()
        self.assertEqual((cursor.position(), cursor.anchor(), self.view.editor.verticalScrollBar().value()), before)
        self.assertEqual(self.view.editor.lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.toggle_source()
        self.assertEqual(self.view._search_input.text(), "result 299")
        self.assertTrue(self.view._line_wrap_check.isChecked())

    def test_search_covers_unshown_source_and_navigates_with_unicode_columns(self):
        target = SOURCE_PAGE_LINES + 2500
        lines = [f"plain row {i}".ljust(120, "x") for i in range(target + 1000)]
        lines[target] = "😀\tNEEDLE needle"
        self.stage(lines, total=len(lines) + 10000)
        self.view.toggle_source()
        self.assertEqual(self.source.page_end, SOURCE_PAGE_LINES)
        self.view._search_input.setText("needle")
        self.view.search_results()
        self.wait_source_search()
        self.assertEqual(list(self.source.matches.lines), [target, target])
        self.assertEqual(self.source.page_start, 0)  # Initial Enter never jumps.
        self.assertEqual(self.source.matches.starts[0], utf16_length("😀\t"))
        self.view.find_next()
        self.assertTrue(self.source.page_start <= target < self.source.page_end)
        self.wait_source_search()
        selection = self.source.editor.extraSelections()[-1]
        self.assertEqual(selection.cursor.selectedText(), "NEEDLE")
        self.view.find_next()
        selection = self.source.editor.extraSelections()[-1]
        self.assertEqual(selection.cursor.selectedText(), "needle")
        self.view.find_next()
        self.assertEqual(self.source.current_match, 0)
        self.view.find_previous()
        self.assertEqual(self.source.current_match, 1)
        self.assertEqual(self.source.editor.toPlainText(), "\n".join(lines[self.source.page_start:self.source.page_end]))

    def test_page_boundaries_and_original_go_to_line_do_not_skip_text(self):
        line_length = SOURCE_PAGE_CHARACTERS // 1000
        lines = self.stage((str(i) + "x" * line_length for i in range(1400)), total=9400)
        self.view.toggle_source()
        first_end = self.source.page_end
        self.assertLess(first_end, len(lines))
        self.source.next_page()
        self.assertEqual(self.source.page_start, first_end)
        self.source.previous_page()
        self.assertEqual(self.source.page_end, first_end)
        self.source.goto_input.setText("9 350")
        self.source.go_to_input()
        self.assertEqual(self.source.editor.textCursor().block().text(), lines[1349])
        before = self.source.editor.toPlainText()
        before_range = self.source.range_label.text()
        self.assertFalse(self.source.go_to_line(1))
        self.assertEqual(self.source.editor.toPlainText(), before)
        self.assertEqual(self.source.range_label.text(), before_range)
        self.assertIn("not loaded", self.source.goto_input.toolTip())
        self.assertTrue(self.source.go_to_line(9350))
        self.assertNotIn("not loaded", self.source.goto_input.toolTip())

    def test_cleared_results_count_does_not_reappear_on_switching(self):
        self.stage(("ERROR: needle",))
        self.render()
        self.view._search_input.setText("needle")
        self.view.search_results()
        self.wait(lambda: not self.view.is_searching)
        self.view._search_input.clear()
        self.view.toggle_source()
        self.view.toggle_source()
        self.assertTrue(self.view._search_count_label.isHidden())

    def test_failure_during_source_search_clears_query_and_retry_loads_snapshot(self):
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.page.load_file(self.path)
            self.view.toggle_source()
            self.view._search_input.setText("needle")
            self.view.search_results()
            self.path.unlink()
            workers[0].run()
        self.assertFalse(self.source.is_searching)
        self.assertEqual(self.view._search_input.text(), self.source.query)
        self.assertIn("Could not load", self.source.editor.placeholderText())
        self.assertEqual(self.source.range_label.text(), "")
        self.path.write_text("ERROR: replacement\n", encoding="utf-8")
        self.page.analyze()
        self.wait(lambda: self.page.session.analysis is not None)
        self.assertIn("replacement", self.source.editor.toPlainText())
        self.view.toggle_source()
        self.wait(lambda: not self.page.session.is_busy)

    def test_query_edit_and_replacement_cancel_search_and_release_snapshot(self):
        self.stage(("needle " * 500 for _ in range(3000)))
        self.view.toggle_source()
        self.view._search_input.setText("needle")
        self.view.search_results()
        self.source._advance_search()
        self.assertTrue(self.source.is_searching)
        self.view._search_input.setText("replacement")
        self.assertFalse(self.source.is_searching)
        self.assertFalse(self.source.matches)
        self.stage(("replacement",))
        self.assertEqual(self.source.lines, ("replacement",))
        self.assertEqual(self.view._search_input.text(), "")
        self.view._search_input.setText("replacement")
        self.view.search_results()
        self.wait_source_search()
        self.assertEqual(len(self.source.matches), 1)
        self.window.close_tab(0)
        self.assertFalse(self.source.lines)
        self.assertIsNone(self.source._search_work)
        self.assertIsNone(self.source._page_work)

    def test_source_and_results_rendering_switch_without_stranding_session(self):
        self.stage(f"ERROR: row {i}" for i in range(2000))
        self.view.toggle_source()
        self.page.analyze()
        self.wait(lambda: self.page.session.analysis is not None)
        self.assertTrue(self.view.source_active)
        self.assertTrue(self.view.is_rendering)
        self.view.toggle_source()
        self.wait(lambda: not self.page.session.is_busy)
        self.assertIn("row 1999", self.view.editor.toPlainText())

    def test_each_document_owns_source_query_page_and_mode(self):
        self.stage(f"first needle {i}" for i in range(2500))
        self.view.toggle_source()
        self.source.go_to_line(2200)
        self.view._search_input.setText("needle")
        other = Path(self.temp.name) / "other.log"
        other.write_text("second\n", encoding="utf-8")
        self.window.load_file(other)
        second = self.window._document
        self.wait(lambda: second.session.has_document)
        second.results_view.toggle_source()
        self.assertEqual(second.results_view.source_view.editor.toPlainText(), "second")
        self.window._select_document(self.page)
        self.assertTrue(self.view.source_active)
        self.assertEqual(self.source.target_line, 2200)
        self.assertEqual(self.view._search_input.text(), "needle")


if __name__ == "__main__":
    unittest.main()
