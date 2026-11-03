"""Compact display index over logical result rows and structural rows."""
from bisect import bisect_right
from dataclasses import dataclass
from logreader.core import COMBINED_CATEGORY_KEY, ResultLine
from .result_formatting import CategoryLabel, result_label, summary_operations

@dataclass(frozen=True, slots=True)
class Fragment:
    text: str
    role: str
    bold: bool
    pattern_key: str | None


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
        self.match_labels: dict[str, str] = {}
        self._label_fragments = {}
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
        self.match_labels.clear()
        self._label_fragments.clear()
        self._decorations(self.header_operations)
        summary_start = len(self.runs)
        self._decorations(summary_operations(model.analysis, config), "summary")
        if len(self.runs) > summary_start:
            self.runs[summary_start].first = True
            self.runs[-1].last = True
        for section in model.sections:
            presentation = section.presentation
            if presentation.key == COMBINED_CATEGORY_KEY:
                self._decorations([("\n", "body", False)])
            else:
                self._decorations([("\n", "heading", True), CategoryLabel(presentation.key, "heading"),
                                   (presentation.heading("") + "\n\n", "heading", True)])
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
        for operation in operations:
            key = None
            if isinstance(operation, CategoryLabel):
                if operation.key.startswith(("custom_", "regex_")):
                    self._label_fragments.setdefault(operation.key, []).append(
                        (self.row_count, len(fragments), operation)
                    )
                name = result_label(operation.key, self.config)
                if operation.count:
                    key = operation.key
                    self.match_labels[key] = name
                pieces = operation.fragments(name)
            else:
                pieces = (operation,)
            for text, role, bold in pieces:
                parts = text.split("\n")
                for index, part in enumerate(parts):
                    if part:
                        fragments.append(Fragment(part, role, bold, key))
                    if index < len(parts) - 1:
                        self._append(Decoration(fragments, kind))
                        fragments = []
        if fragments:
            self._append(Decoration(fragments, kind))

    def rename_category(self, key, name):
        # Keep display row addresses stable for selections, bookmarks and the sparse loader.
        changed = []
        for row, index, label in self._label_fragments.get(key, ()):
            if label.role == "hit_count":
                self.match_labels[key] = name
            fragments = self.entry(row).fragments
            replacement = Fragment(*label.fragment(name), fragments[index].pattern_key)
            if fragments[index] != replacement:
                fragments[index] = replacement
                changed.append(row)
        return changed

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
        return ResultLine(0, "".join(fragment.text for fragment in entry.fragments))

    def resolve(self, location):
        row = self.logical.resolve(location)
        return self.display_row(row) if row is not None else None
