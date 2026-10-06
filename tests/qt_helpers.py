"""Event-loop helpers for tests that need a loaded document or held analysis."""

from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtTest import QTest

from logreader.document_session import LoadPhase
from logreader.workers.load_worker import LoadWorker
from logreader.workers.work_queue import WorkQueue


def wait_for_load(page):
    for _ in range(500):
        if page.session.load_phase is not LoadPhase.LOADING and not any(
            isinstance(worker, LoadWorker) for worker in page._workers.values()
        ):
            return
        QTest.qWait(10)
    raise AssertionError("File loading did not finish")


@contextmanager
def capture_analysis(workers):
    submit = WorkQueue.submit

    def dispatch(queue, worker):
        if isinstance(worker, LoadWorker):
            submit(queue, worker)
        else:
            worker.signals.started.emit(worker.request_id)
            workers.append(worker)

    with patch.object(WorkQueue, "submit", new=dispatch):
        yield


def wait_for_search(widget):
    from logreader.ui.results.results_view import ResultsView
    views = [widget] if isinstance(widget, ResultsView) else widget.findChildren(ResultsView)
    for _ in range(1000):
        if all(not view.is_searching and not view._visible_timer.isActive()
               and view.editor.navigation.pending is None
               for view in views):
            return
        QTest.qWait(5)
    raise AssertionError("Results search did not finish")


def wait_for_render(view):
    for _ in range(2000):
        if not view.is_rendering:
            return
        QTest.qWait(5)
    raise AssertionError("Results did not finish loading")


def wait_for_navigation(view):
    for _ in range(2000):
        QTest.qWait(2)
        if view.editor.navigation.pending is None:
            return
    raise AssertionError("Destination did not become ready")


def retire_results():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def render_results(view, lines, *, complete=True):
    from logreader.config import LogreaderConfig
    from logreader.core import analyze_lines
    config = LogreaderConfig(context=0, combined_view=True, enabled_patterns=(), regex_patterns=(".*",))
    view.window().show()
    QCoreApplication.processEvents()
    lines = tuple(lines)
    view.set_source(lines, len(lines))
    if not complete:
        def hold_background():
            view.loader.background = False
        view.results_prepared.connect(hold_background)
    view.start_rendering(1, "test.log", analyze_lines(lines, config.search_patterns(), combined=True), config)
    if complete:
        wait_for_render(view)
    else:
        for _ in range(2000):
            if view.results_ready and view._renderer is None:
                break
            QTest.qWait(2)
        else:
            raise AssertionError("Results were not prepared")
        view.results_prepared.disconnect(hold_background)
    return view.editor
