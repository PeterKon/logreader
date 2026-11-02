"""Background file reading, decoding, and splitting for a document."""

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..cancellation import AnalysisCancelled, CancellationToken
from ..file_loader import DEFAULT_MAX_LINES_SCANNED, load_log


class LoadWorkerSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)
    started = Signal(int)


class LoadWorker(QRunnable):
    def __init__(
        self, request_id: int, source_path: Path,
        max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED, *, include_error_path: bool = True,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.source_path: Path | None = source_path
        self.max_lines_scanned = max_lines_scanned
        self.include_error_path = include_error_path
        self.cancellation = CancellationToken()
        self.signals = LoadWorkerSignals()

    def cancel(self) -> None:
        self.cancellation.cancel()

    def discard(self) -> None:
        """Release queued work without opening the file."""
        self.cancel()
        self.source_path = None
        self.signals.finished.emit(self.request_id)

    @Slot()
    def run(self) -> None:
        try:
            self.cancellation.check()
            loaded = load_log(
                self.source_path, max_lines_scanned=self.max_lines_scanned,
                cancellation=self.cancellation,
            )
            self.cancellation.check()
            self.signals.completed.emit(self.request_id, loaded)
        except AnalysisCancelled:
            pass
        except Exception as error:
            if not self.cancellation.is_cancelled:
                message = str(error)
                if not self.include_error_path and isinstance(error, OSError) and error.strerror:
                    message = error.strerror
                self.signals.failed.emit(self.request_id, message)
        finally:
            self.source_path = None
            self.signals.finished.emit(self.request_id)
