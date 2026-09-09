import os
import tempfile
import unittest
from pathlib import Path
from threading import Event, Lock
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QThreadPool, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QSpinBox

    from qt_helpers import wait_for_load
    from logreader.core import analyze_lines
    from logreader.document_session import LoadPhase
    from logreader.file_loader import LoadedLog
    from logreader.qt_app import LogreaderWindow
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class MultiFileWorkTests(unittest.TestCase):
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

    def log(self, name, content=None):
        path = self.root / name
        path.write_text(content or f"ERROR: {name}\n", encoding="utf-8")
        return path

    def wait_until(self, predicate):
        for _ in range(500):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail("Work did not reach the expected state")

    def test_picker_batch_preserves_order_first_selection_and_individual_failures(self):
        existing, first, last = [self.log(name) for name in ("existing.log", "first.log", "last.log")]
        bad = self.root / "bad.log"
        bad.write_bytes(b"\xff\xfe\x00")
        missing = self.root / "missing.log"
        self.window.load_file(existing)
        original = self.window._document
        wait_for_load(original)
        requested = [first, existing, bad, first, missing, last]
        with patch("logreader.qt_app.QFileDialog.getOpenFileNames",
                   return_value=([str(path) for path in requested], "")):
            self.window.open_file()
        pages = [self.window._pages.widget(i) for i in range(self.window._tabs.count())]
        self.assertEqual([page.session.path for page in pages], [existing, first, bad, missing, last])
        self.assertIs(self.window._document, pages[1])
        for page in pages:
            wait_for_load(page)
            self.assertIsNone(page.session.analysis)
        self.assertEqual(pages[2].session.load_phase, LoadPhase.FAILED)
        self.assertEqual(pages[3].session.load_phase, LoadPhase.FAILED)
        self.assertEqual(pages[4].session.load_phase, LoadPhase.LOADED)
        self.assertIs(self.window._document, pages[1])
        self.window.load_files([existing, last, first])
        self.assertIs(self.window._document, original)
        self.assertEqual(self.window._tabs.count(), 5)

    def test_multiple_file_drops_work_over_controls_and_results(self):
        first, second = self.log("first.log"), self.log("second.log")
        self.window.load_file(self.log("initial.log"))
        wait_for_load(self.window._document)
        self.window.show()
        self.app.processEvents()
        for target in (self.window._open_button, self.window._document.results_view.editor.viewport()):
            mime = QMimeData()
            mime.setUrls([
                QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second)),
                QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(self.root)),
                QUrl("https://example.com/remote.log"),
            ])
            enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(target, enter)
            self.assertTrue(enter.isAccepted())
            self.assertEqual(self.window._drop_overlay.text(), "Drop 3 files")
            self.app.sendEvent(target, drop)
            self.assertTrue(drop.isAccepted())
            self.assertEqual(self.window._tabs.count(), 3)
            self.assertEqual(self.window._document.session.path, first)
        for index in range(self.window._tabs.count()):
            wait_for_load(self.window._pages.widget(index))

    def test_one_load_and_one_analysis_run_concurrently_and_cancelled_queued_work_never_starts(self):
        paths = [self.log(name) for name in ("a.log", "b.log", "c.log")]
        self.window.load_files(paths)
        pages = [self.window._pages.widget(i) for i in range(3)]
        for page in pages:
            wait_for_load(page)
        load_started, analysis_started = Event(), Event()
        release_load, release_analysis = Event(), Event()
        lock = Lock()
        active = {"load": 0, "analysis": 0}
        maximum = {"load": 0, "analysis": 0}
        calls = {"load": [], "analysis": []}

        def enter(kind, name):
            with lock:
                calls[kind].append(name)
                active[kind] += 1
                maximum[kind] = max(maximum[kind], active[kind])

        def leave(kind):
            with lock:
                active[kind] -= 1

        def load(path, *, cancellation=None):
            enter("load", path.name)
            try:
                if path.name == "load-first.log":
                    load_started.set()
                    if not release_load.wait(5):
                        raise TimeoutError("Load not released")
                return LoadedLog((f"ERROR: {path.name}",), "UTF-8")
            finally:
                leave("load")

        def analyze(lines, patterns, *, combined=False, cancellation=None):
            enter("analysis", lines[0])
            try:
                if "a.log" in lines[0]:
                    analysis_started.set()
                    if not release_analysis.wait(5):
                        raise TimeoutError("Analysis not released")
                return analyze_lines(lines, patterns, combined=combined, cancellation=cancellation)
            finally:
                leave("analysis")

        with patch("logreader.load_worker.load_log", side_effect=load), patch(
            "logreader.analysis_worker.analyze_lines", side_effect=analyze
        ):
            try:
                for page in pages:
                    self.window._select_document(page)
                    self.window.analyze_current()
                self.assertTrue(analysis_started.wait(2))
                queued_analysis = pages[1]._analysis_worker
                self.assertTrue(pages[1].analysis_queued)
                self.assertTrue(pages[2].analysis_queued)
                pages[2].findChild(QSpinBox, "contextSpin").setValue(8)
                self.assertEqual(self.window._analyze_button.text(), "Queued…")
                load_paths = [self.root / name for name in ("load-first.log", "load-skip.log", "load-last.log")]
                self.window.load_files(load_paths)
                load_pages = [self.window._pages.widget(i) for i in range(3, 6)]
                self.assertTrue(load_started.wait(2))
                self.assertEqual(active, {"load": 1, "analysis": 1})
                self.assertTrue(load_pages[1].load_queued)
                self.assertTrue(load_pages[2].load_queued)
                queued_load = load_pages[1]._load_worker
                self.window.load_files([load_paths[0], load_paths[1]])
                self.assertEqual(self.window._tabs.count(), 6)
                self.window.close_tab(self.window._pages.indexOf(pages[1]))
                self.window.close_tab(self.window._pages.indexOf(load_pages[1]))
                self.assertTrue(queued_analysis.cancellation.is_cancelled)
                self.assertEqual(queued_analysis.lines, ())
                self.assertEqual(queued_analysis.patterns, ())
                self.assertTrue(queued_load.cancellation.is_cancelled)
                self.assertIsNone(queued_load.source_path)
                self.assertEqual(len(self.window._scheduler.analysis._pending), 1)
                self.assertEqual(len(self.window._scheduler.loading._pending), 1)
                release_analysis.set()
                release_load.set()
                wait_for_load(load_pages[2])
                self.wait_until(lambda: self.window._scheduler.analysis._active is None
                                and not self.window._scheduler.analysis._pending
                                and pages[2].session.analysis is not None)
                self.assertEqual(calls["analysis"], ["ERROR: a.log", "ERROR: c.log"])
                self.assertEqual(calls["load"], ["load-first.log", "load-last.log"])
                self.assertEqual(maximum, {"load": 1, "analysis": 1})
                self.assertIsNone(pages[0].results_view._renderer)
                self.assertIsNone(pages[2].results_view._renderer)
                self.assertIsNotNone(pages[0].session.analysis)
                self.assertIsNotNone(pages[2].session.analysis)
                self.assertEqual(pages[2].session.analysis_config.context, 3)
                self.assertEqual(pages[2].build_config().context, 8)
            finally:
                release_analysis.set()
                release_load.set()
                QThreadPool.globalInstance().waitForDone(5000)

    def test_cancelled_active_load_keeps_its_slot_until_finished(self):
        workers = []
        with patch.object(QThreadPool, "start", side_effect=workers.append):
            self.window.load_files([self.log("first.log"), self.log("second.log")])
            self.assertEqual(len(workers), 1)
            first_worker = workers[0]
            self.window.close_tab(0)
            self.assertIs(self.window._scheduler.loading._active, first_worker)
            self.assertEqual(len(workers), 1)
            first_worker.run()
            self.wait_until(lambda: len(workers) == 2)
            workers[1].run()
        self.assertEqual(self.window._document.session.load_phase, LoadPhase.LOADED)
        self.assertEqual(self.window._document.session.path.name, "second.log")

    def test_shutdown_discards_pending_jobs_without_starting_them(self):
        workers = []
        with patch.object(QThreadPool, "start", side_effect=workers.append):
            self.window.load_files([self.log("first.log"), self.log("second.log")])
            queued = self.window._pages.widget(1)._load_worker
            self.window.close()
            self.assertFalse(self.window._scheduler.loading._pending)
            self.assertTrue(queued.cancellation.is_cancelled)
            self.assertIsNone(queued.source_path)
            workers[0].run()
            self.app.processEvents()
            self.assertEqual(len(workers), 1)
            self.assertIsNone(self.window._scheduler.loading._active)

    def test_hidden_rendering_is_deferred_and_paused_time_is_not_counted(self):
        self.window.load_files([self.log("first.log"), self.log("second.log")])
        first, second = self.window._pages.widget(0), self.window._pages.widget(1)
        wait_for_load(first)
        wait_for_load(second)
        workers = []
        with patch.object(QThreadPool, "start", side_effect=workers.append):
            self.window.analyze_current()
            self.window._select_document(second)
            self.window.analyze_current()
            self.assertEqual(len(workers), 1)
            workers[0].run()
            self.assertIsNone(first.results_view._renderer)
            self.wait_until(lambda: len(workers) == 2)
            workers[1].run()
        second_renderer = second.results_view._renderer
        self.window._select_document(first)
        self.assertFalse(second_renderer._timer.isActive())
        done = QSignalSpy(first.analysis_finished)
        self.wait_until(lambda: done.count() == 1)
        second_done = QSignalSpy(second.analysis_finished)
        self.window._select_document(second)
        self.wait_until(lambda: second_done.count() == 1)

        # Four clock readings: start, pause, resume, finish. The 100-second
        # inactive interval must not inflate the rendering duration.
        view = first.results_view
        rendered = QSignalSpy(view.rendering_completed)
        with patch("logreader.results_view.perf_counter", side_effect=(10.0, 11.0, 111.0, 113.0)):
            view.start_rendering(99, "timing", first.session.analysis, first.session.analysis_config)
            renderer = view._renderer
            renderer.set_paused(True)
            renderer.set_paused(False)
            with patch("logreader.results_view.INCREMENTAL_RENDER_BATCH_MS", 100000):
                renderer._render_next_batch()
        self.assertEqual(rendered.at(0), [99, 3.0])
