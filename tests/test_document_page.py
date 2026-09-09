import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import capture_analysis
    from PySide6.QtCore import QThreadPool
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

    from logreader.document_page import DocumentPage
    from logreader.document_session import AnalysisPhase
    from logreader.file_loader import LoadedLog
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class DocumentPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.first = DocumentPage()
        self.second = DocumentPage()
        self.first.stage_loaded_log(
            Path("first.log"), LoadedLog(("ERROR: first",), "UTF-8")
        )
        self.second.stage_loaded_log(
            Path("second.log"), LoadedLog(("ERROR: second",), "UTF-8")
        )

    def tearDown(self):
        for page in (self.first, self.second):
            page.session.cancel_request()
            page._finish_analysis_request()
            page.close()
            page.deleteLater()
        self.app.processEvents()

    def wait_for_completion(self, spy):
        for _ in range(500):
            if spy.count():
                return
            QTest.qWait(10)
        self.fail("Document did not finish rendering")

    def test_equal_request_numbers_complete_in_their_own_pages(self):
        first_done = QSignalSpy(self.first.analysis_finished)
        second_done = QSignalSpy(self.second.analysis_finished)
        first_status = QSignalSpy(self.first.status_changed)
        self.first.filter_panel.findChild(QSpinBox, "contextSpin").setValue(7)
        draft = self.first.filter_panel.findChild(QLineEdit, "customPattern")
        draft.setText("unfinished draft")

        workers = []
        with capture_analysis(workers):
            self.first.analyze()
            self.second.analyze()
        self.assertEqual(workers[0].request_id, workers[1].request_id)

        # Later edits must not alter the configuration of the running request.
        self.first.filter_panel.findChild(QSpinBox, "contextSpin").setValue(9)
        first_status_before = first_status.count()
        workers[1].run()
        self.wait_for_completion(second_done)
        self.assertEqual(self.first.session.phase, AnalysisPhase.ANALYZING)
        self.assertIsNone(self.first.session.analysis)
        self.assertEqual(first_done.count(), 0)
        self.assertEqual(first_status.count(), first_status_before)
        self.assertIn("ERROR: second", self.second.results_view.editor.toPlainText())

        workers[0].run()
        self.wait_for_completion(first_done)
        first_output = self.first.results_view.editor.toPlainText()
        self.assertIn("ERROR: first", first_output)
        self.assertNotIn("ERROR: second", first_output)
        self.assertEqual(self.first.session.analysis_config.context, 7)
        self.assertEqual(self.first.build_config().context, 9)
        self.assertEqual(self.second.build_config().context, 3)
        self.assertEqual(draft.text(), "unfinished draft")
        self.assertFalse(self.first._analysis_busy_timer.isActive())
        self.assertFalse(self.second._analysis_busy_timer.isActive())

    def test_replacement_rejects_old_worker_and_rendering_signals(self):
        workers = []
        with capture_analysis(workers):
            self.first.analyze()
            old_id = workers[0].request_id
            self.first.stage_loaded_log(
                Path("replacement.log"), LoadedLog(("ERROR: replacement",), "UTF-8")
            )
            self.first.analyze()

        done = QSignalSpy(self.first.analysis_finished)
        failed = QSignalSpy(self.first.analysis_failed)
        status = QSignalSpy(self.first.status_changed)
        workers[0].run()
        workers[0].signals.failed.emit(old_id, "old failure")
        self.first.results_view.rendering_completed.emit(old_id, 1.0)
        self.first.results_view.rendering_failed.emit(old_id, "old render failure")
        self.assertEqual(self.first.session.phase, AnalysisPhase.ANALYZING)
        self.assertIsNone(self.first.session.analysis)
        self.assertEqual(done.count(), 0)
        self.assertEqual(failed.count(), 0)
        self.assertEqual(status.count(), 0)
        self.assertEqual(self.first.results_view.editor.toPlainText(), "")

        workers[1].run()
        self.wait_for_completion(done)
        self.assertIn("ERROR: replacement", self.first.results_view.editor.toPlainText())

    def test_worker_failure_only_finishes_and_notifies_its_owner(self):
        workers = []
        with capture_analysis(workers):
            self.first.analyze()
            self.second.analyze()
        first_failed = QSignalSpy(self.first.analysis_failed)
        second_failed = QSignalSpy(self.second.analysis_failed)
        with patch("logreader.analysis_worker.analyze_lines", side_effect=ValueError("bad pattern")):
            workers[1].run()
        self.assertEqual(first_failed.count(), 0)
        self.assertEqual(second_failed.at(0), ["bad pattern"])
        self.assertEqual(self.first.session.phase, AnalysisPhase.ANALYZING)
        self.assertEqual(self.second.session.phase, AnalysisPhase.IDLE)
        self.assertIs(self.first._analysis_worker, workers[0])
        self.assertIsNone(self.second._analysis_worker)
        self.assertFalse(self.second._analysis_busy_timer.isActive())

        done = QSignalSpy(self.first.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)
