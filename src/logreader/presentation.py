"""Pure presentation projections shared by GUI rendering and tests."""

from __future__ import annotations

from dataclasses import dataclass

from .core import AnalysisResult, CategoryResult, LogExcerpt


@dataclass(frozen=True, slots=True)
class CategoryPresentation:
    """The visible portion of one non-empty analysis category."""

    key: str
    result: CategoryResult
    excerpts: tuple[LogExcerpt, ...]
    shown_match_count: int

    @property
    def is_limited(self) -> bool:
        return self.shown_match_count < self.result.match_count

    def heading(self, label: str) -> str:
        return f"{label} — {self.result.match_count} matches"

    def limit_message(self) -> str | None:
        if not self.is_limited:
            return None
        return (
            f"Showing {self.shown_match_count} of "
            f"{self.result.match_count} matches."
        )


def build_category_presentations(
    analysis: AnalysisResult,
    limit: int | None,
) -> tuple[CategoryPresentation, ...]:
    """Select non-empty categories and apply the per-category display limit."""

    if limit is not None and limit <= 0:
        raise ValueError("Limit must be positive or None")

    presentations = []
    for key, result in analysis.categories.items():
        if not result.match_count:
            continue
        excerpts, shown_match_count = _limit_excerpts(result, limit)
        presentations.append(
            CategoryPresentation(
                key=key,
                result=result,
                excerpts=excerpts,
                shown_match_count=shown_match_count,
            )
        )
    return tuple(presentations)


def _limit_excerpts(
    result: CategoryResult,
    limit: int | None,
) -> tuple[tuple[LogExcerpt, ...], int]:
    if limit is None or result.match_count <= limit:
        return result.excerpts, result.match_count

    visible_excerpts = []
    shown_match_count = 0
    stopped_at_limit = False

    for excerpt in result.excerpts:
        visible_lines = []
        for line in excerpt.lines:
            if line.is_match:
                if shown_match_count >= limit:
                    stopped_at_limit = True
                    break
                shown_match_count += 1
            visible_lines.append(line)

        if visible_lines:
            visible_excerpts.append(LogExcerpt(lines=tuple(visible_lines)))
        if stopped_at_limit or shown_match_count >= limit:
            break

    return tuple(visible_excerpts), shown_match_count
