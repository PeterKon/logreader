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
    encoding: str | None = None
    analysis: AnalysisResult | None = None
    analysis_config: LogreaderConfig | None = None
    analysis_seconds: float | None = None
    rendering_seconds: float | None = None
    phase: AnalysisPhase = AnalysisPhase.IDLE
    request_generation: int = 0
    active_request: AnalysisRequest | None = None

    @property
    def has_document(self) -> bool:
        """Return whether a document has been loaded, including an empty one."""

        return self.path is not None

    @property
    def is_busy(self) -> bool:
        """Return whether analysis or result rendering is in progress."""

        return self.phase is not AnalysisPhase.IDLE

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
        self.encoding = loaded.encoding
        self.analysis = None
        self.analysis_config = None
        self.analysis_seconds = None
        self.rendering_seconds = None
        self.phase = AnalysisPhase.IDLE
        self.active_request = None

    def begin_analysis(
        self,
        config: LogreaderConfig,
        pattern_count: int,
    ) -> AnalysisRequest:
        """Start an analysis and return its immutable request snapshot."""

        if self.path is None:
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
