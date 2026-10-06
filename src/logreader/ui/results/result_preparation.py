"""Prepare result indexes cooperatively outside the GUI thread."""
from dataclasses import dataclass
from time import perf_counter
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from logreader.cancellation import AnalysisCancelled, checked
from logreader.workers.analysis_worker import InteractiveAnalysisToken
from .results_model import ResultsModel
from .result_presentation import PresentationModel

@dataclass(slots=True)
class PreparedResults:
    logical: ResultsModel
    presentation: PresentationModel
    model_ms: float
    presentation_ms: float


class PreparationSignals(QObject):
    started = Signal(int)
    phase = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)


class PreparationWorker(QRunnable):
    def __init__(self, request_id, analysis, snapshot_id, config, *, header_operations=()):
        super().__init__()
        self.request_id = request_id
        self.analysis, self.snapshot_id, self.config = analysis, snapshot_id, config
        self.header_operations = header_operations
        self.signals = PreparationSignals()
        self.cancellation = InteractiveAnalysisToken()

    def cancel(self):
        self.cancellation.cancel()

    def discard(self):
        self.cancel()
        self.analysis = self.config = None
        self.signals.finished.emit(self.request_id)

    @Slot()
    def run(self):
        try:
            self.cancellation.check()
            started = perf_counter()
            logical = ResultsModel(self.analysis, self.snapshot_id)
            for _ in checked(logical.prepare(), self.cancellation):
                pass
            self.cancellation.check()
            model_ms = (perf_counter() - started) * 1000
            self.signals.phase.emit(self.request_id, "indexing")
            started = perf_counter()
            presentation = PresentationModel(logical, self.config, defer=True,
                                             header_operations=self.header_operations)
            for _ in checked(presentation.prepare(), self.cancellation):
                pass
            self.cancellation.check()
            result = PreparedResults(logical, presentation, model_ms, (perf_counter() - started) * 1000)
            self.signals.completed.emit(self.request_id, result)
        except AnalysisCancelled:
            pass
        except Exception as error:
            if not self.cancellation.is_cancelled:
                self.signals.failed.emit(self.request_id, str(error))
        finally:
            self.analysis = self.config = None
            self.signals.finished.emit(self.request_id)
