"""Compact logical/native index for retained result ranges."""

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    loaded: bool
    guard_before: bool = False

    @property
    def blocks(self):
        return self.end - self.start + int(self.guard_before) if self.loaded else 2


@dataclass(frozen=True, slots=True)
class UnloadedGap:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class RetainedBoundary:
    row: int


class RangeIndex:
    def __init__(self, total):
        self.total = total
        self.spans = [Span(0, total, False)] if total else []
        self._index()

    def _index(self):
        self.starts, self.native_starts = [], []
        self.block_count = self.loaded_count = 0
        for span in self.spans:
            self.starts.append(span.start)
            self.native_starts.append(self.block_count)
            self.block_count += span.blocks
            if span.loaded:
                self.loaded_count += span.end - span.start

    @property
    def loaded_ranges(self):
        ranges = []
        for span in self.spans:
            if span.loaded:
                if ranges and ranges[-1][1] == span.start:
                    ranges[-1] = (ranges[-1][0], span.end)
                else:
                    ranges.append((span.start, span.end))
        return ranges

    @property
    def guard_count(self):
        return sum(s.guard_before for s in self.spans)

    @property
    def gaps(self):
        return [(s.start, s.end) for s in self.spans if not s.loaded]

    def span_at(self, row):
        if not 0 <= row < self.total:
            raise IndexError(row)
        return bisect_right(self.starts, row) - 1

    def contains(self, row):
        return 0 <= row < self.total and self.spans[self.span_at(row)].loaded

    def block_for(self, row, *, project_gap=False):
        i = self.span_at(row)
        span = self.spans[i]
        if not span.loaded:
            return self.native_starts[i] if project_gap else None
        return self.native_starts[i] + int(span.guard_before) + row - span.start

    def logical_at(self, block):
        if not 0 <= block < self.block_count:
            return None
        i = bisect_right(self.native_starts, block) - 1
        span = self.spans[i]
        if not span.loaded:
            return UnloadedGap(span.start, span.end)
        offset = block - self.native_starts[i] - int(span.guard_before)
        return RetainedBoundary(span.start) if offset < 0 else span.start + offset

    def fill(self, start, end):
        i = self.span_at(start)
        gap = self.spans[i]
        if gap.loaded or not start < end <= gap.end:
            raise ValueError("Fill must be contained in one unloaded interval")
        parts = ([Span(gap.start, start, False)] if start > gap.start else [])
        # A single invisible boundary protects the first retained line of an
        # island from Qt invalidating the block following an edited gap.
        parts.append(Span(start, end, True, guard_before=start > gap.start))
        if end < gap.end:
            parts.append(Span(end, gap.end, False))
        merged = []
        for span in self.spans[:i] + parts + self.spans[i + 1:]:
            if merged and merged[-1].loaded == span.loaded and not span.guard_before:
                merged[-1] = Span(merged[-1].start, span.end, span.loaded, merged[-1].guard_before)
            else:
                merged.append(span)
        self.spans = merged
        self._index()
        return parts
