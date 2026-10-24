import gc
from pathlib import Path
import unittest
import weakref
from unittest.mock import patch

from source_test_case import SourceViewCase
import test_source_integration as integration
from test_document_retention import SourceText
from PySide6.QtTest import QTest
from shiboken6 import isValid
from logreader.document_session import LoadPhase
from logreader.file_loader import LoadedLog
from logreader.ui.results.results_model import SourceLocation
from qt_helpers import retire_results, wait_for_load


class SourceLifecycleTests(SourceViewCase):
    wait = integration.SourceIntegrationTests.wait
    open_source = integration.SourceIntegrationTests.open_source
    wait_source_search = integration.SourceIntegrationTests.wait_source_search
    search = integration.SourceIntegrationTests.search

    def test_scan_limit_and_results_readiness_are_independent_of_source_insertion(self):
        self.path.write_text("".join(f"ERROR: line {i}\n" for i in range(1, 12001)), encoding="utf-8")
        self.page.load_file(self.path, max_lines_scanned=5000)
        self.view.set_source_active(True)
        wait_for_load(self.page)
        self.settle_source()
        snapshot, editor = self.source.lines, self.source.editor
        identity = self.page.session.snapshot_id
        self.assertEqual((len(snapshot), self.source.first_line), (5000, 7001))
        self.assertTrue(self.source.is_ready)
        self.assertFalse(self.source.loader.done)
        self.assertLess(editor.ranges.loaded_count, 128)
        self.source.go_to_line(10000)
        self.settle_source()
        reading = editor.top_point(), editor.anchor, editor.caret
        self.page.filter_panel._limit_spin.setValue(1000)
        with patch("logreader.workers.load_worker.load_log", side_effect=AssertionError("Unneeded reload")):
            self.page.analyze()
            self.wait(lambda: not self.page.session.is_busy)
        self.assertTrue(self.view.source_active)
        self.assertIs(self.source.editor, editor)
        self.assertIs(self.source.lines, snapshot)
        self.assertEqual(self.page.session.snapshot_id, identity)
        self.assertEqual(self.page.session.analysis.line_count, 1000)
        self.assertEqual((editor.top_point(), editor.anchor, editor.caret), reading)
        self.assertTrue(self.source.is_ready)
        self.assertFalse(self.source.loader.done)
        self.assertEqual(self.window._loading_status.text(), "")
        self.assertEqual(self.source.activity_label.text(), "")
        self.assertTrue(self.window._analyze_button.isEnabled())

        # Results still owns its loading status when selected.
        self.view.loading_status = "Loading results: 25%"
        self.view.loading_status_changed.emit(self.view.loading_status)
        self.assertEqual(self.window._loading_status.text(), "")
        self.view.set_source_active(False)
        self.assertEqual(self.window._loading_status.text(), self.view.loading_status)
        self.view.set_source_active(True)
        self.assertEqual(self.window._loading_status.text(), "")

        self.page.filter_panel._limit_spin.setValue(9000)
        self.assertIs(self.source.lines, snapshot)
        self.page.analyze()
        self.wait(lambda: self.page.session.analysis is not None and not self.page.session.is_busy)
        self.settle_source()
        self.assertIsNot(self.source.editor, editor)
        self.assertIsNot(self.source.lines, snapshot)
        self.assertNotEqual(self.page.session.snapshot_id, identity)
        self.assertEqual((len(self.source.lines), self.source.first_line), (9000, 3001))
        self.assertEqual(self.page.session.analysis.line_count, 9000)
        self.assertIs(self.source.lines, self.page.session.lines)
        self.assertTrue(self.source.is_ready)
        self.assertFalse(isValid(editor))

    def test_source_native_retirement_precedes_replacement_reader_even_without_gc(self):
        line = SourceText("old snapshot " * 10000)
        reference = weakref.ref(line)
        old = self.open_source((line,))
        old.wrapper_cycle = old
        model = weakref.ref(old.presentation)
        old_loader = self.source.loader
        del line
        observed = []
        submit = self.page._scheduler.loading.submit

        def dispatch(worker):
            observed.append((isValid(old), reference(), model()))
            submit(worker)

        enabled = gc.isenabled()
        gc.disable()
        try:
            with patch.object(self.page._scheduler.loading, "submit", side_effect=dispatch):
                self.page.load_file(self.path)
                self.assertEqual(observed, [])
                self.assertTrue(old_loader.cancelled)
                self.assertIsNotNone(self.page._waiting_load)
                self.assertTrue(self.view.has_retiring_results)
                wait_for_load(self.page)
                self.assertEqual(observed, [(False, None, None)])
            self.assertIsNone(old.presentation)
            self.assertFalse(self.view.has_retiring_results)
            self.settle_source()
            self.assertTrue(self.source.is_ready)
        finally:
            if enabled:
                gc.enable()

    def test_smaller_and_empty_replacements_cancel_search_navigation_and_markers(self):
        old = self.open_source(f"needle row {i}" for i in range(20000))
        self.search("needle")
        self.view.bookmarks.add(SourceLocation(self.page.session.snapshot_id, 19000), "Distant")
        self.source.loader.interval_ms = 1000
        self.source.go_to_line(19000)
        self.assertIsNotNone(old.navigation.pending)
        self.source.set_query("row")
        self.source.search()
        self.assertTrue(self.source.is_searching)
        old_loader = self.source.loader
        self.stage(("replacement",), total=7)
        self.assertTrue(old_loader.cancelled)
        self.assertIsNone(old.navigation.pending)
        self.settle_source()
        retire_results()
        self.assertFalse(isValid(old))
        self.assertIsNone(old.presentation)
        self.assertEqual(self.source.editor._block(0).text(), "replacement")
        self.assertEqual(self.source.first_line, 7)
        self.assertFalse(self.source.is_searching)
        self.assertEqual(len(self.source.matches), 0)
        self.assertEqual(list(self.source.global_scroll.match_rows), [])
        self.assertEqual(list(self.source.global_scroll.bookmark_rows), [])
        self.assertEqual(self.source.editor.extraSelections(), [])
        self.assertIsNone(self.source.target_line)
        self.assertFalse(self.view.bookmarks.items)
        self.stage(())
        self.settle_source()
        self.assertTrue(self.source.is_ready)
        self.assertEqual(self.source.editor.toPlainText(), "")
        self.assertEqual(self.source.editor.ranges.loaded_count, 0)
        self.assertIsNone(self.source.editor.navigation.pending)
        self.assertFalse(self.source.loader.timer.isActive())
        self.assertFalse(self.source._search_timer.isActive())
        self.assertEqual(self.source.activity_label.text(), "")

    def test_hidden_tabs_pause_work_resume_reading_and_close_during_search(self):
        line = SourceText("needle " * 100)
        reference = weakref.ref(line)
        old = self.open_source((line,) * 100000)
        del line
        other_path = Path(self.temp.name) / "other.log"
        other_path.write_text("Other document", encoding="utf-8")
        self.window.load_file(other_path)
        other = self.window._document
        wait_for_load(other)
        self.window._select_document(self.page)
        self.settle_source()
        self.source.go_to_line(200)
        self.settle_source()
        saved = old.top_point(), old.anchor, old.caret
        self.source.loader.interval_ms = 1000
        self.source.go_to_line(90000)
        self.assertIsNotNone(old.navigation.pending)
        self.source.set_query("needle")
        self.source.search()
        self.window._select_document(other)
        self.assertIsNone(old.navigation.pending)
        self.assertFalse(self.source.loader.timer.isActive())
        self.assertFalse(self.source._search_timer.isActive())
        count = old.insertion_count
        pending_count = len(self.source._pending)
        QTest.qWait(100)
        self.assertEqual(old.insertion_count, count)
        self.assertEqual(len(self.source._pending), pending_count)
        self.source.loader.interval_ms = 0
        self.window._select_document(self.page)
        self.settle_source()
        self.assertEqual((old.top_point(), old.anchor, old.caret), saved)
        self.assertTrue(self.source.is_searching)
        self.assertTrue(self.source._search_timer.isActive())
        self.assertTrue(self.source.is_ready)
        self.window.close_tab(self.window._pages.indexOf(self.page))
        self.assertFalse(self.source.is_searching)
        self.assertFalse(self.source._search_timer.isActive())
        self.assertFalse(self.source.loader.timer.isActive())
        self.assertEqual(self.source.lines, ())
        self.assertEqual(self.page.session.lines, ())
        self.assertFalse(self.page.session.is_busy)
        retire_results()
        self.assertFalse(isValid(old))
        self.assertIsNone(old.presentation)
        self.assertIsNone(reference())
        self.assertIs(self.window._document, other)
        self.assertFalse(other.session.is_busy)
        self.assertTrue(self.window._analyze_button.isEnabled())

    def test_failed_load_clears_source_and_analyze_retries(self):
        old = self.open_source(f"old row {i}" for i in range(10000))
        self.source.go_to_line(9000)
        self.source.set_query("old")
        self.source.search()
        missing = Path(self.temp.name) / "missing.log"
        self.page.filter_panel._limit_spin.setValue(17)
        self.page.load_file(missing, max_lines_scanned=17)
        wait_for_load(self.page)
        self.assertEqual(self.page.session.load_phase, LoadPhase.FAILED)
        self.assertFalse(self.page.session.is_busy)
        self.assertFalse(self.source.is_ready)
        self.assertEqual(self.source.lines, ())
        self.assertEqual(self.source.editor.toPlainText(), "")
        self.assertFalse(self.source.is_searching)
        self.assertIsNone(self.source.editor.navigation.pending)
        self.assertFalse(isValid(old))
        self.assertIn("Press Analyze to retry", self.source.editor.placeholderText())
        self.assertTrue(self.window._analyze_button.isEnabled())
        missing.write_text("ERROR: recovered\n", encoding="utf-8")
        self.page.analyze()
        self.wait(lambda: self.page.session.analysis is not None and not self.page.session.is_busy)
        self.settle_source()
        self.assertTrue(self.source.is_ready)
        self.assertEqual(self.source.lines, ("ERROR: recovered",))
        self.assertEqual(self.page.filter_panel._limit_spin.value(), 17)

    def test_superseding_and_closing_reloads_discards_stale_work(self):
        old = self.open_source(f"old {i}" for i in range(1000))
        submitted = []
        with patch.object(self.page._scheduler.loading, "submit", side_effect=submitted.append):
            self.page.load_file(Path(self.temp.name) / "superseded.log")
            first = self.page._waiting_load
            self.page.load_file(self.path)
            second = self.page._waiting_load
            self.assertIsNot(first, second)
            self.assertTrue(first.cancellation.is_cancelled)
            self.assertEqual(submitted, [])
            retire_results()
            self.assertFalse(isValid(old))
            self.assertEqual(submitted, [second])
            first.signals.completed.emit(first.request_id, LoadedLog(("stale",), "UTF-8"))
            self.assertEqual(self.source.lines, ())
            self.window.close_tab(self.window._pages.indexOf(self.page))
            self.assertTrue(second.cancellation.is_cancelled)
            second.signals.completed.emit(second.request_id, LoadedLog(("late",), "UTF-8"))
            second.signals.failed.emit(second.request_id, "late failure")
            self.assertEqual(self.source.lines, ())
            self.assertFalse(self.page.session.is_busy)
            second.run()
        retire_results()
        self.assertFalse(isValid(self.page))
        self.assertIsNone(self.window._document)


if __name__ == "__main__":
    unittest.main()
