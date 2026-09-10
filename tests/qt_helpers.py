"""Event-loop helpers for tests that need a loaded document or held analysis."""

from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest

from logreader.document_session import LoadPhase
from logreader.load_worker import LoadWorker
from logreader.work_queue import WorkQueue


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
    from logreader.results_view import ResultsView
    views = [widget] if isinstance(widget, ResultsView) else widget.findChildren(ResultsView)
    for _ in range(1000):
        if all(not view.is_searching and not view._search_highlighter._highlight_timer.isActive()
               for view in views):
            return
        QTest.qWait(5)
    raise AssertionError("Results search did not finish")
