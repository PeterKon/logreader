import gc
import os
import unittest
import weakref
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from logreader.analysis_worker import AnalysisWorker, InteractiveAnalysisToken
from logreader.cancellation import AnalysisCancelled
from logreader.config import LogreaderConfig
from logreader.core import SearchPattern, analyze_lines
from logreader.results_view import IncrementalAnalysisRenderer
from logreader.work_queue import WorkScheduler


class SourceText(str):
    """A weak-referenceable source line used to detect retained input."""


class DocumentRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    def test_cancelled_renderer_releases_analysis_before_deferred_deletion(self):
        editor = QPlainTextEdit()
        self.addCleanup(editor.deleteLater)
        source = SourceText("ERROR: retained input")
        reference = weakref.ref(source)
        config = LogreaderConfig(enabled_patterns=("error_colon",))
        analysis = analyze_lines((source,), config.search_patterns())
        renderer = IncrementalAnalysisRenderer(1, editor, "sample", analysis, config)
        renderer.start()
        # Suspend the operations generator while it still owns the analysis.
        next(renderer._operations)
        del source, analysis
        self.assertIsNotNone(reference())
        renderer.cancel()
        self.assertIsNone(reference())
        renderer.deleteLater()

    def test_completed_and_cancelled_workers_release_source_even_if_wrapper_is_held(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                source = SourceText("ERROR: worker input")
                reference = weakref.ref(source)
                worker = AnalysisWorker(1, (source,), (SearchPattern("error", "ERROR:"),))
                del source
                if cancel:
                    worker.cancel()
                worker.run()
                self.assertEqual(worker.lines, ())
                self.assertEqual(worker.patterns, ())
                self.assertIsNone(reference())

    def test_queued_cancellation_and_shutdown_release_inputs_without_running(self):
        scheduler = WorkScheduler(self.app)
        self.addCleanup(scheduler.deleteLater)
        active = AnalysisWorker(1, ("active",), ())
        sources = [SourceText("queued one"), SourceText("queued two")]
        references = [weakref.ref(source) for source in sources]
        queued = [AnalysisWorker(i + 2, (source,), ()) for i, source in enumerate(sources)]
        sources.clear()
        with patch.object(QThreadPool, "start") as start:
            scheduler.analysis.submit(active)
            for worker in queued:
                scheduler.analysis.submit(worker)
            scheduler.cancel(queued[0])
            self.assertIsNone(references[0]())
            scheduler.shutdown()
            self.assertIsNone(references[1]())
            self.assertEqual(start.call_count, 1)
            self.assertFalse(scheduler.analysis._pending)
            active.run()
        self.assertIsNone(scheduler.analysis._active)

    def test_interactive_token_yields_at_deadline_and_rechecks_cancellation(self):
        token = InteractiveAnalysisToken()
        with patch("logreader.analysis_worker.monotonic", return_value=1.0), patch(
            "logreader.analysis_worker.sleep"
        ) as pause:
            for _ in range(100):
                token.check()
            pause.assert_called_once_with(.001)
        with patch("logreader.analysis_worker.monotonic", return_value=2.0), patch(
            "logreader.analysis_worker.sleep", side_effect=lambda _seconds: token.cancel()
        ):
            with self.assertRaises(AnalysisCancelled):
                token.check()
