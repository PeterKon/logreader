"""Document-owned controls, results, and analysis lifecycle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .analysis_worker import AnalysisWorker
from .config import LogreaderConfig
from .core import AnalysisResult
from .document_session import AnalysisPhase, DocumentSession
from .file_loader import LoadedLog
from .filter_panel import FilterPanel, VisibleCheckBox, VisibleSpinBox
from .results_view import ResultsView


ANALYSIS_BUSY_DELAY_MS = 1_000


class DocumentPage(QWidget):
    """Own one document independently of the window presenting its status."""

    analysis_finished = Signal()
    analysis_failed = Signal(str)
    status_changed = Signal(str)
    busy_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("centralWidget")
        self.session = DocumentSession()
        self.status_message = "Ready: Open a log file to begin"
        self.busy_visible = False
        self._analysis_worker: AnalysisWorker | None = None
        self._workers: dict[int, AnalysisWorker] = {}
        self._disposed = False
        self._analysis_pool = QThreadPool.globalInstance()
        self._analysis_busy_timer = QTimer(self)
        self._analysis_busy_timer.setSingleShot(True)
        self._analysis_busy_timer.setInterval(ANALYSIS_BUSY_DELAY_MS)
        self._analysis_busy_timer.timeout.connect(self._show_analysis_busy)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.controls_container = QWidget(self)
        self.controls_container.setObjectName("controlsContainer")
        self.controls_layout = QVBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(12, 12, 12, 10)
        self.controls_layout.setSpacing(10)
        self.filter_panel = FilterPanel()
        self.controls_layout.addWidget(self.filter_panel)
        root_layout.addWidget(self.controls_container)
        self.results_view = ResultsView(
            self,
            checkbox_factory=VisibleCheckBox,
            spinbox_factory=VisibleSpinBox,
        )
        self.results_view.rendering_completed.connect(self._complete_rendering)
        self.results_view.rendering_failed.connect(self._fail_analysis)
        self.results_view.maximized_changed.connect(self._set_results_maximized)
        root_layout.addWidget(self.results_view, 1)

    @Slot(bool)
    def _set_results_maximized(self, maximized: bool) -> None:
        self.controls_container.setVisible(not maximized)
        self.filter_panel.setVisible(not maximized)

    def _set_status(self, message: str) -> None:
        self.status_message = message
        self.status_changed.emit(message)

    def build_config(self) -> LogreaderConfig:
        """Snapshot the current document's committed filter settings."""
        return self.filter_panel.build_config()

    def stage_loaded_log(self, path: Path, loaded: LoadedLog) -> None:
        """Replace this document, invalidating its previous work."""
        if self._disposed:
            return
        if self._analysis_worker is not None:
            self._analysis_worker.cancel()
        was_busy = self.session.is_busy
        self.session.stage_loaded_log(path, loaded)
        if was_busy:
            self._finish_analysis_request()
        self.results_view.reset_for_loaded_file(path.name)
        self.busy_changed.emit()
        self._set_status(
            f"{len(loaded.lines):,} lines loaded as {loaded.encoding}  •  "
            "press Analyze to begin"
        )

    def analyze(self) -> None:
        """Analyze the loaded file using the current controls."""

        if self._disposed or not self.session.has_document or self.session.is_busy:
            return

        try:
            config = self.build_config()
            patterns = config.search_patterns()
        except ValueError as error:
            self._set_status(f"Analysis could not be completed: {error}")
            self.analysis_failed.emit(str(error))
            return

        request = self.session.begin_analysis(
            config, sum(not pattern.exclude for pattern in patterns),
        )
        worker = AnalysisWorker(
            request.request_id,
            self.session.lines,
            patterns,
            config.combined_view,
        )
        worker.signals.completed.connect(self._complete_analysis)
        worker.signals.failed.connect(self._fail_analysis)
        worker.signals.finished.connect(self._worker_finished)
        self._workers[request.request_id] = worker
        self._analysis_worker = worker
        self._set_analysis_busy(True)
        self._analysis_pool.start(worker)

    def dispose(self) -> None:
        """Stop UI work now; retain running workers until their final signal."""
        if self._disposed:
            return
        self._disposed = True
        self.session.clear()
        for worker in self._workers.values():
            worker.cancel()
        self._finish_analysis_request()
        self.results_view.reset_for_loaded_file("")
        self.hide()
        if not self._workers:
            self.deleteLater()

    @Slot(int)
    def _worker_finished(self, request_id: int) -> None:
        self._workers.pop(request_id, None)
        if self._disposed and not self._workers:
            self.deleteLater()

    @Slot(int, object, float)
    def _complete_analysis(
        self,
        request_id: int,
        analysis: AnalysisResult,
        analysis_seconds: float,
    ) -> None:
        """Render the current worker result back on Qt's GUI thread."""

        if not self.session.begin_rendering(
            request_id,
            analysis,
            analysis_seconds,
        ):
            return

        request = self.session.active_request
        if request is None:
            self._finish_analysis_request()
            return

        self._analysis_worker = None
        self.results_view.start_rendering(
            request_id,
            str(request.source_path),
            analysis,
            request.config,
        )
        if self.busy_visible:
            self._set_status(
                f"Rendering results for {request.source_path.name}…"
            )

    @Slot(int, float)
    def _complete_rendering(
        self,
        request_id: int,
        rendering_seconds: float,
    ) -> None:
        """Finalize timings and status after all render batches complete."""

        if not self.session.complete_rendering(
            request_id,
            rendering_seconds,
        ):
            return

        analysis = self.session.analysis
        analysis_seconds = self.session.analysis_seconds
        if analysis is None or analysis_seconds is None:
            self._finish_analysis_request()
            return

        self.results_view.prepend_performance_timings(
            analysis_seconds,
            rendering_seconds,
        )

        match_count = sum(
            result.match_count for result in analysis.categories.values()
        )
        self._finish_analysis_request()
        self._set_status(
            f"{analysis.line_count:,} lines  •  {match_count:,} matches  •  "
            f"{analysis.pattern_count} active patterns  •  "
            f"{self.session.encoding or 'unknown encoding'}"
        )
        self.analysis_finished.emit()

    @Slot(int, str)
    def _fail_analysis(self, request_id: int, message: str) -> None:
        """Restore the interface after a worker-side analysis failure."""

        if not self.session.fail_request(request_id):
            return

        self._finish_analysis_request()
        self._set_status(f"Analysis could not be completed: {message}")
        self.analysis_failed.emit(message)

    def _set_analysis_busy(self, busy: bool) -> None:
        if busy:
            self.busy_visible = False
            self.results_view.focus_editor()
            self.busy_changed.emit()
            self._analysis_busy_timer.start()
            return

        self._analysis_busy_timer.stop()
        self.busy_visible = False
        self.busy_changed.emit()

    @Slot()
    def _show_analysis_busy(self) -> None:
        if not self.session.is_busy:
            return

        self.busy_visible = True
        self.busy_changed.emit()
        request = self.session.active_request
        source_name = request.source_path.name if request is not None else "log"
        if self.session.phase is AnalysisPhase.RENDERING:
            self._set_status(
                f"Rendering results for {source_name}…"
            )
        else:
            pattern_count = request.pattern_count if request is not None else 0
            self._set_status(
                f"Analyzing {source_name} with "
                f"{pattern_count} active patterns…"
            )

    def _finish_analysis_request(self) -> None:
        self.results_view.cancel_rendering()
        self._analysis_worker = None
        self._set_analysis_busy(False)
