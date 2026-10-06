import gc
import os
import unittest
import weakref
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from logreader.workers.analysis_worker import AnalysisWorker, InteractiveAnalysisToken
from logreader.cancellation import AnalysisCancelled
from logreader.config import LogreaderConfig
from logreader.core import SearchPattern, analyze_lines
from logreader.ui.results.result_preparation import PreparationWorker
from logreader.ui.results.results_view import ResultsView
from logreader.ui.document_page import DocumentPage
from logreader.file_loader import LoadedLog
from logreader.workers.work_queue import WorkScheduler
from qt_helpers import render_results, retire_results
from pathlib import Path


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

    def test_cancelled_preparation_releases_source_even_if_wrapper_is_held(self):
        source = SourceText("ERROR: prepared input")
        reference = weakref.ref(source)
        config = LogreaderConfig(enabled_patterns=("error_colon",))
        analysis = analyze_lines((source,), config.search_patterns())
        worker = PreparationWorker(1, analysis, "snapshot", config)
        del source, analysis
        worker.cancel()
        worker.run()
        self.assertIsNone(worker.analysis)
        self.assertIsNone(reference())

    def test_retired_editor_releases_model_with_wrapper_cycle_and_collection_disabled(self):
        view = ResultsView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        source = SourceText("ERROR: retained result")
        reference = weakref.ref(source)
        render_results(view, (source,))
        old = view.editor
        old.wrapper_cycle = old
        model = weakref.ref(view.model)
        del source
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            view.reset_for_loaded_file("replacement")
            self.assertTrue(view.has_retiring_results)
            retire_results()
            self.assertFalse(view.has_retiring_results)
            self.assertIsNone(old.presentation)
            self.assertIsNone(model())
            self.assertIsNone(reference())
        finally:
            if was_enabled:
                gc.enable()

    def test_reload_waits_for_native_retirement_before_submitting_reader(self):
        page = DocumentPage()
        self.addCleanup(page.dispose)
        source = SourceText("ERROR: replaced source")
        reference = weakref.ref(source)
        page.stage_loaded_log(Path("old.log"), LoadedLog((source,), "UTF-8"))
        render_results(page.results_view, (source,))
        del source
        observed = []
        with patch.object(page._scheduler.loading, "submit", side_effect=lambda worker: observed.append(reference())):
            page.load_file(Path("replacement.log"))
            self.assertEqual(observed, [])
            self.assertIsNotNone(page._waiting_load)
            retire_results()
            self.assertEqual(observed, [None])
            self.assertIsNone(page._waiting_load)
            # The captured worker was deliberately never submitted.
            page._load_worker.discard()

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
        with patch("logreader.workers.analysis_worker.monotonic", return_value=1.0), patch(
            "logreader.workers.analysis_worker.sleep"
        ) as pause:
            for _ in range(100):
                token.check()
            pause.assert_called_once_with(.001)
        with patch("logreader.workers.analysis_worker.monotonic", return_value=2.0), patch(
            "logreader.workers.analysis_worker.sleep", side_effect=lambda _seconds: token.cancel()
        ):
            with self.assertRaises(AnalysisCancelled):
                token.check()
