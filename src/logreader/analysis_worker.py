"""Qt worker that runs Logreader analysis outside the GUI thread."""

from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .core import SearchPattern, analyze_lines


class AnalysisWorkerSignals(QObject):
    """Cross-thread completion signals for one analysis request."""

    completed = Signal(int, object, float)
    failed = Signal(int, str)


class AnalysisWorker(QRunnable):
    """Run the pure log analysis engine outside Qt's GUI thread."""

    def __init__(
        self,
        request_id: int,
        lines: tuple[str, ...],
        patterns: tuple[SearchPattern, ...],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.lines = lines
        self.patterns = patterns
        self.signals = AnalysisWorkerSignals()

    @Slot()
    def run(self) -> None:
        started = perf_counter()
        try:
            analysis = analyze_lines(self.lines, self.patterns)
        except Exception as error:  # Keep worker failures from stranding the UI.
            self.signals.failed.emit(self.request_id, str(error))
            return

        self.signals.completed.emit(
            self.request_id,
            analysis,
            perf_counter() - started,
        )
