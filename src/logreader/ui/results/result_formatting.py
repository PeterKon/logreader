"""Result summaries, excerpts, and text formatting operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from ...config import LogreaderConfig
from ...core import COMBINED_CATEGORY_KEY, AnalysisResult, ResultLine
from .presentation import CategoryPresentation, build_category_presentations
from .results_model import ResultsModel


SUMMARY_ENTRY_GAP = 3
SUMMARY_LINE_LENGTH = 100
RESULT_LABEL_OVERRIDES = {"http_4xx": "HTTP 4xx", "http_5xx": "HTTP 5xx"}

RenderOperation = tuple[str, str, bool]


@dataclass(frozen=True, slots=True)
class CategoryLabel:
    key: str
    role: str

    def fragment(self, name: str) -> RenderOperation:
        if self.role == "hit_count":
            # Keep the label and its count together when Qt wraps the line.
            name = name.replace(" ", "\u00a0") + "\u00a0"
        return name, self.role, self.role == "heading"

    def resolve(self, config: LogreaderConfig) -> RenderOperation:
        return self.fragment(RESULT_LABEL_OVERRIDES.get(self.key, config.label_for(self.key)))


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

    for operation in summary_operations(analysis, config):
        yield operation.resolve(config) if isinstance(operation, CategoryLabel) else operation
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


def summary_operations(analysis: AnalysisResult, config: LogreaderConfig) -> Iterator[RenderOperation | CategoryLabel]:
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
        if match_count == 0:
            zero_entries.append((key, match_count))
        else:
            positive_entries.append((key, match_count))

    total_matches = sum(result.match_count for result in analysis.categories.values())
    yield f"Matches ({total_matches:,} total):\n", "heading", True
    if positive_entries:
        yield from _iter_summary_entries(positive_entries, config)
    else:
        yield "0", "muted", False
    yield "\n", "body", False

    if zero_entries:
        yield "\nNo matches:\n", "heading", False
        yield from _iter_summary_entries(zero_entries, config)
        yield "\n", "muted", False


def _iter_summary_entries(
    entries: list[tuple[str, int]], config: LogreaderConfig,
) -> Iterator[RenderOperation | CategoryLabel]:
    line_length = 0
    for key, count in entries:
        label = CategoryLabel(key, "hit_count" if count else "muted")
        entry_length = len(label.resolve(config)[0]) + (len(str(count)) if count else 0)
        separator = " " * SUMMARY_ENTRY_GAP if count else ", "
        if line_length:
            if line_length + len(separator) + entry_length > SUMMARY_LINE_LENGTH:
                yield "\n", "muted", False
                line_length = 0
            else:
                yield separator, "muted", False
                line_length += len(separator)
        yield label
        if count:
            yield str(count), "body", False
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
