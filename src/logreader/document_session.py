"""State and lifecycle for one loaded Logreader document."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .config import LogreaderConfig
from .core import AnalysisResult
from .file_loader import LoadedLog


class AnalysisPhase(str, Enum):
    """Current analysis lifecycle phase for a document."""

    IDLE = "idle"
    ANALYZING = "analyzing"
    RENDERING = "rendering"


class LoadPhase(str, Enum):
    """Whether a reserved document path has readable source contents."""

    EMPTY = "empty"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Immutable snapshot of one analysis request."""

    request_id: int
    source_path: Path
    config: LogreaderConfig
    pattern_count: int


@dataclass(slots=True)
class DocumentSession:
    """Own the source and analysis state for one loaded document."""

    path: Path | None = None
    lines: tuple[str, ...] = ()
    total_line_count: int = 0
    encoding: str | None = None
    analysis: AnalysisResult | None = None
    analysis_config: LogreaderConfig | None = None
    analysis_seconds: float | None = None
    rendering_seconds: float | None = None
    phase: AnalysisPhase = AnalysisPhase.IDLE
    request_generation: int = 0
    active_request: AnalysisRequest | None = None
    load_phase: LoadPhase = LoadPhase.EMPTY
    active_load_id: int | None = None
    load_error: str | None = None

    @property
    def has_document(self) -> bool:
        """Return whether a document has been loaded, including an empty one."""

        return self.load_phase is LoadPhase.LOADED

    @property
    def is_busy(self) -> bool:
        """Return whether loading, analysis, or result rendering is in progress."""

        return self.phase is not AnalysisPhase.IDLE or self.load_phase is LoadPhase.LOADING

    def begin_loading(self, source_path: str | Path) -> int:
        """Reserve the path and generation before background loading starts."""
        self.clear()
        self.request_generation += 1
        self.active_load_id = self.request_generation
        self.path = Path(source_path)
        self.load_phase = LoadPhase.LOADING
        return self.active_load_id

    def complete_loading(self, request_id: int, loaded: LoadedLog) -> bool:
        """Accept contents only from the current load generation."""
        if self.active_load_id != request_id or self.load_phase is not LoadPhase.LOADING:
            return False
        self.active_load_id = None
        self.load_phase = LoadPhase.EMPTY
        self.stage_loaded_log(self.path, loaded)
        return True

    def fail_loading(self, request_id: int, message: str) -> bool:
        """Retain the path and failure details without marking it ready."""
        if self.active_load_id != request_id or self.load_phase is not LoadPhase.LOADING:
            return False
        self.active_load_id = None
        self.load_phase = LoadPhase.FAILED
        self.load_error = message
        return True

    def stage_loaded_log(
        self,
        source_path: str | Path,
        loaded: LoadedLog,
    ) -> None:
        """Replace the document and clear analysis derived from the old one."""

        if self.is_busy:
            self.cancel_request()

        self.path = Path(source_path)
        self.lines = loaded.lines
        self.total_line_count = loaded.total_line_count
        self.encoding = loaded.encoding
        self.analysis = None
        self.analysis_config = None
        self.analysis_seconds = None
        self.rendering_seconds = None
        self.phase = AnalysisPhase.IDLE
        self.active_request = None
        self.load_phase = LoadPhase.LOADED
        self.load_error = None

    def begin_analysis(
        self,
        config: LogreaderConfig,
        pattern_count: int,
    ) -> AnalysisRequest:
        """Start an analysis and return its immutable request snapshot."""

        if not self.has_document:
            raise RuntimeError("Cannot analyze before a document is loaded")
        if self.is_busy:
            raise RuntimeError("An analysis request is already active")
        if pattern_count < 0:
            raise ValueError("Pattern count cannot be negative")

        self.request_generation += 1
        request = AnalysisRequest(
            request_id=self.request_generation,
            source_path=self.path,
            config=config,
            pattern_count=pattern_count,
        )
        self.active_request = request
        self.phase = AnalysisPhase.ANALYZING
        return request

    def clear(self) -> None:
        """Invalidate requests and release all source and derived data."""
        self.cancel_request()
        self.path = None
        self.lines = ()
        self.total_line_count = 0
        self.encoding = None
        self.analysis = None
        self.analysis_config = None
        self.analysis_seconds = None
        self.rendering_seconds = None
        self.load_phase = LoadPhase.EMPTY
        self.active_load_id = None
        self.load_error = None

    def begin_rendering(
        self,
        request_id: int,
        analysis: AnalysisResult,
        analysis_seconds: float,
    ) -> bool:
        """Accept current analysis output and advance to result rendering."""

        if not self._matches_active_request(
            request_id,
            AnalysisPhase.ANALYZING,
        ):
            return False

        request = self.active_request
        if request is None:  # Guard the lifecycle invariant for type checkers.
            return False

        self.analysis = analysis
        self.analysis_config = request.config
        self.analysis_seconds = analysis_seconds
        self.rendering_seconds = None
        self.phase = AnalysisPhase.RENDERING
        return True

    def complete_rendering(
        self,
        request_id: int,
        rendering_seconds: float,
    ) -> bool:
        """Record completed rendering for the current analysis request."""

        if not self._matches_active_request(
            request_id,
            AnalysisPhase.RENDERING,
        ):
            return False

        self.rendering_seconds = rendering_seconds
        self._finish_request()
        return True

    def fail_request(self, request_id: int) -> bool:
        """Finish the current request after analysis or rendering failed."""

        if not self._matches_active_request(request_id):
            return False

        self._finish_request()
        return True

    def cancel_request(self) -> bool:
        """Invalidate and finish the current request, if one is active."""

        if not self.is_busy:
            return False

        self.request_generation += 1
        if self.load_phase is LoadPhase.LOADING:
            self.active_load_id = None
            self.load_phase = LoadPhase.EMPTY
        self._finish_request()
        return True

    def _matches_active_request(
        self,
        request_id: int,
        phase: AnalysisPhase | None = None,
    ) -> bool:
        request = self.active_request
        return (
            request is not None
            and request.request_id == request_id
            and (phase is None or self.phase is phase)
        )

    def _finish_request(self) -> None:
        self.phase = AnalysisPhase.IDLE
        self.active_request = None
