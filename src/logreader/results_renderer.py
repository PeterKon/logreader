"""Qt document rendering and result headers."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from .config import LogreaderConfig
from .core import AnalysisResult
from .result_formatting import RenderOperation, _iter_analysis_render_operations
from .result_source_map import ResultSourceMap
from .results_editor import (
    ExcerptGapBlock, ResultsEditor, StructuralBlock, SummaryBlock, mark_summary, size_excerpt_gap,
)
from .results_model import ResultsModel
from .theme import THEME_COLORS


RESULT_COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
# Lazily built for the fixed results palette; never mutate a cached format.
_RESULT_FORMATS: dict[tuple[str, bool], QTextCharFormat] = {}
INCREMENTAL_RENDER_BATCH_MS = 8


class IncrementalAnalysisRenderer(QObject):
    """Build a formatted results document in event-loop-sized batches."""

    completed = Signal(int, float)
    failed = Signal(int, str)

    def __init__(
        self,
        request_id: int,
        view: QPlainTextEdit,
        source_name: str,
        analysis: AnalysisResult,
        config: LogreaderConfig,
        parent: QObject | None = None,
        source_map: ResultSourceMap | None = None,
        model: ResultsModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._view = view
        self._source_map = source_map if source_map is not None else (
            view.projection if isinstance(view, ResultsEditor) else None
        )
        self._model = model if model is not None else ResultsModel(analysis, uuid4().hex)
        self._index_work = self._model.prepare()
        self._operations = _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
            on_excerpt=self._record_excerpt,
            on_summary=self._record_summary,
            model=self._model,
        )
        self._cursor: QTextCursor | None = None
        self._started = 0.0
        self._cancelled = False
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_next_batch)

    def _record_summary(self) -> None:
        if isinstance(self._view, ResultsEditor) and self._cursor is not None:
            mark_summary(self._cursor)

    def _record_excerpt(self, source_line: int, length: int) -> None:
        if self._source_map is not None and self._cursor is not None:
            self._source_map.append(self._cursor.blockNumber(), length, source_line)

    def start(self) -> None:
        """Clear the previous document and schedule the first render batch."""

        self._started = perf_counter()
        self._view.setUpdatesEnabled(False)
        self._view.clear()
        if self._source_map is not None:
            self._source_map.clear()
        if isinstance(self._view, ResultsEditor):
            self._view.set_model(self._model)
        self._cursor = QTextCursor(self._view.document())
        self._timer.start(0)

    def cancel(self) -> None:
        """Stop future batches and restore painting for the results view."""

        self._cancelled = True
        self._timer.stop()
        self._cursor = None
        # A suspended generator owns the full analysis (and source strings).
        # Release it now, even if a caller retains the renderer wrapper until
        # after Qt processes deleteLater().
        self._operations = iter(())
        self._index_work = None
        if isinstance(self._view, ResultsEditor) and self._view.model is self._model:
            self._view.set_model(None)
            self._view.projection.clear()
        self._model = None
        self._view.setUpdatesEnabled(True)

    def set_paused(self, paused: bool) -> None:
        if self._cancelled or paused == (self._paused_at is not None):
            return
        if paused:
            self._paused_at = perf_counter()
            self._timer.stop()
            self._view.setUpdatesEnabled(True)
        else:
            self._paused_seconds += perf_counter() - self._paused_at
            self._paused_at = None
            self._view.setUpdatesEnabled(False)
            self._timer.start(0)

    @Slot()
    def _render_next_batch(self) -> None:
        if self._cancelled or self._cursor is None or self._paused_at is not None:
            return

        batch_elapsed = QElapsedTimer()
        batch_elapsed.start()
        finished = False
        self._cursor.beginEditBlock()
        try:
            while True:
                if self._index_work is not None:
                    try:
                        next(self._index_work)
                    except StopIteration:
                        self._index_work = None
                        if isinstance(self._view, ResultsEditor):
                            self._view.update_gutter()
                    if batch_elapsed.elapsed() >= INCREMENTAL_RENDER_BATCH_MS:
                        break
                    continue
                try:
                    text, role, bold = next(self._operations)
                except StopIteration:
                    finished = True
                    break

                _insert(
                    self._cursor, text, role, bold=bold,
                    structural=isinstance(self._view, ResultsEditor) and
                    self._view.projection.row(self._cursor.blockNumber()) is None,
                )
                if batch_elapsed.elapsed() >= INCREMENTAL_RENDER_BATCH_MS:
                    break
        except Exception as error:
            self._cursor.endEditBlock()
            self.cancel()
            self.failed.emit(self.request_id, str(error))
            return
        self._cursor.endEditBlock()

        if not finished:
            self._timer.start(0)
            return

        self._cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._view.setTextCursor(self._cursor)
        self._cursor = None
        self._model = None
        self._view.setUpdatesEnabled(True)
        self.completed.emit(
            self.request_id,
            perf_counter() - self._started - self._paused_seconds,
        )


def render_analysis(
    view: QPlainTextEdit,
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> None:
    """Render a structured analysis result into a colored Qt text view."""

    view.setUpdatesEnabled(False)
    try:
        view.clear()
        model = ResultsModel(analysis, uuid4().hex)
        for _ in model.prepare():
            pass
        if isinstance(view, ResultsEditor):
            view.set_model(model)
        cursor = QTextCursor(view.document())
        cursor.beginEditBlock()
        for text, role, bold in _iter_analysis_render_operations(
            source_name,
            analysis,
            config,
            model=model,
            on_summary=(lambda: mark_summary(cursor)) if isinstance(view, ResultsEditor) else None,
            on_excerpt=(lambda number, length: view.projection.append(
                cursor.blockNumber(), length, number,
            )) if isinstance(view, ResultsEditor) else None,
        ):
            _insert(
                cursor, text, role, bold=bold,
                structural=isinstance(view, ResultsEditor) and
                view.projection.row(cursor.blockNumber()) is None,
            )

        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def prepend_performance_timings(
    view: QPlainTextEdit,
    analysis_seconds: float,
    rendering_seconds: float,
) -> None:
    """Place diagnostic analysis and rendering durations above the results."""

    model = view.model if isinstance(view, ResultsEditor) else None
    scanned_lines = model.analysis.line_count if model is not None else 0
    result_rows = model.row_count if model is not None else 0
    analysis_per_100k = (
        f"{(analysis_seconds / scanned_lines) * 100_000:.3f} s" if scanned_lines else "N/A"
    )
    rendering_per_100k = (
        f"{(rendering_seconds / result_rows) * 100_000:.3f} s" if result_rows else "N/A"
    )
    _prepend_result_header(view, (
        ("Performance results\n", "heading", True),
        (f"Analysis: {analysis_seconds:.3f} s\n", "muted", False),
        (f"Rendering: {rendering_seconds:.3f} s\n", "muted", False),
        (f"Total: {analysis_seconds + rendering_seconds:.3f} s\n\n", "muted", False),
        (f"Analysis per 100K source rows: {analysis_per_100k}\n", "muted", False),
        (f"Rendering per 100K result rows: {rendering_per_100k}\n\n", "muted", False),
    ))


def _prepend_result_header(view: QPlainTextEdit, operations: tuple[RenderOperation, ...]) -> None:
    """Insert notices above the summary while preserving source row mapping."""
    blocks_before = view.document().blockCount()
    first_was_structural = isinstance(view.document().firstBlock().userData(), StructuralBlock)
    first_data = view.document().firstBlock().userData()
    first_summary = (first_data.first, first_data.last) if isinstance(first_data, SummaryBlock) else None
    view.setUpdatesEnabled(False)
    try:
        cursor = QTextCursor(view.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        for text, role, bold in operations:
            _insert(cursor, text, role, bold=bold, structural=True)
        # Inserting at the start splits the old first block; Qt leaves its user
        # data on the inserted block, so restore the displaced row's identity.
        cursor.block().setUserData(
            SummaryBlock(first=first_summary[0], last=first_summary[1]) if first_summary else
            StructuralBlock() if first_was_structural else None
        )
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        if isinstance(view, ResultsEditor):
            view.projection.header_blocks += view.document().blockCount() - blocks_before
            view.update_gutter()
        view.setUpdatesEnabled(True)


def _insert(
    cursor: QTextCursor,
    text: str,
    role: str,
    *,
    bold: bool = False,
    structural: bool = False,
) -> None:
    excerpt_gap = role == "excerpt_gap"
    if excerpt_gap:
        role = "body"
    key = (role, bold)
    text_format = _RESULT_FORMATS.get(key)
    if text_format is None:
        text_format = QTextCharFormat()
        text_format.setForeground(RESULT_COLORS[role])
        if bold:
            text_format.setFontWeight(QFont.Weight.Bold)
        _RESULT_FORMATS[key] = text_format
    first = cursor.block()
    cursor.insertText(text, text_format)
    # Mark completed structural blocks, including the starting block of a
    # partial formatting operation. The final empty block may be filled with
    # source text next, so leave its identity to that next insertion.
    block = first
    while block.isValid() and block.position() < cursor.position():
        block.setUserData(StructuralBlock() if structural else None)
        block = block.next()
    if excerpt_gap:
        first.setUserData(ExcerptGapBlock())
        size_excerpt_gap(first, cursor.document().defaultFont())
