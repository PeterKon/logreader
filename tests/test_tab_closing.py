import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import capture_analysis, wait_for_load
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QThreadPool, Qt
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QTabBar
    from shiboken6 import isValid

    from logreader.core import analyze_lines
    from logreader.ui.qt_app import DocumentTabMenu, LogreaderWindow
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

    def tab_menu(self, index, choose=None, before_choice=None):
        self.window.show()
        self.app.processEvents()
        tabs = self.window._tabs
        point = tabs.tabRect(index).center() if index >= 0 else QPoint(tabs.width() - 1, 5)
        active = self.window._document
        seen = []

        def execute(menu, position):
            self.assertIs(self.window._document, active)
            self.assertEqual(position, tabs.mapToGlobal(point))
            seen.extend((action.text(), action.isEnabled()) for action in menu.actions())
            if before_choice:
                before_choice()
            return menu.actions()[choose] if choose is not None else None

        with patch.object(DocumentTabMenu, "exec", new=execute):
            QTest.mouseClick(tabs, Qt.MouseButton.RightButton, pos=point)
            self.assertIs(self.window._document, active)
            # QTest mouse events do not synthesize the platform context-menu event.
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, tabs.mapToGlobal(point))
            QApplication.sendEvent(tabs, event)
        return seen

    def test_tab_menu_targets_inactive_tab_and_preserves_selection_on_dismissal(self):
        first = self.open_log("first.log")
        second = self.open_log("second.log")
        self.assertEqual(self.tab_menu(0), [
            ("Close tab", True), ("Close all other tabs", True),
            ("Close all tabs to the right", True),
        ])
        self.assertIs(self.window._document, second)
        self.tab_menu(0, choose=0)
        self.assertEqual(self.window._tabs.count(), 1)
        self.assertIs(self.window._document, second)
        self.assertNotIn(first, self.window._documents_by_path.values())
        self.tab_menu(0, choose=0)
        self.assertEqual(self.window._tabs.count(), 0)
        self.assertIsNone(self.window._document)
        self.assertTrue(self.window._empty_page.isVisible())

    def test_tab_menu_disabled_actions_and_empty_space(self):
        self.open_log("first.log")
        self.assertEqual(self.tab_menu(0), [
            ("Close tab", True), ("Close all other tabs", False),
            ("Close all tabs to the right", False),
        ])
        self.open_log("second.log")
        self.assertEqual(self.tab_menu(1)[1:], [
            ("Close all other tabs", True), ("Close all tabs to the right", False),
        ])
        self.assertEqual(self.tab_menu(-1), [])
        self.assertEqual(self.window._tabs.count(), 2)

    def test_tab_menu_bulk_closing_keeps_correct_tabs_and_cancels_work(self):
        for action in (1, 2):
            with self.subTest(action=action):
                pages = [self.open_log(f"{action}-{i}.log") for i in range(4)]
                workers = []
                with capture_analysis(workers):
                    for page in pages:
                        self.window._select_document(page)
                        self.window.analyze_current()
                self.tab_menu(1, choose=action)
                kept = [pages[1]] if action == 1 else pages[:2]
                self.assertEqual(list(self.window._documents_by_path.values()), kept)
                self.assertEqual(self.window._tabs.count(), len(kept))
                self.assertIs(self.window._document, pages[1])
                for page, worker in zip(pages, workers):
                    self.assertEqual(worker.cancellation.is_cancelled, page not in kept)
                while self.window._tabs.count():
                    self.window.close_tab(self.window._tabs.count() - 1)
                for worker in workers:
                    worker.run()

    def test_tab_menu_actions_accept_only_left_mouse_clicks(self):
        menu = DocumentTabMenu(self.window.title_menus)
        self.addCleanup(menu.close)
        action = menu.addAction("Close tab")
        triggered = QSignalSpy(action.triggered)
        menu.popup(QPoint(100, 100))
        self.app.processEvents()
        point = menu.actionGeometry(action).center()
        QTest.mouseMove(menu, point)
        # Releasing the right-click that opened the menu must also be harmless.
        QTest.mouseRelease(menu, Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(triggered.count(), 0)
        QTest.mouseClick(menu, Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(triggered.count(), 0)
        self.assertTrue(menu.isVisible())
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(triggered.count(), 1)

    def test_tab_menu_resolves_target_after_tabs_change_while_open(self):
        self.open_log("first.log")
        self.open_log("second.log")
        third = self.open_log("third.log")
        self.tab_menu(1, choose=0, before_choice=lambda: self.window.close_tab(0))
        self.assertEqual(self.window._tabs.count(), 1)
        self.assertIs(self.window._document, third)

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
        self.assertTrue(self.window._empty_logo.isVisible())
        self.assertTrue(self.window._empty_version_label.isVisible())
        self.assertFalse(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.windowTitle(), "Logreader")
        self.assertFalse(self.window._analyze_button.isVisible())
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

                def blocked(lines, patterns, *, combined=False, line_offset=0, cancellation=None):
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("Test worker was not released")
                    return analyze_lines(lines, patterns, combined=combined, line_offset=line_offset, cancellation=cancellation)

                with patch("logreader.workers.analysis_worker.analyze_lines", side_effect=blocked):
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
                        with patch("logreader.ui.qt_app.QMessageBox.warning") as warning:
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
                preparation = []
                with patch.object(QThreadPool, "start", side_effect=preparation.append):
                    workers[0].run()
                renderer = first.results_view._renderer
                self.assertFalse(renderer.cancellation.is_cancelled)
                if active:
                    self.window.close_tab(self.window._pages.indexOf(first))
                else:
                    other = self.open_log(f"render-{active}-other.log")
                    self.window.close_tab(self.window._pages.indexOf(first))
                    self.assertIs(self.window._document, other)
                self.assertTrue(renderer.cancellation.is_cancelled)
                self.assertFalse(first.results_view.loader.timer.isActive())
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
                self.assertTrue(renderer.cancellation.is_cancelled)
                self.assertFalse(first.results_view.loader.timer.isActive())
                self.assertEqual(first.session.lines, ())
                self.assertEqual(second.session.lines, ())
                done = QSignalSpy(workers[0].signals.finished)
                with patch("logreader.workers.analysis_worker.analyze_lines", wraps=analyze_lines):
                    workers[0].run()
                self.assertEqual(done.count(), 1)
                self.assertEqual(workers[0].lines, ())
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertFalse(isValid(first))
                self.assertFalse(isValid(second))
