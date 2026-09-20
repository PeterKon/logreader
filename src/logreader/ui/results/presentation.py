"""Pure presentation projections shared by GUI rendering and tests."""

from __future__ import annotations

from dataclasses import dataclass

from ...core import COMBINED_CATEGORY_KEY, AnalysisResult, CategoryResult, LogExcerpt


@dataclass(frozen=True, slots=True)
class CategoryPresentation:
    """Every excerpt in one non-empty category of the scanned source portion."""

    key: str
    result: CategoryResult
    excerpts: tuple[LogExcerpt, ...]

    def heading(self, label: str) -> str:
        suffix = "" if self.key == COMBINED_CATEGORY_KEY else " matches"
        return f"{label} - {self.result.match_count}{suffix}"


def build_category_presentations(
    analysis: AnalysisResult,
) -> tuple[CategoryPresentation, ...]:
    """Select non-empty categories without truncating their results."""
    return tuple(
        CategoryPresentation(key=key, result=result, excerpts=result.excerpts)
        for key, result in analysis.categories.items()
        if result.match_count
    )
