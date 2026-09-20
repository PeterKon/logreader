"""Logical result rows and source locations, independent of text layout."""

from array import array
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from typing import Iterator

from ...core import AnalysisResult, ResultLine
from .presentation import CategoryPresentation, build_category_presentations


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """An original line in one loaded snapshot; survives reanalysis."""

    snapshot_id: str
    line: int


@dataclass(frozen=True, slots=True)
class CategoryIdentity:
    """Pattern identity independent of custom/regex list positions."""

    kind: str
    value: str
    case_sensitive: bool = False
    occurrence: int = 0


@dataclass(frozen=True, slots=True)
class ResultLocation:
    source: SourceLocation
    category: CategoryIdentity


@dataclass(slots=True)
class ResultSection:
    presentation: CategoryPresentation
    identity: CategoryIdentity
    row_starts: array = field(default_factory=lambda: array("Q"))

    def row_for_source(self, number: int) -> int | None:
        excerpts = self.presentation.excerpts
        index = bisect_right(excerpts, number, key=lambda e: e.lines[0].number) - 1
        if index < 0:
            return None
        offset = number - excerpts[index].lines[0].number
        if offset >= len(excerpts[index].lines):
            return None
        return self.row_starts[index] + offset


class ResultsModel:
    """Borrow analysis objects and index excerpts, without duplicating log text.

    Logical rows contain only source lines, in display order. Summary, headings,
    spacing and Qt blocks have no effect on their identity. Index construction
    yields once per excerpt so large, sparse results remain cancellable.
    """

    def __init__(self, analysis: AnalysisResult, snapshot_id: str) -> None:
        self.analysis = analysis
        self.snapshot_id = snapshot_id
        self.sections: list[ResultSection] = []
        self._section_starts = array("Q")
        self.row_count = 0
        self.max_source_line = 0
        self.ready = False

    def prepare(self) -> Iterator[None]:
        if self.ready:
            return
        self.sections.clear()
        self._section_starts = array("Q")
        self.row_count = self.max_source_line = 0
        occurrences: dict[CategoryIdentity, int] = {}
        for presentation in build_category_presentations(self.analysis):
            pattern = presentation.result.pattern
            if pattern is None:
                identity = CategoryIdentity("combined", presentation.key)
            elif presentation.key.startswith(("custom_", "regex_")):
                identity = CategoryIdentity(
                    "regex" if pattern.is_regex else "literal",
                    pattern.needle, pattern.case_sensitive,
                )
            else:
                identity = CategoryIdentity("preset", presentation.key)
            # Equivalent custom filters may appear more than once. Keep their
            # relative occurrence distinct without depending on custom_N keys.
            occurrence = occurrences.get(identity, 0)
            occurrences[identity] = occurrence + 1
            identity = replace(identity, occurrence=occurrence)
            section = ResultSection(presentation, identity)
            self.sections.append(section)
            self._section_starts.append(self.row_count)
            for excerpt in presentation.excerpts:
                section.row_starts.append(self.row_count)
                self.row_count += len(excerpt.lines)
                self.max_source_line = max(self.max_source_line, excerpt.lines[-1].number)
                yield None
        self.ready = True

    def _section(self, row: int) -> ResultSection:
        if not self.ready or not 0 <= row < self.row_count:
            raise IndexError(row)
        return self.sections[bisect_right(self._section_starts, row) - 1]

    def line(self, row: int) -> ResultLine:
        section = self._section(row)
        index = bisect_right(section.row_starts, row) - 1
        return section.presentation.excerpts[index].lines[row - section.row_starts[index]]

    def iter_lines(self) -> Iterator[ResultLine]:
        for section in self.sections:
            for excerpt in section.presentation.excerpts:
                yield from excerpt.lines

    def location(self, row: int) -> ResultLocation:
        return ResultLocation(
            SourceLocation(self.snapshot_id, self.line(row).number),
            self._section(row).identity,
        )

    def rows_for_source(self, source: SourceLocation) -> tuple[int, ...]:
        if not self.ready or source.snapshot_id != self.snapshot_id:
            return ()
        return tuple(
            row for section in self.sections
            if (row := section.row_for_source(source.line)) is not None
        )

    def resolve(self, location: ResultLocation | SourceLocation) -> int | None:
        """Prefer the original category, then the first surviving occurrence."""
        source = location.source if isinstance(location, ResultLocation) else location
        rows = self.rows_for_source(source)
        if isinstance(location, ResultLocation):
            for row in rows:
                if self._section(row).identity == location.category:
                    return row
        return rows[0] if rows else None
