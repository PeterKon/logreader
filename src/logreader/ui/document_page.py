"""Document-owned controls, results, and analysis lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..workers.analysis_worker import AnalysisWorker
from ..config import LogreaderConfig
from ..core import AnalysisResult
from ..document_session import AnalysisPhase, DocumentSession, LoadPhase
from ..file_loader import DEFAULT_MAX_LINES_SCANNED, LoadedLog
from ..profiles import Profile, ProfileError
from ..session_snapshot import BookmarkSnapshot, SessionTab
from ..workers.load_worker import LoadWorker
from .filter_panel import FilterPanel, VisibleCheckBox, VisibleSpinBox
from .results.results_view import ResultsView
from .unavailable_file import UnavailableFileWarning
from ..workers.work_queue import WorkScheduler


ANALYSIS_BUSY_DELAY_MS = 40


class DocumentPage(QWidget):
    """Own one document independently of the window presenting its status."""

    analysis_finished = Signal()
    analysis_failed = Signal(str)
    status_changed = Signal(str)
    busy_changed = Signal()
    load_finished = Signal()
    profile_state_changed = Signal()
    replace_file_requested = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, scheduler: WorkScheduler | None = None,
        show_performance: bool = False,
        claim_replacement: Callable[[DocumentPage, Path], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("centralWidget")
        self.session = DocumentSession()
        self._applied_profile: Profile | None = None
        self.profile_available = False
        self.profile_modified = False
        self._updating_profile_state = False
        self.show_performance = show_performance
        self.status_message = "Open a file to begin"
        self.busy_visible = False
        self._analysis_worker: AnalysisWorker | None = None
        self._workers: dict[int, AnalysisWorker | LoadWorker] = {}
        self._load_worker: LoadWorker | None = None
        self._pending_analysis: LogreaderConfig | None = None
        self._pending_result_names: dict[str, str] = {}
        self._from_saved_session = False
        self._claim_replacement = claim_replacement
        self._pending_bookmarks: tuple[BookmarkSnapshot, ...] | None = None
        self._disposed = False
        self._bookmark_reset_notice = False
        self._scheduler = scheduler if scheduler is not None else WorkScheduler(self)
        self.load_queued = False
        self.analysis_queued = False
        self._render_active = True
        self._waiting_load = None
        self._analysis_busy_timer = QTimer(self)
        self._analysis_busy_timer.setSingleShot(True)
        self._analysis_busy_timer.setInterval(ANALYSIS_BUSY_DELAY_MS)
        self._analysis_busy_timer.timeout.connect(self._show_analysis_busy)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.file_warning = UnavailableFileWarning(self)
        self.file_warning.retry.clicked.connect(self.retry_session_file)
        self.file_warning.replace.clicked.connect(self.replace_file_requested.emit)
        root_layout.addWidget(self.file_warning)
        self.controls_container = QWidget(self)
        self.controls_container.setObjectName("controlsContainer")
        self.controls_layout = QVBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(0, 12, 0, 6)
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
        self.results_view.retired.connect(self._submit_waiting_load)
        self.results_view.view_state_changed.connect(self._emit_active_status)
        self.results_view.source_view.status_changed.connect(self._emit_active_status)
        root_layout.addWidget(self.results_view, 1)
        self.filter_panel.filters_changed.connect(self._update_profile_state)
        self.filter_panel.result_label_changed.connect(self._rename_result)
        self.results_view.results_prepared.connect(self._apply_pending_result_names)

    def _rename_result(self, key: str, name: str) -> None:
        if self.results_view.results_ready:
            self.results_view.rename_category(key, name)
        elif self.session.is_busy:
            self._pending_result_names[key] = name

    def _apply_pending_result_names(self) -> None:
        for key, name in self._pending_result_names.items():
            self.results_view.rename_category(key, name)
        self._pending_result_names.clear()

    @property
    def applied_profile(self) -> Profile | None:
        return self._applied_profile

    @applied_profile.setter
    def applied_profile(self, profile: Profile | None) -> None:
        self._applied_profile = profile
        self.profile_available = profile is not None
        self._update_profile_state()

    def sync_saved_profile(self, profile: Profile | None) -> None:
        """Refresh saved metadata without replacing this tab's controls."""
        if profile is not None:
            self._applied_profile = profile
        self.profile_available = profile is not None
        self._update_profile_state()

    def _update_profile_state(self) -> None:
        if self._disposed or self._updating_profile_state:
            return
        self._updating_profile_state = True
        try:
            profile = self.applied_profile
            self.profile_modified = False
            if profile is not None:
                try:
                    self.profile_modified = self.filter_panel.capture_snapshot() != profile.filters
                except ValueError:
                    self.profile_modified = True
            self.profile_state_changed.emit()
        finally:
            self._updating_profile_state = False

    def apply_profile(self, profile: Profile) -> None:
        if self._disposed or self.session.is_busy:
            raise ProfileError("Wait for this tab to finish before applying a profile.")
        self.filter_panel.restore_snapshot(profile.filters)
        self.applied_profile = profile
        self._set_status(f"Profile applied: {profile.name}")

    def capture_session_tab(self) -> SessionTab:
        if self._disposed or self.session.path is None:
            raise ValueError("A session tab must have a file")
        custom, regex = self.filter_panel.pattern_drafts()
        return SessionTab(
            path=self.session.path.absolute(), filters=self.filter_panel.capture_snapshot(),
            custom_draft=custom, regex_draft=regex, bookmarks=self._capture_bookmarks(),
        )

    def restore_session_tab(self, tab: SessionTab) -> None:
        """Reload the saved source with the tab's own controls and annotations."""
        if self._disposed:
            raise ValueError("Cannot restore a closed tab")
        self.applied_profile = None
        self.filter_panel.restore_snapshot(tab.filters)
        self.filter_panel.set_pattern_drafts(tab.custom_draft, tab.regex_draft)
        self.load_file(tab.path, max_lines_scanned=tab.filters.max_lines_scanned,
                       session_bookmarks=tab.bookmarks)

    def _capture_bookmarks(self) -> tuple[BookmarkSnapshot, ...]:
        if self._pending_bookmarks is not None:
            return self._pending_bookmarks
        return self.results_view.bookmarks.capture()

    def _restore_pending_bookmarks(self) -> None:
        if self._pending_bookmarks is not None:
            self.results_view.bookmarks.restore(self._pending_bookmarks)
            self._pending_bookmarks = None

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
        self._emit_active_status()

    @property
    def active_status_message(self) -> str:
        if self.results_view.source_active:
            message = self.results_view.source_view.status_message
            if self.session.encoding:
                message += f" - {self.session.encoding}"
            return message
        return self.status_message

    def _emit_active_status(self) -> None:
        self.status_changed.emit(self.active_status_message)

    def build_config(self) -> LogreaderConfig:
        """Snapshot the current document's committed filter settings."""
        return self.filter_panel.build_config()

    def stage_loaded_log(self, path: Path, loaded: LoadedLog) -> None:
        """Replace this document, invalidating its previous work."""
        if self._disposed:
            return
        self._from_saved_session = False
        self._pending_bookmarks = None
        if self._waiting_load is not None:
            waiting, self._waiting_load = self._waiting_load, None
            waiting.discard()
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
        self.file_warning.hide()
        self.results_view.reset_for_loaded_file(path.name)
        self.results_view.set_source(
            loaded.lines, loaded.total_line_count, snapshot_id=self.session.snapshot_id,
        )
        if self._pending_bookmarks is not None:
            self._restore_pending_bookmarks()
            self._bookmark_reset_notice = False
        self.busy_changed.emit()
        self._set_status(f"Loaded as {loaded.encoding}: {path.name}")
        self._bookmark_reset_notice = False

    def load_file(
        self, path: Path, *,
        max_lines_scanned: int | None = None,
        analyze_after_load: LogreaderConfig | None = None,
        session_bookmarks: tuple[BookmarkSnapshot, ...] | None = None,
    ) -> None:
        """Start a document-owned load without blocking the GUI thread."""
        if self._disposed:
            return
        if session_bookmarks is None and self._from_saved_session and path == self.session.path:
            # Retry and scan-limit expansion reread the same restored tab.
            session_bookmarks = self._capture_bookmarks()
        if max_lines_scanned is None:
            max_lines_scanned = (self.filter_panel.capture_snapshot().max_lines_scanned
                                 if session_bookmarks is not None else DEFAULT_MAX_LINES_SCANNED)
        self._from_saved_session = session_bookmarks is not None
        self._pending_bookmarks = session_bookmarks
        self.file_warning.hide()
        if self._waiting_load is not None:
            waiting, self._waiting_load = self._waiting_load, None
            waiting.discard()
        self._pending_analysis = analyze_after_load
        for worker in tuple(self._workers.values()):
            self._scheduler.cancel(worker)
        request_id = self.session.begin_loading(path)
        self._finish_analysis_request()
        self.results_view.reset_for_loaded_file(path.name)
        if self._from_saved_session:
            self._bookmark_reset_notice = False
        self.results_view.source_view.reset("Loading source…")
        self._queue_load(request_id, path, max_lines_scanned)

    @property
    def unavailable_session_file(self) -> bool:
        return not self._disposed and self._from_saved_session and self.session.load_phase is LoadPhase.FAILED

    def retry_session_file(self) -> None:
        if self.unavailable_session_file:
            self.load_file(self.session.path)

    def try_replacement(self, path: Path) -> None:
        if not self.unavailable_session_file:
            return
        if path == self.session.path:
            self.retry_session_file()
            return
        limit = self.filter_panel.capture_snapshot().max_lines_scanned
        request_id = self.session.begin_loading(path, replacement=True)
        self.file_warning.set_detail(f"Trying {path}", busy=True)
        self._queue_load(request_id, path, limit)
        self.busy_changed.emit()

    def _queue_load(self, request_id: int, path: Path, max_lines_scanned: int) -> None:
        self.load_queued = True
        message = f"Queued to load: {path.name}"
        self._set_status(message)
        worker = LoadWorker(request_id, path, max_lines_scanned, include_error_path=not self._from_saved_session)
        worker.signals.started.connect(self._load_started)
        worker.signals.completed.connect(self._complete_load)
        worker.signals.failed.connect(self._fail_load)
        worker.signals.finished.connect(self._worker_finished)
        self._load_worker = worker
        self._workers[request_id] = worker
        self._waiting_load = worker
        self._submit_waiting_load()

    def _submit_waiting_load(self) -> None:
        worker = self._waiting_load
        if worker is None or self.results_view.has_retiring_results:
            return
        self._waiting_load = None
        if self._disposed or self.session.active_load_id != worker.request_id:
            worker.discard()
            return
        self._scheduler.loading.submit(worker)

    @Slot(int)
    def _load_started(self, request_id: int) -> None:
        if self._disposed or self.session.active_load_id != request_id:
            return
        self.load_queued = False
        message = f"Loading {self.session.loading_path.name}…"
        self._set_status(message)
        self.busy_changed.emit()

    @Slot(int, object)
    def _complete_load(self, request_id: int, loaded: LoadedLog) -> None:
        if self.session.active_load_id != request_id:
            return
        candidate = self.session.loading_path
        if candidate != self.session.path:
            # Include any note edits made while the candidate was being read.
            records = self._capture_bookmarks()
            if self._claim_replacement is not None and not self._claim_replacement(self, candidate):
                self._fail_load(request_id, "This file is already open in another tab.")
                return
            self._pending_bookmarks = records
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
        attempted = self.session.loading_path
        if not self.session.fail_loading(request_id, message):
            return
        self._load_worker = None
        self.load_queued = False
        self._pending_analysis = None
        if self.unavailable_session_file:
            self.file_warning.show_failure(self.session.path, self.session.load_error)
            if attempted != self.session.path:
                self.file_warning.set_detail(f"Could not use {attempted}\n{message}")
            self._set_status(f"File unavailable: {self.session.path.name}")
        else:
            self._set_status(f"Could not load {self.session.path.name}: {message}. Press Analyze to retry.")
        if attempted == self.session.path:
            self._bookmark_reset_notice = False
            self.results_view.reset_for_loaded_file(self.session.path.name)
            placeholder = ("Source file unavailable." if self.unavailable_session_file else
                           f"Could not load the file: {message}. Press Analyze to retry.")
            self.results_view.source_view.reset(placeholder)
            self._restore_pending_bookmarks()
        self.busy_changed.emit()
        self.load_finished.emit()

    def analyze(self) -> None:
        """Analyze the loaded file using the current controls."""

        if self._disposed or self.session.path is None or self.session.is_busy or self.unavailable_session_file:
            return

        try:
            config = self.build_config()
            config.search_patterns()  # Validate before discarding the loaded snapshot.
        except ValueError as error:
            self._set_status(f"Analysis failed: {error}")
            self.analysis_failed.emit(str(error))
            return

        self.filter_panel.bind_result_keys()
        self._pending_result_names.clear()
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
            config, sum(not (pattern.exclude or pattern.exclusive) for pattern in patterns),
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
        if (self._disposed or request is None or request.request_id != request_id
                or self.session.phase is not AnalysisPhase.ANALYZING):
            return
        self.analysis_queued = False
        if self.busy_visible:
            self.results_view.set_analysis_message("Analyzing...")
        self._set_status(f"Analyzing: {request.source_path.name}")
        self.busy_changed.emit()

    def set_render_active(self, active: bool) -> None:
        """Only the selected tab consumes GUI rendering batches."""
        if self._render_active == active:
            return
        self._render_active = active
        self.results_view.source_view.set_active(active)
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
                scan_limit=(request.config.max_lines_scanned, self.session.total_line_count)
                if request.config.max_lines_scanned < self.session.total_line_count else None,
            )
        self._set_status(f"Displaying results: {request.source_path.name}")
        self.busy_changed.emit()

    def dispose(self) -> None:
        """Stop UI work now; retain running workers until their final signal."""
        if self._disposed:
            return
        self._disposed = True
        if self._waiting_load is not None:
            waiting, self._waiting_load = self._waiting_load, None
            waiting.discard()
        self._pending_analysis = None
        self._pending_bookmarks = None
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
        self._set_analysis_busy(False)
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

        if analysis.line_count == self.session.total_line_count:
            scanned = f"All {analysis.line_count:,} lines scanned"
        else:
            scanned = f"{analysis.line_count:,} of {self.session.total_line_count:,} lines were scanned"
        self._finish_analysis_request(cancel_rendering=False)
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
        self.results_view.set_analysis_message("Analysis failed")
        self._set_status(f"Analysis failed: {message}")
        self.analysis_failed.emit(message)

    def _set_analysis_busy(self, busy: bool) -> None:
        if busy:
            self.busy_visible = False
            self.results_view.begin_analysis()
            self.results_view.focus_editor()
            self._analysis_busy_timer.start()
            self.busy_changed.emit()
            return

        self._analysis_busy_timer.stop()
        self.busy_visible = False
        self.results_view.set_analysis_message("")
        self.busy_changed.emit()

    @Slot()
    def _show_analysis_busy(self) -> None:
        if self.session.phase is not AnalysisPhase.ANALYZING:
            return

        self.busy_visible = True
        self.results_view.set_analysis_message("Queued" if self.analysis_queued else "Analyzing...")
        self.busy_changed.emit()

    def _finish_analysis_request(self, *, cancel_rendering: bool = True) -> None:
        if cancel_rendering:
            self.results_view.cancel_rendering()
        self._analysis_worker = None
        self.analysis_queued = False
        self._set_analysis_busy(False)
