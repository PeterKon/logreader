import os
import tempfile
import unittest
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QThreadPool, QTimer
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QLineEdit
    from shiboken6 import isValid

    from qt_helpers import wait_for_load
    from logreader.document_page import DocumentPage
    from logreader.document_session import LoadPhase
    from logreader.file_loader import LoadedLog, _iter_decoded_lines
    from logreader.qt_app import LogreaderWindow
    from logreader.work_queue import WorkQueue
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class LoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.window = LogreaderWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_for(self, spy):
        for _ in range(500):
            self.app.processEvents()
            if spy.count():
                return
            QTest.qWait(10)
        self.fail("Expected signal was not delivered")

    def test_read_decode_and_split_run_off_gui_while_tabs_remain_usable(self):
        ready_path = self.root / "ready.log"
        ready_path.write_text("ERROR: ready\n", encoding="utf-8")
        self.window.load_file(ready_path)
        ready = self.window._document
        wait_for_load(ready)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        main_thread = get_ident()
        stages = []
        started, release = Event(), Event()

        slow_path = self.root / "slow.log"
        slow_path.write_bytes(b"ERROR: loaded\n")

        def decoded_lines(stream, codec, cancellation):
            stages.append(("read/decode/split", get_ident()))
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test read was not released")
            yield from _iter_decoded_lines(stream, codec, cancellation)

        with patch("logreader.file_loader._iter_decoded_lines", side_effect=decoded_lines):
            try:
                self.assertTrue(self.window.load_file(self.root / "slow.log"))
                loading = self.window._document
                self.assertTrue(started.wait(2))
                self.assertEqual(loading.session.load_phase, LoadPhase.LOADING)
                self.assertFalse(loading.session.has_document)
                self.assertFalse(self.window._analyze_button.isEnabled())
                self.assertEqual(self.window._analyze_button.text(), "Loading…")
                self.assertIn("Loading", self.window._tabs.tabText(1))
                self.window.analyze_current()
                self.assertIsNone(loading._analysis_worker)
                self.assertTrue(self.window.load_file(self.root / "folder" / ".." / "slow.log"))
                self.assertEqual(self.window._tabs.count(), 2)
                self.assertIs(self.window._document, loading)
                self.window._select_document(ready)
                self.assertTrue(self.window._analyze_button.isEnabled())
                draft = ready.findChild(QLineEdit, "customPattern")
                draft.setText("keep editing")
                draft.selectAll()
                draft.setFocus()
                ticked = []
                QTimer.singleShot(0, lambda: ticked.append(True))
                self.app.processEvents()
                self.assertTrue(ticked)
                status = self.window.statusBar().currentMessage()
                release.set()
                wait_for_load(loading)
                self.assertEqual(loading.session.lines, ("ERROR: loaded",))
                self.assertEqual(loading.session.encoding, "UTF-8")
                self.assertIsNone(loading.session.analysis)
                self.assertIs(self.app.focusWidget(), draft)
                self.assertEqual(draft.selectedText(), "keep editing")
                self.assertEqual(self.window.statusBar().currentMessage(), status)
                self.assertEqual(self.window._tabs.tabText(1), "slow.log")
                self.window._select_document(loading)
                self.assertTrue(self.window._analyze_button.isEnabled())
                self.assertEqual(self.window._analyze_button.text(), "&Analyze")
            finally:
                release.set()
                QThreadPool.globalInstance().waitForDone(5000)
        self.assertEqual([stage for stage, _ in stages], ["read/decode/split"])
        self.assertTrue(all(thread != main_thread for _, thread in stages))

    def test_loads_preserve_encoding_policy_and_empty_file_readiness(self):
        for codec, label in (
            ("utf-8", "UTF-8"), ("utf-8-sig", "UTF-8 with BOM"),
            ("utf-16", "UTF-16 LE"), ("utf-32", "UTF-32 LE"),
            ("cp1252", "Windows-1252"),
        ):
            with self.subTest(codec=codec):
                path = self.root / f"{codec}.log"
                path.write_bytes("ERROR: café\r\nafter".encode(codec))
                self.window.load_file(path)
                page = self.window._document
                wait_for_load(page)
                self.assertEqual(page.session.lines, ("ERROR: café", "after"))
                self.assertEqual(page.session.encoding, label)
        path = self.root / "empty.log"
        path.write_bytes(b"")
        self.window.load_file(path)
        wait_for_load(self.window._document)
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window._document.session.lines, ())

    def test_out_of_order_success_and_failure_stay_in_owning_tabs_and_retry(self):
        first_path = self.root / "first.log"
        first_path.write_bytes(b"ERROR: first")
        second_path = self.root / "second.log"
        second_path.write_bytes(b"\xff\xfe\x00")  # Invalid BOM-marked UTF-16.
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.window.load_file(first_path)
            first = self.window._document
            self.window.load_file(second_path)
            second = self.window._document
        self.assertEqual(workers[0].request_id, workers[1].request_id)
        self.window._select_document(first)
        status = self.window.statusBar().currentMessage()
        with patch("logreader.qt_app.QMessageBox.critical") as dialog:
            workers[1].run()
            dialog.assert_not_called()
        self.assertEqual(second.session.load_phase, LoadPhase.FAILED)
        self.assertIn("Invalid UTF-16", second.session.load_error)
        self.assertEqual(self.window.statusBar().currentMessage(), status)
        self.window._select_document(second)
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertIn("Failed", self.window._tabs.tabText(1))
        self.assertEqual(second.results_view.editor.placeholderText(), "")
        self.assertIn(second.session.load_error, second.status_message)
        failed_status = self.window.statusBar().currentMessage()
        workers[0].run()
        self.assertEqual(first.session.load_phase, LoadPhase.LOADED)
        self.assertEqual(self.window.statusBar().currentMessage(), failed_status)
        second_path.write_bytes(b"ERROR: retry")
        self.window.load_file(second_path)
        self.assertIs(self.window._document, second)
        wait_for_load(second)
        self.assertEqual(self.window._tabs.count(), 2)
        self.assertEqual(second.session.lines, ("ERROR: retry",))
        self.assertIsNone(second.session.load_error)
        self.assertTrue(self.window._analyze_button.isEnabled())

    def test_close_or_shutdown_pending_load_releases_resources_and_ignores_late_result(self):
        for shutdown in (False, True):
            with self.subTest(shutdown=shutdown):
                started, release = Event(), Event()

                def blocked(path, *, max_lines_scanned=1_000_000, cancellation=None):
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("Test load was not released")
                    # Deliberately return despite cancellation to test the worker guard.
                    return LoadedLog(("old contents",), "UTF-8")

                with patch("logreader.load_worker.load_log", side_effect=blocked):
                    try:
                        path = self.root / f"pending-{shutdown}.log"
                        self.window.load_file(path)
                        page = self.window._document
                        worker = page._load_worker
                        destroyed = QSignalSpy(page.destroyed)
                        completed = QSignalSpy(worker.signals.completed)
                        self.assertTrue(started.wait(2))
                        if shutdown:
                            self.window.close()
                        else:
                            self.window.close_tab(0)
                        self.assertEqual(self.window._tabs.count(), 0)
                        self.assertTrue(worker.cancellation.is_cancelled)
                        self.assertEqual(page.session.lines, ())
                        self.assertIsNone(page.session.active_load_id)
                        self.assertIsNone(page._load_worker)
                        self.assertIs(self.window._workspace.currentWidget(), self.window._empty_page)
                        worker.signals.completed.emit(worker.request_id, LoadedLog(("late",), "UTF-8"))
                        worker.signals.failed.emit(worker.request_id, "late failure")
                        self.assertEqual(page.session.lines, ())
                        before = completed.count()
                        release.set()
                        self.wait_for(destroyed)
                        self.assertEqual(completed.count(), before)
                        self.assertIsNone(worker.source_path)
                        self.assertFalse(isValid(page))
                    finally:
                        release.set()
                        QThreadPool.globalInstance().waitForDone(5000)

    def test_superseded_generation_and_reopened_path_reject_old_load_callbacks(self):
        page = DocumentPage()
        workers = []
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            page.load_file(self.root / "old.log")
            page.load_file(self.root / "new.log")
        old, current = workers
        self.assertTrue(old.cancellation.is_cancelled)
        self.assertNotEqual(old.request_id, current.request_id)
        old.signals.completed.emit(old.request_id, LoadedLog(("stale",), "UTF-8"))
        old.signals.failed.emit(old.request_id, "stale failure")
        self.assertEqual(page.session.load_phase, LoadPhase.LOADING)
        self.assertEqual(page.session.lines, ())
        current.signals.completed.emit(current.request_id, LoadedLog(("current",), "UTF-8"))
        self.assertEqual(page.session.lines, ("current",))
        page.dispose()
        old.run()
        current.run()

        workers = []
        path = self.root / "same.log"
        with patch.object(WorkQueue, "submit", side_effect=workers.append):
            self.window.load_file(path)
            old_page = self.window._document
            self.window.close_tab(0)
            self.window.load_file(path)
            new_page = self.window._document
        self.assertEqual(workers[0].request_id, workers[1].request_id)
        workers[0].signals.completed.emit(workers[0].request_id, LoadedLog(("wrong",), "UTF-8"))
        self.assertIs(self.window._document, new_page)
        self.assertIsNot(new_page, old_page)
        self.assertEqual(new_page.session.load_phase, LoadPhase.LOADING)
        self.assertEqual(new_page.session.lines, ())
        self.window.close_tab(0)
        for worker in workers:
            worker.run()
