"""Qt worker that runs Logreader analysis outside the GUI thread."""

from __future__ import annotations

from time import monotonic, perf_counter, sleep

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .core import SearchPattern, analyze_lines
from .cancellation import AnalysisCancelled, CancellationToken


class InteractiveAnalysisToken(CancellationToken):
    """Periodically give Qt's GUI thread time to finish a render batch.

    Python analysis and PySide calls compete for the GIL. A short worker-only
    pause avoids repeated GIL handoffs stretching a GUI batch across hundreds
    of milliseconds. Pure engine callers keep the ordinary cancellation token.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_yield = 0.0

    def check(self) -> None:
        super().check()
        now = monotonic()
        if now >= self._next_yield:
            sleep(0.001)
            self._next_yield = monotonic() + 0.008
            super().check()


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
        self.cancellation = InteractiveAnalysisToken()

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
