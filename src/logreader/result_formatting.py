"""Result summaries, excerpts, and text formatting operations."""

from __future__ import annotations

from typing import Callable, Iterator

from .config import LogreaderConfig
from .core import COMBINED_CATEGORY_KEY, AnalysisResult, ResultLine
from .presentation import CategoryPresentation, build_category_presentations
from .results_model import ResultsModel


SUMMARY_COLUMNS = 3
SUMMARY_COLUMN_WIDTH = 19
SUMMARY_COLUMN_GAP = 5
SUMMARY_LINE_LENGTH = 100
RESULT_LABEL_OVERRIDES = {"http_4xx": "HTTP 4xx", "http_5xx": "HTTP 5xx"}

RenderOperation = tuple[str, str, bool]


def _iter_analysis_render_operations(
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
    *,
    on_excerpt: Callable[[int, int], None] | None = None,
    on_summary: Callable[[], None] | None = None,
    model: ResultsModel | None = None,
) -> Iterator[RenderOperation]:
    """Yield ordered formatting operations without touching Qt widgets."""

    if config.combined_view:
        summary_counts = (
            analysis.category_match_counts.items()
            if analysis.category_match_counts is not None
            else ()
        )
    else:
        summary_counts = (
            (key, result.match_count)
            for key, result in analysis.categories.items()
        )

    positive_entries = []
    zero_entries = []
    # Stable ordering keeps presets first, then custom literals, then regexes.
    ordered_counts = sorted(
        summary_counts,
        key=lambda item: 2 if item[0].startswith("regex_") else
        1 if item[0].startswith("custom_") else 0,
    )
    for key, match_count in ordered_counts:
        label = RESULT_LABEL_OVERRIDES.get(key, config.label_for(key))
        if match_count == 0:
            zero_entries.append((label, None))
        else:
            positive_entries.append((label, match_count))

    total_matches = sum(result.match_count for result in analysis.categories.values())
    yield f"Matches ({total_matches:,} total):\n", "heading", True
    if positive_entries:
        yield from _iter_positive_summary_entries(positive_entries)
    else:
        yield "0", "muted", False
    yield "\n", "body", False

    if zero_entries:
        yield "\nNo matches:\n", "heading", False
        yield from _iter_summary_entries(zero_entries)
        yield "\n", "muted", False

    if on_summary is not None:
        on_summary()

    presentations = (
        (section.presentation for section in model.sections)
        if model is not None else build_category_presentations(analysis)
    )
    for presentation in presentations:
        yield from _iter_category_render_operations(
            presentation, config, on_excerpt=on_excerpt,
        )


def _iter_positive_summary_entries(
    entries: list[tuple[str, int]],
) -> Iterator[RenderOperation]:
    """Fill three 19-character columns per row, with five spaces between them.

    Oversized entries keep their full label and count, extending only their row.
    """
    for index, (label, count) in enumerate(entries):
        if index:
            yield "\n" if index % SUMMARY_COLUMNS == 0 else " " * SUMMARY_COLUMN_GAP, "muted", False
        count_text = str(count)
        padding = " " * max(1, SUMMARY_COLUMN_WIDTH - len(label) - len(count_text))
        yield label + padding, _match_count_role(count), False
        yield count_text, "body", False


def _iter_summary_entries(
    entries: list[tuple[str, int | None]],
) -> Iterator[RenderOperation]:
    """Wrap plain-text lists at entry boundaries, preserving oversized entries."""
    line_length = 0
    for label, count in entries:
        count_text = "" if count is None else str(count)
        entry_length = len(label) + (1 + len(count_text) if count is not None else 0)
        if line_length:
            if line_length + 2 + entry_length > SUMMARY_LINE_LENGTH:
                yield "\n", "muted", False
                line_length = 0
            else:
                yield ", ", "muted", False
                line_length += 2
        if count is None:
            yield label, "muted", False
        else:
            yield f"{label} ", _match_count_role(count), False
            yield count_text, "body", False
        line_length += entry_length


def _iter_category_render_operations(
    presentation: CategoryPresentation,
    config: LogreaderConfig,
    *,
    on_excerpt: Callable[[int, int], None] | None = None,
) -> Iterator[RenderOperation]:
    if presentation.key == COMBINED_CATEGORY_KEY:
        yield "\n", "body", False
    else:
        label = RESULT_LABEL_OVERRIDES.get(presentation.key, config.label_for(presentation.key))
        yield f"\n{presentation.heading(label)}\n\n", "heading", True

    for excerpt_index, excerpt in enumerate(presentation.excerpts):
        if on_excerpt is not None and excerpt.lines:
            on_excerpt(excerpt.lines[0].number, len(excerpt.lines))
        for line in excerpt.lines:
            yield from _iter_result_line_render_operations(line)

        if (
            config.separate_entries
            and excerpt_index < len(presentation.excerpts) - 1
        ):
            yield "\n", "excerpt_gap", False



def _iter_result_line_render_operations(
    line: ResultLine,
) -> Iterator[RenderOperation]:
    if not line.is_match:
        yield f"{line.text}\n", "body", False
        return

    position = 0
    for span in line.match_spans:
        if span.start > position:
            yield line.text[position : span.start], "matched_text", False
        yield line.text[span.start : span.end], "match", True
        position = span.end
    yield f"{line.text[position:]}\n", "matched_text", False


def _match_count_role(match_count: int) -> str:
    return "hit_count" if match_count else "muted"
