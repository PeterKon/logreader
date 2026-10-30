import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import capture_analysis, trigger_pattern_action, wait_for_search, wait_source, wait_until
    from PySide6.QtCore import QThreadPool, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

    from logreader.ui.document_page import DocumentPage
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

    def test_exclusive_filters_are_omitted_from_request_and_result_counts(self):
        panel = self.first.filter_panel
        for checkbox in panel._pattern_checkboxes.values():
            checkbox.setChecked(False)
        for pattern in ("first", "ERROR", "skip"):
            panel._custom_pattern.setText(pattern)
            panel.add_custom_pattern()
        trigger_pattern_action(panel._custom_pattern_list, 0, "Exclusive")
        trigger_pattern_action(panel._custom_pattern_list, 2, "Exclude")
        workers = []
        done = QSignalSpy(self.first.analysis_finished)
        with capture_analysis(workers):
            self.first.analyze()
        self.assertEqual(self.first.session.active_request.pattern_count, 1)
        workers[0].run()
        self.wait_for_completion(done)
        self.assertEqual(self.first.session.analysis.pattern_count, 1)
        self.assertEqual(self.first.session.analysis.category_match_counts, {"custom_2": 1})
        self.assertIn("ERROR: first", self.first.results_view.editor.toPlainText())

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
        self.assertEqual(self.second.build_config().context, 5)
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
        self.assertEqual(self.first.results_view._analysis_message.text(), "")

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
        with patch("logreader.workers.analysis_worker.analyze_lines", side_effect=ValueError("bad pattern")):
            workers[1].run()
        self.assertEqual(first_failed.count(), 0)
        self.assertEqual(second_failed.at(0), ["bad pattern"])
        self.assertEqual(self.first.session.phase, AnalysisPhase.ANALYZING)
        self.assertEqual(self.second.session.phase, AnalysisPhase.IDLE)
        self.assertIs(self.first._analysis_worker, workers[0])
        self.assertIsNone(self.second._analysis_worker)
        self.assertFalse(self.second._analysis_busy_timer.isActive())
        self.assertEqual(self.second.results_view._analysis_message.text(), "Analysis failed")

        done = QSignalSpy(self.first.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)

    def test_reanalysis_hides_stale_results_without_rebuilding_or_losing_source_and_bookmarks(self):
        page = self.first
        view = page.results_view
        page.show()
        workers = []
        with capture_analysis(workers):
            page.analyze()
        done = QSignalSpy(page.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)
        editor, document, model = view.editor, view.editor.document(), view.model
        source_lines, snapshot = view.source_view.lines, view._snapshot_id
        location = model.location(0)
        self.assertTrue(view.bookmarks.add(location, "Keep"))
        view._search_input.setText("first")
        view.search_results()
        wait_for_search(view)
        editor.selectAll()

        with capture_analysis(workers):
            page.analyze()
        self.assertIs(view.editor, editor)
        self.assertIs(view.editor.document(), document)
        self.assertIs(view.model, model)
        self.assertFalse(view.results_ready)
        self.assertTrue(view.surface.isVisible())
        self.assertIs(view._view_stack.currentWidget(), view.surface)
        self.assertEqual(view._analysis_message.text(), "")
        self.assertEqual(view.loading_status, "")
        self.assertFalse(view._search_input.isEnabled())
        self.assertTrue(view._search_count_label.isHidden())
        self.assertFalse(view.loader.timer.isActive())
        self.assertFalse(view.bookmarks.strip.isTabEnabled(0))
        self.assertFalse(view.show_result_location(location))
        wait_until(lambda: view._analysis_message.text() == "Analyzing...")
        self.assertTrue(view.surface.isHidden())
        self.assertIs(view._view_stack.currentWidget(), view._analysis_message)
        self.assertEqual(view._analysis_message.text(), "Analyzing...")
        with patch.object(editor, "go_to_search_result") as navigate, patch.object(editor, "copy") as copy:
            view.find_next()
            QTest.keyClick(view._analysis_message, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        navigate.assert_not_called()
        copy.assert_not_called()

        view.set_source_active(True)
        wait_source(view)
        self.assertIs(view.source_view.lines, source_lines)
        self.assertEqual(view._snapshot_id, snapshot)
        self.assertTrue(view._search_input.isEnabled())
        self.assertTrue(view.bookmarks.strip.isTabEnabled(0))
        view.set_source_active(False)
        self.assertIs(view._view_stack.currentWidget(), view._analysis_message)
        self.assertEqual(view._analysis_message.text(), "Analyzing...")
        self.assertFalse(view.loader.timer.isActive())

        done = QSignalSpy(page.analysis_finished)
        workers[1].run()
        self.wait_for_completion(done)
        self.assertTrue(view.results_ready)
        self.assertTrue(view._analysis_message.isHidden())
        self.assertIs(view._view_stack.currentWidget(), view.surface)
        self.assertEqual(view._search_input.text(), "first")
        self.assertTrue(view._search_input.isEnabled())
        self.assertEqual(view.bookmarks.items[location.source].name, "Keep")
        self.assertTrue(view.bookmarks.strip.isTabEnabled(0))
        self.assertIs(view.source_view.lines, source_lines)

    def test_fast_analysis_clears_delay_before_deferred_rendering_and_tab_switch(self):
        page = self.first
        view = page.results_view
        workers = []
        with capture_analysis(workers):
            page.analyze()
        done = QSignalSpy(page.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)
        previous = view.surface
        with capture_analysis(workers):
            page.analyze()
        self.assertIs(view._view_stack.currentWidget(), previous)
        page.set_render_active(False)
        workers[1].run()
        self.assertEqual(page.session.phase, AnalysisPhase.RENDERING)
        self.assertFalse(page._analysis_busy_timer.isActive())
        self.assertEqual(page.results_view._analysis_message.text(), "")
        self.assertIs(view._view_stack.currentWidget(), previous)
        page._show_analysis_busy()
        self.assertFalse(page.busy_visible)
        self.assertEqual(page.results_view._analysis_message.text(), "")
        with patch.object(QThreadPool, "start") as start:
            page.set_render_active(True)
        self.assertFalse(page._analysis_busy_timer.isActive())
        self.assertEqual(page.results_view._analysis_message.text(), "")
        done = QSignalSpy(page.analysis_finished)
        start.call_args.args[0].run()
        self.wait_for_completion(done)
        self.assertTrue(page.results_view.results_ready)
        self.assertIs(view._view_stack.currentWidget(), view.surface)
        self.assertIsNot(view.surface, previous)

    def test_queued_message_changes_to_analyzing_without_another_delay(self):
        page = self.first
        view = page.results_view
        with patch.object(page._scheduler.analysis, "submit"):
            page.analyze()
        worker = page._analysis_worker
        self.assertTrue(page.analysis_queued)
        self.assertIs(view._view_stack.currentWidget(), view.surface)
        wait_until(lambda: view._analysis_message.text() == "Queued")
        self.assertEqual(view._analysis_message.text(), "Queued")
        self.assertIs(view._view_stack.currentWidget(), view._analysis_message)
        page._analysis_started(worker.request_id)
        self.assertEqual(view._analysis_message.text(), "Analyzing...")
        self.assertFalse(page._analysis_busy_timer.isActive())
        done = QSignalSpy(page.analysis_finished)
        worker.run()
        self.wait_for_completion(done)
        self.assertTrue(view.results_ready)

    def test_failed_reanalysis_stays_empty_and_retry_replaces_message(self):
        page = self.first
        view = page.results_view
        workers = []
        with capture_analysis(workers):
            page.analyze()
        done = QSignalSpy(page.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)
        old_editor = view.editor
        with capture_analysis(workers):
            page.analyze()
        page._show_analysis_busy()
        with patch("logreader.workers.analysis_worker.analyze_lines", side_effect=ValueError("bad pattern")):
            workers[1].run()
        self.assertEqual(page.session.phase, AnalysisPhase.IDLE)
        self.assertFalse(page._analysis_busy_timer.isActive())
        self.assertEqual(view._analysis_message.text(), "Analysis failed")
        self.assertFalse(view.results_ready)
        self.assertIs(view.editor, old_editor)
        self.assertIs(view._view_stack.currentWidget(), view._analysis_message)

        with capture_analysis(workers):
            page.analyze()
        self.assertEqual(view._analysis_message.text(), "")
        workers[1].signals.failed.emit(workers[1].request_id, "late failure")
        self.assertEqual(view._analysis_message.text(), "")
        done = QSignalSpy(page.analysis_finished)
        workers[2].run()
        self.wait_for_completion(done)
        self.assertTrue(view.results_ready)
        self.assertTrue(view._analysis_message.isHidden())
