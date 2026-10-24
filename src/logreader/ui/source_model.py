"""Direct source rows over the document session's immutable snapshot."""

from ..core import ResultLine
from .results.results_model import ResultLocation


class SourcePresentation:
    ready = True

    def __init__(self, lines: tuple[str, ...], total_line_count: int, snapshot_id: str):
        if total_line_count < len(lines):
            raise ValueError("Source line count cannot be smaller than retained lines")
        self.lines = lines
        self.row_count = len(lines)
        self.max_source_line = total_line_count
        self.first_line = total_line_count - len(lines) + 1
        self.snapshot_id = snapshot_id

    @property
    def logical(self):
        return self

    def entry(self, row):
        return row

    def line(self, row):
        if not 0 <= row < self.row_count:
            raise IndexError(row)
        return ResultLine(self.first_line + row, self.lines[row])

    def display_row(self, row):
        return row

    def iter_lines(self):
        for row in range(self.row_count):
            yield self.line(row)

    def resolve(self, location):
        source = location.source if isinstance(location, ResultLocation) else location
        if source.snapshot_id != self.snapshot_id:
            return None
        row = source.line - self.first_line
        return row if 0 <= row < self.row_count else None
