"""Qt worker that runs Logreader analysis outside the GUI thread."""

from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .core import SearchPattern, analyze_lines
from .cancellation import AnalysisCancelled, CancellationToken


class AnalysisWorkerSignals(QObject):
    """Cross-thread completion signals for one analysis request."""

    completed = Signal(int, object, float)
    failed = Signal(int, str)
    finished = Signal(int)
    started = Signal(int)


class AnalysisWorker(QRunnable):
    """Run the pure log analysis engine outside Qt's GUI thread."""

    def __init__(
        self,
        request_id: int,
        lines: tuple[str, ...],
        patterns: tuple[SearchPattern, ...],
        combined: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.lines = lines
        self.patterns = patterns
        self.combined = combined
        self.signals = AnalysisWorkerSignals()
        self.cancellation = CancellationToken()

    def cancel(self) -> None:
        self.cancellation.cancel()

    def discard(self) -> None:
        """Release queued work that has never entered the thread pool."""
        self.cancel()
        self.lines = ()
        self.patterns = ()
        self.signals.finished.emit(self.request_id)

    @Slot()
    def run(self) -> None:
        started = perf_counter()
        try:
            self.cancellation.check()
            analysis = analyze_lines(
                self.lines,
                self.patterns,
                combined=self.combined,
                cancellation=self.cancellation,
            )
            self.cancellation.check()
            self.signals.completed.emit(
                self.request_id,
                analysis,
                perf_counter() - started,
            )
        except AnalysisCancelled:
            pass
        except Exception as error:  # Keep worker failures from stranding the UI.
            if not self.cancellation.is_cancelled:
                self.signals.failed.emit(self.request_id, str(error))
        finally:
            self.lines = ()
            self.patterns = ()
            self.signals.finished.emit(self.request_id)
