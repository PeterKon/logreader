import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import capture_analysis, wait_for_load
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QTabBar
    from shiboken6 import isValid

    from logreader.core import analyze_lines
    from logreader.qt_app import APP_VERSION, LogreaderWindow
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TabClosingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.window = LogreaderWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def open_log(self, name):
        path = Path(self.directory.name) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ERROR: example\n" * 100, encoding="utf-8")
        self.assertTrue(self.window.load_file(path))
        wait_for_load(self.window._document)
        return self.window._document

    def wait_for(self, spy):
        for _ in range(500):
            self.app.processEvents()
            if spy.count():
                return
            QTest.qWait(10)
        self.fail("Worker did not finish")

    def test_close_cross_targets_its_tab_after_indexes_shift_and_last_returns_empty(self):
        first = self.open_log("one/server.log")
        second = self.open_log("two/server.log")
        third = self.open_log("third.log")
        second_path = second.session.path
        third_button = self.window._tabs.tabButton(2, QTabBar.ButtonPosition.RightSide)
        first_button = self.window._tabs.tabButton(0, QTabBar.ButtonPosition.RightSide)
        self.assertEqual(first_button.accessibleName(), "Close server.log")
        self.assertEqual(first_button.text(), "")  # Cross is painted, not font-dependent.
        first_button.click()
        self.assertIs(self.window._document, third)
        self.assertEqual(self.window._tabs.tabText(0), "server.log")
        third_button.click()
        self.assertIs(self.window._document, second)
        self.assertEqual(self.window._tabs.count(), 1)
        self.window.show()
        self.window.activateWindow()
        second.results_view.set_maximized(True)
        self.app.processEvents()
        QTest.keyClick(self.window, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window._tabs.count(), 0)
        self.assertIsNone(self.window._document)
        self.assertEqual(self.window._documents_by_path, {})
        self.assertTrue(self.window._empty_page.isVisible())
        self.assertFalse(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.windowTitle(), APP_VERSION)
        self.assertEqual(self.window._path_label.text(), "No file selected")
        QTest.keyClick(self.window, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.window.load_file(second_path))
        self.assertIsNot(self.window._document, second)
        self.assertEqual(self.window._tabs.count(), 1)

    def test_closing_active_or_inactive_running_worker_cancels_and_ignores_late_signals(self):
        for active in (False, True):
            with self.subTest(active=active):
                first = self.open_log(f"{active}-first.log")
                second = self.open_log(f"{active}-second.log")
                self.window._select_document(first)
                started, release = Event(), Event()

                def blocked(lines, patterns, *, combined=False, cancellation=None):
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("Test worker was not released")
                    return analyze_lines(lines, patterns, combined=combined, cancellation=cancellation)

                with patch("logreader.analysis_worker.analyze_lines", side_effect=blocked):
                    try:
                        self.window.analyze_current()
                        worker = first._analysis_worker
                        finished = QSignalSpy(worker.signals.finished)
                        destroyed = QSignalSpy(first.destroyed)
                        completed = QSignalSpy(worker.signals.completed)
                        self.assertTrue(started.wait(2))
                        if not active:
                            self.window._select_document(second)
                        self.window.close_tab(self.window._pages.indexOf(first))
                        self.assertIs(self.window._document, second)
                        self.assertTrue(worker.cancellation.is_cancelled)
                        self.assertEqual(first.session.lines, ())
                        self.assertIsNone(first.session.active_request)
                        self.assertIsNone(first.session.analysis)
                        self.assertIsNone(first.results_view._renderer)
                        self.assertFalse(first._analysis_busy_timer.isActive())
                        self.assertIn(worker.request_id, first._workers)
                        status = self.window.statusBar().currentMessage()
                        with patch("logreader.qt_app.QMessageBox.warning") as warning:
                            worker.signals.completed.emit(worker.request_id, None, 0.1)
                            worker.signals.failed.emit(worker.request_id, "late failure")
                            self.assertEqual(self.window.statusBar().currentMessage(), status)
                            warning.assert_not_called()
                        completed_before = completed.count()
                        release.set()
                        self.wait_for(finished)
                        self.assertEqual(completed.count(), completed_before)
                        self.assertEqual(worker.lines, ())
                        self.assertEqual(worker.patterns, ())
                        # Worker signals are queued to the GUI thread; observing
                        # finished in a spy does not mean its slot has run yet.
                        self.wait_for(destroyed)
                        self.assertFalse(isValid(first))
                        # Qt disconnects the deleted receiver; later signals are harmless.
                        worker.signals.failed.emit(worker.request_id, "after deletion")
                    finally:
                        release.set()
                        QThreadPool.globalInstance().waitForDone(5000)

    def test_close_during_rendering_stops_batches_for_active_and_inactive_pages(self):
        for active in (False, True):
            with self.subTest(active=active):
                first = self.open_log(f"render-{active}-first.log")
                workers = []
                with capture_analysis(workers):
                    self.window.analyze_current()
                workers[0].run()
                renderer = first.results_view._renderer
                self.assertTrue(renderer._timer.isActive())
                with patch("logreader.results_view.INCREMENTAL_RENDER_BATCH_MS", 0):
                    renderer._render_next_batch()
                renderer._timer.stop()
                if active:
                    self.window.close_tab(self.window._pages.indexOf(first))
                else:
                    other = self.open_log(f"render-{active}-other.log")
                    self.window.close_tab(self.window._pages.indexOf(first))
                    self.assertIs(self.window._document, other)
                self.assertTrue(renderer._cancelled)
                self.assertFalse(renderer._timer.isActive())
                self.assertIsNone(first.results_view._renderer)
                status = self.window.statusBar().currentMessage()
                first.results_view.rendering_completed.emit(workers[0].request_id, 1.0)
                first.results_view.rendering_failed.emit(workers[0].request_id, "late render failure")
                self.assertEqual(self.window.statusBar().currentMessage(), status)
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertFalse(isValid(first))

    def test_window_close_and_application_quit_cancel_all_work(self):
        for quit_signal in (False, True):
            with self.subTest(quit_signal=quit_signal):
                if quit_signal:
                    self.window.deleteLater()
                    self.window = LogreaderWindow()
                first = self.open_log(f"shutdown-{quit_signal}-first.log")
                workers = []
                with capture_analysis(workers):
                    self.window.analyze_current()
                    second = self.open_log(f"shutdown-{quit_signal}-second.log")
                    self.window.analyze_current()
                workers[1].run()
                renderer = second.results_view._renderer
                if quit_signal:
                    self.app.aboutToQuit.emit()
                else:
                    self.window.close()
                self.assertEqual(self.window._tabs.count(), 0)
                self.assertTrue(workers[0].cancellation.is_cancelled)
                self.assertTrue(renderer._cancelled)
                self.assertFalse(renderer._timer.isActive())
                self.assertEqual(first.session.lines, ())
                self.assertEqual(second.session.lines, ())
                done = QSignalSpy(workers[0].signals.finished)
                with patch("logreader.analysis_worker.analyze_lines", wraps=analyze_lines):
                    workers[0].run()
                self.assertEqual(done.count(), 1)
                self.assertEqual(workers[0].lines, ())
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertFalse(isValid(first))
                self.assertFalse(isValid(second))
