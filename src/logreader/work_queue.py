"""GUI-owned FIFO queues with independent load and analysis concurrency limits."""

from collections import deque

from PySide6.QtCore import QObject, QThreadPool, QTimer, Slot

from .analysis_worker import AnalysisWorker
from .load_worker import LoadWorker

Worker = AnalysisWorker | LoadWorker


class WorkQueue(QObject):
    """Start at most one worker; cancelled active work keeps its slot until done."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._pending: deque[Worker] = deque()
        self._active: Worker | None = None
        self._stopped = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_next)

    def submit(self, worker: Worker) -> None:
        if self._stopped:
            worker.discard()
            return
        self._pending.append(worker)
        self._start_next()

    @Slot()
    def _start_next(self) -> None:
        if self._stopped or self._active is not None or not self._pending:
            return
        worker = self._pending.popleft()
        self._active = worker
        worker.signals.finished.connect(self._finished)
        worker.signals.started.emit(worker.request_id)
        QThreadPool.globalInstance().start(worker)

    @Slot(int)
    def _finished(self, _request_id: int) -> None:
        worker = self._active
        if worker is None or self.sender() is not worker.signals:
            return
        worker.signals.finished.disconnect(self._finished)
        self._active = None
        if not self._stopped:
            self._timer.start(0)

    def cancel(self, worker: Worker) -> None:
        worker.cancel()
        if worker in self._pending:
            self._pending.remove(worker)
            worker.discard()

    def shutdown(self) -> None:
        self._stopped = True
        self._timer.stop()
        for worker in tuple(self._pending):
            self.cancel(worker)
        if self._active is not None:
            self._active.cancel()


class WorkScheduler(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.loading = WorkQueue(self)
        self.analysis = WorkQueue(self)

    def cancel(self, worker: AnalysisWorker | LoadWorker) -> None:
        queue = self.loading if isinstance(worker, LoadWorker) else self.analysis
        queue.cancel(worker)

    def shutdown(self) -> None:
        self.loading.shutdown()
        self.analysis.shutdown()
