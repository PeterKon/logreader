"""Event-loop helpers for tests that need a loaded document or held analysis."""

from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest

from logreader.document_session import LoadPhase
from logreader.load_worker import LoadWorker


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
    start = QThreadPool.start

    def dispatch(pool, worker):
        if isinstance(worker, LoadWorker):
            start(pool, worker)
        else:
            workers.append(worker)

    with patch.object(QThreadPool, "start", new=dispatch):
        yield
