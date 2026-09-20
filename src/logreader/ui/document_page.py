"""Document-owned controls, results, and analysis lifecycle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..workers.analysis_worker import AnalysisWorker
from ..config import LogreaderConfig
from ..core import AnalysisResult
from ..document_session import AnalysisPhase, DocumentSession
from ..file_loader import DEFAULT_MAX_LINES_SCANNED, LoadedLog
from ..workers.load_worker import LoadWorker
from .filter_panel import FilterPanel, VisibleCheckBox, VisibleSpinBox
from .results.results_view import ResultsView
from ..workers.work_queue import WorkScheduler


ANALYSIS_BUSY_DELAY_MS = 1_000


class DocumentPage(QWidget):
    """Own one document independently of the window presenting its status."""

    analysis_finished = Signal()
    analysis_failed = Signal(str)
    status_changed = Signal(str)
    busy_changed = Signal()
    load_finished = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, scheduler: WorkScheduler | None = None,
        show_performance: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("centralWidget")
        self.session = DocumentSession()
        self.show_performance = show_performance
        self.status_message = "Open a file to begin"
        self.busy_visible = False
        self._analysis_worker: AnalysisWorker | None = None
        self._workers: dict[int, AnalysisWorker | LoadWorker] = {}
        self._load_worker: LoadWorker | None = None
        self._pending_analysis: LogreaderConfig | None = None
        self._disposed = False
        self._bookmark_reset_notice = False
        self._scheduler = scheduler if scheduler is not None else WorkScheduler(self)
        self.load_queued = False
        self.analysis_queued = False
        self._render_active = True
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
        self.results_view.bookmarks_cleared.connect(self._bookmarks_cleared)
        root_layout.addWidget(self.results_view, 1)

    @Slot(bool)
    def _set_results_maximized(self, maximized: bool) -> None:
        self.controls_container.setVisible(not maximized)
        self.filter_panel.setVisible(not maximized)

    def _bookmarks_cleared(self) -> None:
        if not self._disposed:
            self._bookmark_reset_notice = True

    def _set_status(self, message: str) -> None:
        if self._bookmark_reset_notice:
            message += "  •  Bookmarks cleared: file replaced"
        self.status_message = message
        self.status_changed.emit(message)

    def build_config(self) -> LogreaderConfig:
        """Snapshot the current document's committed filter settings."""
        return self.filter_panel.build_config()

    def stage_loaded_log(self, path: Path, loaded: LoadedLog) -> None:
        """Replace this document, invalidating its previous work."""
        if self._disposed:
            return
        self._pending_analysis = None
        if self._analysis_worker is not None:
            self._scheduler.cancel(self._analysis_worker)
        if self._load_worker is not None:
            self._scheduler.cancel(self._load_worker)
            self._load_worker = None
        was_busy = self.session.is_busy
        self.session.stage_loaded_log(path, loaded)
        if was_busy:
            self._finish_analysis_request()
        self._show_loaded_log(path, loaded)

    def _show_loaded_log(self, path: Path, loaded: LoadedLog) -> None:
        self.results_view.reset_for_loaded_file(path.name)
        self.results_view.set_source(
            loaded.lines, loaded.total_line_count, snapshot_id=self.session.snapshot_id,
        )
        self.busy_changed.emit()
        self._set_status(f"Loaded as {loaded.encoding}: {path.name}")
        self._bookmark_reset_notice = False

    def load_file(
        self, path: Path, *,
        max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED,
        analyze_after_load: LogreaderConfig | None = None,
    ) -> None:
        """Start a document-owned load without blocking the GUI thread."""
        if self._disposed:
            return
        self._pending_analysis = analyze_after_load
        for worker in tuple(self._workers.values()):
            self._scheduler.cancel(worker)
        request_id = self.session.begin_loading(path)
        self._finish_analysis_request()
        self.results_view.reset_for_loaded_file(path.name)
        self.results_view.source_view.reset("Loading source…")
        self.load_queued = True
        message = f"Queued to load: {path.name}"
        self._set_status(message)
        worker = LoadWorker(request_id, path, max_lines_scanned)
        worker.signals.started.connect(self._load_started)
        worker.signals.completed.connect(self._complete_load)
        worker.signals.failed.connect(self._fail_load)
        worker.signals.finished.connect(self._worker_finished)
        self._load_worker = worker
        self._workers[request_id] = worker
        self._scheduler.loading.submit(worker)

    @Slot(int)
    def _load_started(self, request_id: int) -> None:
        if self._disposed or self.session.active_load_id != request_id:
            return
        self.load_queued = False
        message = f"Loading {self.session.path.name}…"
        self._set_status(message)
        self.busy_changed.emit()

    @Slot(int, object)
    def _complete_load(self, request_id: int, loaded: LoadedLog) -> None:
        if not self.session.complete_loading(request_id, loaded):
            return
        self._load_worker = None
        self.load_queued = False
        config = self._pending_analysis
        self._pending_analysis = None
        self._show_loaded_log(self.session.path, loaded)
        if config is not None:
            self._start_analysis(config)
        self.load_finished.emit()

    @Slot(int, str)
    def _fail_load(self, request_id: int, message: str) -> None:
        if not self.session.fail_loading(request_id, message):
            return
        self._load_worker = None
        self.load_queued = False
        self._pending_analysis = None
        self._set_status(f"Could not load {self.session.path.name}: {message}. Press Analyze to retry.")
        self._bookmark_reset_notice = False
        self.results_view.reset_for_loaded_file(self.session.path.name)
        self.results_view.source_view.reset(f"Could not load the file: {message}. Press Analyze to retry.")
        self.busy_changed.emit()
        self.load_finished.emit()

    def analyze(self) -> None:
        """Analyze the loaded file using the current controls."""

        if self._disposed or self.session.path is None or self.session.is_busy:
            return

        try:
            config = self.build_config()
            config.search_patterns()  # Validate before discarding the loaded snapshot.
        except ValueError as error:
            self._set_status(f"Analysis failed: {error}")
            self.analysis_failed.emit(str(error))
            return

        if (not self.session.has_document or
                len(self.session.lines) < min(config.max_lines_scanned, self.session.total_line_count)):
            self.load_file(
                self.session.path, max_lines_scanned=config.max_lines_scanned,
                analyze_after_load=config,
            )
            return
        self._start_analysis(config)

    def _start_analysis(self, config: LogreaderConfig) -> None:
        """Analyze the captured settings after any required replacement load."""
        if self._disposed or not self.session.has_document or self.session.is_busy:
            return
        patterns = config.search_patterns()
        request = self.session.begin_analysis(
            config, sum(not pattern.exclude for pattern in patterns),
        )
        lines = self.session.lines[-config.max_lines_scanned:]
        worker = AnalysisWorker(
            request.request_id,
            lines,
            patterns,
            config.combined_view,
            line_offset=self.session.total_line_count - len(lines),
        )
        worker.signals.started.connect(self._analysis_started)
        worker.signals.completed.connect(self._complete_analysis)
        worker.signals.failed.connect(self._fail_analysis)
        worker.signals.finished.connect(self._worker_finished)
        self._workers[request.request_id] = worker
        self._analysis_worker = worker
        self.analysis_queued = True
        self._set_analysis_busy(True)
        self._set_status(f"Queued to analyze: {self.session.path.name}")
        self._scheduler.analysis.submit(worker)

    @Slot(int)
    def _analysis_started(self, request_id: int) -> None:
        request = self.session.active_request
        if self._disposed or request is None or request.request_id != request_id:
            return
        self.analysis_queued = False
        self._analysis_busy_timer.start()
        self._set_status(f"Analyzing: {request.source_path.name}")
        self.busy_changed.emit()

    def set_render_active(self, active: bool) -> None:
        """Only the selected tab consumes GUI rendering batches."""
        if self._render_active == active:
            return
        self._render_active = active
        self._update_rendering_activity()

    def _update_rendering_activity(self) -> None:
        if self.session.phase is not AnalysisPhase.RENDERING:
            return
        if not self._render_active:
            self.results_view.set_rendering_paused(True)
            self._analysis_busy_timer.stop()
            self.busy_visible = False
            self._set_status("Select this tab to finish displaying results")
            self.busy_changed.emit()
        else:
            self._start_or_resume_rendering()

    def _start_or_resume_rendering(self) -> None:
        request = self.session.active_request
        if request is None or self.session.analysis is None or self._disposed:
            return
        if self.results_view.is_rendering:
            self.results_view.set_rendering_paused(False)
        else:
            self.results_view.start_rendering(
                request.request_id, str(request.source_path),
                self.session.analysis, request.config,
            )
        self._analysis_busy_timer.start()
        self._set_status(f"Displaying results: {request.source_path.name}")
        self.busy_changed.emit()

    def dispose(self) -> None:
        """Stop UI work now; retain running workers until their final signal."""
        if self._disposed:
            return
        self._disposed = True
        self._pending_analysis = None
        self.session.clear()
        for worker in tuple(self._workers.values()):
            self._scheduler.cancel(worker)
        self._load_worker = None
        self._finish_analysis_request()
        self.results_view.reset_for_loaded_file("")
        self.results_view.cancel_search()
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
        self.analysis_queued = False
        self._update_rendering_activity()

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

        if self.show_performance:
            self.results_view.prepend_performance_timings(
                analysis_seconds,
                rendering_seconds,
            )

        config = self.session.analysis_config
        if config is not None and self.session.total_line_count > config.max_lines_scanned:
            self.results_view.prepend_scan_limit_warning(
                config.max_lines_scanned, self.session.total_line_count,
            )

        if analysis.line_count == self.session.total_line_count:
            scanned = f"All {analysis.line_count:,} lines scanned"
        else:
            scanned = f"{analysis.line_count:,} of {self.session.total_line_count:,} lines were scanned"
        self._finish_analysis_request()
        self._set_status(
            f"{scanned} - {self.session.encoding or 'unknown encoding'}"
        )
        self.analysis_finished.emit()

    @Slot(int, str)
    def _fail_analysis(self, request_id: int, message: str) -> None:
        """Restore the interface after a worker-side analysis failure."""

        if not self.session.fail_request(request_id):
            return

        self._finish_analysis_request()
        self._set_status(f"Analysis failed: {message}")
        self.analysis_failed.emit(message)

    def _set_analysis_busy(self, busy: bool) -> None:
        if busy:
            self.busy_visible = False
            self.results_view.focus_editor()
            self.busy_changed.emit()
            return

        self._analysis_busy_timer.stop()
        self.busy_visible = False
        self.busy_changed.emit()

    @Slot()
    def _show_analysis_busy(self) -> None:
        if not self.session.is_busy or self.analysis_queued:
            return

        self.busy_visible = True
        self.busy_changed.emit()
        request = self.session.active_request
        source_name = request.source_path.name if request is not None else "log"
        if self.session.phase is AnalysisPhase.RENDERING:
            self._set_status(
                f"Displaying results: {source_name}"
            )
        else:
            self._set_status(
                f"Analyzing: {source_name}"
            )

    def _finish_analysis_request(self) -> None:
        self.results_view.cancel_rendering()
        self._analysis_worker = None
        self.analysis_queued = False
        self._set_analysis_busy(False)
