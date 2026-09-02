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


@dataclass(slots=True)
class _PatternMatchState:
    """Compiled pattern and its sparse, mutable scan results."""

    pattern: SearchPattern
    expression: re.Pattern[str]
    folded_exclusions: tuple[str, ...]
    match_spans_by_index: dict[int, tuple[MatchSpan, ...]]
    raw_only_match_indexes: set[int]


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
    states = []
    pattern_keys = set()
    for pattern in patterns:
        if pattern.key in pattern_keys:
            raise ValueError(f"Duplicate search pattern key: {pattern.key}")
        pattern_keys.add(pattern.key)
        states.append(_compile_pattern_state(pattern))

    _collect_pattern_matches(source_lines, states)
    categories = {
        state.pattern.key: _build_category_result(source_lines, state)
        for state in states
    }

    return AnalysisResult(line_count=len(source_lines), categories=categories)


def _compile_pattern_state(pattern: SearchPattern) -> _PatternMatchState:
    expression = re.compile(
        pattern.needle if pattern.is_regex else re.escape(pattern.needle),
        0 if pattern.is_regex else re.IGNORECASE,
    )
    return _PatternMatchState(
        pattern=pattern,
        expression=expression,
        folded_exclusions=tuple(
            exclusion.casefold() for exclusion in pattern.excluded_substrings
        ),
        match_spans_by_index={},
        raw_only_match_indexes=set(),
    )


def _collect_pattern_matches(
    source_lines: tuple[str, ...],
    states: list[_PatternMatchState],
) -> None:
    literal_states = [state for state in states if not state.pattern.is_regex]
    independent_states = [state for state in states if state.pattern.is_regex]
    literal_candidates: re.Pattern[str] | None = None
    if len(literal_states) == 1:
        independent_states.extend(literal_states)
        literal_states = []
    elif literal_states:
        alternatives = "|".join(
            dict.fromkeys(
                re.escape(state.pattern.needle) for state in literal_states
            )
        )
        literal_candidates = re.compile(
            rf"(?=(?:{alternatives}))",
            re.IGNORECASE,
        )

    for line_index, line in enumerate(source_lines):
        if literal_candidates is not None:
            _collect_shared_literal_matches(
                line_index,
                line,
                literal_states,
                literal_candidates,
            )
        for state in independent_states:
            spans, has_raw_match = _find_line_matches(
                line,
                state.expression,
                state.folded_exclusions,
                state.pattern.match_validator,
            )
            _record_line_matches(
                state,
                line_index,
                spans,
                has_raw_match,
            )


def _collect_shared_literal_matches(
    line_index: int,
    line: str,
    states: list[_PatternMatchState],
    candidate_expression: re.Pattern[str],
) -> None:
    line_spans: dict[int, list[MatchSpan]] = {}
    next_search_start: dict[int, int] = {}
    completed_exclusions: set[int] = set()
    excluded_state_indexes: set[int] | None = None

    for candidate in candidate_expression.finditer(line):
        start = candidate.start()
        if excluded_state_indexes is None:
            folded_line = line.casefold()
            excluded_state_indexes = {
                index
                for index, state in enumerate(states)
                if state.folded_exclusions
                and any(
                    exclusion in folded_line
                    for exclusion in state.folded_exclusions
                )
            }

        for state_index, state in enumerate(states):
            if state_index in completed_exclusions:
                continue
            if start < next_search_start.get(state_index, 0):
                continue

            match = state.expression.match(line, start)
            if match is None:
                continue
            end = match.end()
            next_search_start[state_index] = end
            if (
                state.pattern.match_validator is not None
                and not state.pattern.match_validator(line, start, end)
            ):
                continue

            if state_index in excluded_state_indexes:
                state.raw_only_match_indexes.add(line_index)
                completed_exclusions.add(state_index)
                continue
            line_spans.setdefault(state_index, []).append(
                MatchSpan(start, end)
            )

    for state_index, spans in line_spans.items():
        states[state_index].match_spans_by_index[line_index] = tuple(spans)


def _record_line_matches(
    state: _PatternMatchState,
    line_index: int,
    spans: tuple[MatchSpan, ...],
    has_raw_match: bool,
) -> None:
    if spans:
        state.match_spans_by_index[line_index] = spans
    elif has_raw_match:
        state.raw_only_match_indexes.add(line_index)


def _build_category_result(
    source_lines: tuple[str, ...],
    state: _PatternMatchState,
) -> CategoryResult:
    pattern = state.pattern
    match_spans_by_index = state.match_spans_by_index
    raw_only_match_indexes = state.raw_only_match_indexes

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
    folded_exclusions: tuple[str, ...] = (),
    match_validator: MatchValidator | None = None,
) -> tuple[tuple[MatchSpan, ...], bool]:
    """Return accepted spans and whether the line has any raw occurrence."""

    is_excluded = False
    if folded_exclusions:
        folded_line = line.casefold()
        is_excluded = any(
            exclusion in folded_line for exclusion in folded_exclusions
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
