"""Pure log analysis primitives used by the Logreader interfaces.

This module deliberately contains no file, terminal, or GUI operations.  Callers
provide already-decoded lines and decide how the structured results are rendered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SearchPattern:
    """Configuration for one case-insensitive literal search."""

    key: str
    needle: str
    context: int = 0
    excluded_substrings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Search pattern key cannot be empty")
        if not self.needle:
            raise ValueError("Search pattern needle cannot be empty")
        if self.context < 0:
            raise ValueError("Search pattern context cannot be negative")


@dataclass(frozen=True, slots=True)
class ResultLine:
    """One source line included in an analysis excerpt."""

    number: int
    text: str
    is_match: bool


@dataclass(frozen=True, slots=True)
class LogExcerpt:
    """A contiguous group containing one or more matches and their context."""

    lines: tuple[ResultLine, ...]


@dataclass(frozen=True, slots=True)
class CategoryResult:
    """All excerpts and match metadata for one search pattern."""

    pattern: SearchPattern
    match_count: int
    excerpts: tuple[LogExcerpt, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Structured output from analyzing a collection of log lines."""

    line_count: int
    categories: Mapping[str, CategoryResult]

    def category(self, key: str) -> CategoryResult:
        return self.categories[key]


def analyze_lines(
    lines: Sequence[str] | Iterable[str],
    patterns: Iterable[SearchPattern],
) -> AnalysisResult:
    """Analyze lines using case-insensitive literal search patterns.

    Context ranges that overlap or touch are merged into a single excerpt.  The
    returned objects retain the original text and one-based source line numbers.
    """

    source_lines = tuple(lines)
    folded_lines = tuple(line.casefold() for line in source_lines)
    categories: dict[str, CategoryResult] = {}

    for pattern in patterns:
        if pattern.key in categories:
            raise ValueError(f"Duplicate search pattern key: {pattern.key}")
        categories[pattern.key] = _analyze_pattern(
            source_lines,
            folded_lines,
            pattern,
        )

    return AnalysisResult(line_count=len(source_lines), categories=categories)


def _analyze_pattern(
    source_lines: tuple[str, ...],
    folded_lines: tuple[str, ...],
    pattern: SearchPattern,
) -> CategoryResult:
    needle = pattern.needle.casefold()
    exclusions = tuple(value.casefold() for value in pattern.excluded_substrings)

    match_indexes = tuple(
        index
        for index, line in enumerate(folded_lines)
        if needle in line and not any(exclusion in line for exclusion in exclusions)
    )
    match_index_set = set(match_indexes)

    ranges: list[tuple[int, int]] = []
    for match_index in match_indexes:
        start = max(0, match_index - pattern.context)
        end = match_index

        for candidate in range(
            match_index + 1,
            min(len(source_lines), match_index + pattern.context + 1),
        ):
            # Preserve the original reader's behavior: following context stops
            # before the next occurrence of the searched term.
            if needle in folded_lines[candidate]:
                break
            end = candidate

        if ranges and start <= ranges[-1][1] + 1:
            previous_start, previous_end = ranges[-1]
            ranges[-1] = (previous_start, max(previous_end, end))
        else:
            ranges.append((start, end))

    excerpts = tuple(
        LogExcerpt(
            lines=tuple(
                ResultLine(
                    number=index + 1,
                    text=source_lines[index],
                    is_match=index in match_index_set,
                )
                for index in range(start, end + 1)
            )
        )
        for start, end in ranges
    )

    return CategoryResult(
        pattern=pattern,
        match_count=len(match_indexes),
        excerpts=excerpts,
    )
