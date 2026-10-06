"""Compact display index over logical result rows and structural rows."""
from bisect import bisect_right
from dataclasses import dataclass
from logreader.core import COMBINED_CATEGORY_KEY, ResultLine
from .result_formatting import RESULT_LABEL_OVERRIDES, _iter_analysis_render_operations

@dataclass
class Decoration:
    fragments: list
    kind: str = "structure"
    first: bool = False
    last: bool = False


class PresentationModel:
    """Index source runs and structural rows without expanding every source row."""

    def __init__(self, model, config, *, defer=False, header_operations=()):
        self._excerpt_gap = Decoration((), "gap")
        self.header_operations = header_operations
        self.logical = model
        self.config = config
        self.ready = False
        self.max_source_line = model.max_source_line
        self.row_count = 0
        self.starts, self.runs = [], []
        self.source_starts, self.display_starts = [], []
        if not defer:
            for _ in self.prepare():
                pass

    def prepare(self):
        if self.ready:
            return
        model, config = self.logical, self.config
        if not model.ready:
            raise ValueError("Prepare the logical results before indexing display rows")
        self.row_count = 0
        self.starts.clear()
        self.runs.clear()
        self.source_starts.clear()
        self.display_starts.clear()
        done = False

        def summary_done():
            nonlocal done
            done = True

        summary = []
        for operation in _iter_analysis_render_operations(
                "preview.log", model.analysis, config, model=model, on_summary=summary_done):
            if done:
                break
            summary.append(operation)
        self._decorations(self.header_operations)
        summary_start = len(self.runs)
        self._decorations(summary, "summary")
        if len(self.runs) > summary_start:
            self.runs[summary_start].first = True
            self.runs[-1].last = True
        for section in model.sections:
            presentation = section.presentation
            if presentation.key == COMBINED_CATEGORY_KEY:
                self._decorations([("\n", "body", False)])
            else:
                label = RESULT_LABEL_OVERRIDES.get(presentation.key, config.label_for(presentation.key))
                self._decorations([(f"\n{presentation.heading(label)}\n\n", "heading", True)])
            for index, excerpt in enumerate(presentation.excerpts):
                self.source_starts.append(section.row_starts[index])
                self.display_starts.append(self.row_count)
                self._append(section.row_starts[index], len(excerpt.lines))
                if config.separate_entries and index < len(presentation.excerpts) - 1:
                    self._append(Decoration([], "gap"))
                yield None
        self._append(Decoration([]))  # Full renderer's final empty block.
        self.ready = True

    def _append(self, run, count=1):
        if isinstance(run, Decoration) and run.kind == "gap":
            run = self._excerpt_gap
        self.starts.append(self.row_count)
        self.runs.append(run)
        self.row_count += count

    def _decorations(self, operations, kind="structure"):
        fragments = []
        for text, role, bold in operations:
            parts = text.split("\n")
            for index, part in enumerate(parts):
                if part:
                    fragments.append((part, role, bold))
                if index < len(parts) - 1:
                    self._append(Decoration(fragments, kind))
                    fragments = []
        if fragments:
            self._append(Decoration(fragments, kind))

    def entry(self, row):
        index = bisect_right(self.starts, row) - 1
        run = self.runs[index]
        return run + row - self.starts[index] if isinstance(run, int) else run

    def display_row(self, logical_row):
        index = bisect_right(self.source_starts, logical_row) - 1
        return self.display_starts[index] + logical_row - self.source_starts[index]

    def line(self, row):
        entry = self.entry(row)
        if isinstance(entry, int):
            return self.logical.line(entry)
        return ResultLine(0, "".join(text for text, _, _ in entry.fragments))

    def resolve(self, location):
        row = self.logical.resolve(location)
        return self.display_row(row) if row is not None else None
