"""Pure log analysis primitives used by the Logreader interfaces.

This module deliberately contains no file or GUI operations. Callers provide
already-decoded lines and decide how the structured results are rendered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence


MatchValidator = Callable[[str, int, int], bool]


@dataclass(frozen=True, slots=True)
class SearchPattern:
    """Configuration for one case-insensitive literal or case-sensitive regex."""

    key: str
    needle: str
    context: int = 0
    excluded_substrings: tuple[str, ...] = ()
    is_regex: bool = False
    match_validator: MatchValidator | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Search pattern key cannot be empty")
        if not self.needle:
            raise ValueError("Search pattern needle cannot be empty")
        if self.context < 0:
            raise ValueError("Search pattern context cannot be negative")
        if self.match_validator is not None and not callable(self.match_validator):
            raise ValueError("Search pattern match validator must be callable")
        if self.is_regex:
            try:
                re.compile(self.needle)
            except re.error as error:
                raise ValueError(f"Invalid search pattern regex: {error}") from error


@dataclass(frozen=True, slots=True)
class MatchSpan:
    """Half-open character range identifying matched text in a source line."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Match span must have a non-empty positive range")


@dataclass(frozen=True, slots=True)
class ResultLine:
    """One source line included in an analysis excerpt."""

    number: int
    text: str
    match_spans: tuple[MatchSpan, ...] = ()

    @property
    def is_match(self) -> bool:
        return bool(self.match_spans)


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
    """Analyze lines using case-insensitive literals or case-sensitive regexes.

    Context ranges that overlap or touch are merged into a single excerpt.  The
    returned objects retain the original text, match spans, and one-based source
    line numbers. Patterns may validate individual regex candidates before they
    become matches.
    """

    source_lines = tuple(lines)
    categories: dict[str, CategoryResult] = {}

    for pattern in patterns:
        if pattern.key in categories:
            raise ValueError(f"Duplicate search pattern key: {pattern.key}")
        categories[pattern.key] = _analyze_pattern(
            source_lines,
            pattern,
        )

    return AnalysisResult(line_count=len(source_lines), categories=categories)


def _analyze_pattern(
    source_lines: tuple[str, ...],
    pattern: SearchPattern,
) -> CategoryResult:
    expression = re.compile(
        pattern.needle if pattern.is_regex else re.escape(pattern.needle),
        0 if pattern.is_regex else re.IGNORECASE,
    )
    match_spans_by_index: dict[int, tuple[MatchSpan, ...]] = {}
    raw_only_match_indexes: set[int] = set()
    for index, line in enumerate(source_lines):
        spans, has_raw_match = _find_line_matches(
            line,
            expression,
            pattern.excluded_substrings,
            pattern.match_validator,
        )
        if spans:
            match_spans_by_index[index] = spans
        elif has_raw_match:
            raw_only_match_indexes.add(index)

    ranges: list[tuple[int, int]] = []
    for match_index in match_spans_by_index:
        start = max(0, match_index - pattern.context)
        end = match_index

        for candidate in range(
            match_index + 1,
            min(len(source_lines), match_index + pattern.context + 1),
        ):
            # Preserve the original reader's behavior: following context stops
            # before the next occurrence of the searched term.
            if (
                candidate in match_spans_by_index
                or candidate in raw_only_match_indexes
            ):
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
                    match_spans=match_spans_by_index.get(index, ()),
                )
                for index in range(start, end + 1)
            )
        )
        for start, end in ranges
    )

    return CategoryResult(
        pattern=pattern,
        match_count=len(match_spans_by_index),
        excerpts=excerpts,
    )


def _find_line_matches(
    line: str,
    expression: re.Pattern[str],
    excluded_substrings: tuple[str, ...] = (),
    match_validator: MatchValidator | None = None,
) -> tuple[tuple[MatchSpan, ...], bool]:
    """Return accepted spans and whether the line has any raw occurrence."""

    is_excluded = False
    if excluded_substrings:
        folded_line = line.casefold()
        is_excluded = any(
            exclusion.casefold() in folded_line
            for exclusion in excluded_substrings
        )

    spans = []
    for match in expression.finditer(line):
        start, end = match.start(), match.end()
        if start == end:
            continue
        if (
            match_validator is not None
            and not match_validator(line, start, end)
        ):
            continue
        if is_excluded:
            return (), True
        spans.append(MatchSpan(start, end))

    accepted_spans = tuple(spans)
    return accepted_spans, bool(accepted_spans)
