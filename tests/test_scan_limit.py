import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QValidator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from logreader.analysis_worker import AnalysisWorker
from logreader.document_session import LoadPhase
from logreader.file_loader import LoadedLog
from logreader.load_worker import LoadWorker
from logreader.qt_app import LogreaderWindow
from logreader.work_queue import WorkQueue


class ScanLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "source.log"
        self.path.write_text("".join(f"ERROR: line {i}\n" for i in range(1, 11)), encoding="utf-8")
        self.window = LogreaderWindow()
        self.window.load_file(self.path)
        self.page = self.window._document
        self.wait_until(lambda: self.page.session.has_document)
        self.spin = self.page.filter_panel._limit_spin

    def tearDown(self):
        self.window.close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def wait_until(self, condition):
        for _ in range(1000):
            if condition():
                return
            QTest.qWait(5)
        self.fail("Operation did not complete")

    def stage_tail(self, count=3):
        self.page.stage_loaded_log(self.path, LoadedLog(
            tuple(f"ERROR: line {i}" for i in range(11 - count, 11)), "UTF-8", 10,
        ))

    def test_default_grouped_editing_pasting_and_positive_only(self):
        self.assertEqual(self.spin.value(), 1_000_000)
        self.assertEqual(self.spin.text(), "1 000 000")
        self.assertEqual(self.spin.minimum(), 1)
        self.assertEqual(self.spin.specialValueText(), "")
        for text in ("2 000 000", "2000000", "2\u00a0000\u00a0000"):
            with self.subTest(text=text):
                self.app.clipboard().setText(text)
                self.spin.lineEdit().selectAll()
                self.spin.lineEdit().paste()
                self.assertEqual(self.page.build_config().max_lines_scanned, 2_000_000)
                self.assertEqual(self.spin.text(), "2 000 000")
        for text in ("-1", "1.5", "Entire file", "2147483648"):
            self.assertEqual(self.spin.validate(text, len(text))[0], QValidator.State.Invalid)
        self.assertNotEqual(self.spin.validate("0", 1)[0], QValidator.State.Acceptable)

    def test_smaller_scan_reuses_source_with_offset_and_no_result_limit(self):
        self.stage_tail(5)
        retained = self.page.session.lines
        for combined in (False, True):
            self.page.filter_panel._combined_view.setChecked(combined)
            self.spin.setValue(2)
            with patch("logreader.load_worker.load_log", side_effect=AssertionError("Unneeded reload")):
                self.page.analyze()
                self.wait_until(lambda: not self.page.session.is_busy)
            self.assertIs(self.page.session.lines, retained)
            self.assertEqual(self.page.session.analysis.line_count, 2)
            for category in self.page.session.analysis.categories.values():
                if category.match_count:
                    self.assertEqual([line.number for line in category.excerpts[0].lines], [9, 10])
            output = self.page.results_view.editor.toPlainText()
            self.assertNotIn("line 8", output)
            self.assertIn("9      -> ERROR: line 9", output)
            self.assertIn("10     -> ERROR: line 10", output)
            self.assertNotIn("Showing", output)

    def test_increase_waits_for_analyze_then_reloads_and_uses_captured_settings(self):
        self.stage_tail()
        self.page.results_view.editor.setPlainText("old results")
        self.page.results_view._search_input.setText("old")
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.spin.setValue(6)
            self.assertEqual(workers, [])
            self.assertEqual(len(self.page.session.lines), 3)
            self.page.analyze()
            self.assertEqual(len(workers), 1)
            load = workers[0]
            self.assertIsInstance(load, LoadWorker)
            self.assertEqual(load.max_lines_scanned, 6)
            self.assertEqual(self.page.session.lines, ())
            self.assertEqual(self.page.results_view.editor.toPlainText(), "")
            self.assertEqual(self.page.results_view._search_input.text(), "")
            self.assertFalse(self.window._analyze_button.isEnabled())
            self.spin.setValue(8)
            self.page.filter_panel._pattern_checkboxes["error_colon"].setChecked(False)
            load.run()
            self.assertEqual(len(workers), 2)
            analysis = workers[1]
            self.assertIsInstance(analysis, AnalysisWorker)
            self.assertEqual(len(analysis.lines), 6)
            self.assertEqual(analysis.line_offset, 4)
            self.assertEqual(self.page.session.active_request.config.max_lines_scanned, 6)
            analysis.run()
        self.wait_until(lambda: not self.page.session.is_busy)
        self.assertEqual(self.page.session.analysis.line_count, 6)
        self.assertEqual(self.page.session.analysis.category("combined").matched_line_count, 6)
        self.assertEqual(self.spin.value(), 8)

    def test_failure_can_retry_with_analyze_and_keeps_path_filters_and_limit(self):
        self.stage_tail()
        self.spin.setValue(6)
        self.path.unlink()
        self.page.analyze()
        self.wait_until(lambda: self.page.session.load_phase is LoadPhase.FAILED)
        self.assertEqual(self.page.session.lines, ())
        self.assertIsNone(self.page.session.analysis)
        self.assertEqual(self.page.session.path, self.path)
        self.assertEqual(self.spin.value(), 6)
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertIn("Press Analyze to retry", self.page.status_message)
        self.path.write_text("ERROR: replacement\n", encoding="utf-8")
        self.window.analyze_current()
        self.wait_until(lambda: self.page.session.analysis is not None and not self.page.session.is_busy)
        self.assertEqual(self.page.session.lines, ("ERROR: replacement",))
        self.assertEqual(self.page.session.total_line_count, 1)
        with patch("logreader.load_worker.load_log", side_effect=AssertionError("Already have whole file")):
            self.spin.setValue(100)
            self.page.analyze()
            self.wait_until(lambda: not self.page.session.is_busy)
        self.assertEqual(self.page.session.analysis.line_count, 1)

    def test_closing_or_superseding_reload_discards_pending_auto_analysis(self):
        for close in (False, True):
            with self.subTest(close=close):
                self.stage_tail()
                self.spin.setValue(6)
                workers = []
                with patch.object(WorkQueue, "submit", side_effect=workers.append):
                    self.page.analyze()
                    load = workers[0]
                    if close:
                        self.window.close_tab(0)
                    else:
                        self.stage_tail(2)
                    load.signals.completed.emit(load.request_id, LoadedLog(("late",), "UTF-8"))
                    load.signals.failed.emit(load.request_id, "late failure")
                    load.run()
                    self.assertEqual(len(workers), 1)
                    self.assertIsNone(self.page._pending_analysis)
                    self.assertIsNone(self.page.session.analysis)

    def test_new_tabs_have_independent_default_limits(self):
        self.spin.setValue(2_000_000)
        other = self.root / "other.log"
        other.write_text("ERROR: other", encoding="utf-8")
        self.window.load_file(other)
        second = self.window._document
        self.wait_until(lambda: second.session.has_document)
        self.assertEqual(second.build_config().max_lines_scanned, 1_000_000)
        self.window._select_document(self.page)
        self.assertEqual(self.page.build_config().max_lines_scanned, 2_000_000)
