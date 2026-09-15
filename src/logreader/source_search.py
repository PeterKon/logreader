"""Bounded Qt-compatible literal scanning over a retained source snapshot."""

from array import array
from typing import Iterable

from PySide6.QtGui import QTextDocument


SEARCH_CHUNK_CHARACTERS = 4096


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


class SourceMatches:
    """Packed source indexes and UTF-16 columns; no source text copies."""

    def __init__(self) -> None:
        self.lines = array("Q")
        self.starts = array("Q")
        self.ends = array("Q")

    def __len__(self) -> int:
        return len(self.lines)

    def append(self, line: int, start: int, end: int) -> None:
        self.lines.append(line)
        self.starts.append(start)
        self.ends.append(end)


def iter_source_matches(lines: Iterable[str], query: str):
    """Yield matches and checkpoints, including on long unmatched lines.

    Use the same Qt literal/case handling as results search. Scratch documents
    contain only bounded slices, never the retained file. Overlap preserves
    matches at slice boundaries; UTF-16 offsets preserve supplementary text.
    """
    if not query:
        return
    scratch = QTextDocument()
    scratch.setUndoRedoEnabled(False)
    for index, line in enumerate(lines):
        position = base = accepted_end = 0
        while position < len(line):
            boundary = min(position + SEARCH_CHUNK_CHARACTERS, len(line))
            end = min(boundary + len(query) - 1, len(line))
            boundary_units = utf16_length(line[position:boundary])
            scratch.setPlainText(line[position:end])
            local_position = max(0, accepted_end - base)
            while True:
                match = scratch.find(query, local_position)
                if match.isNull() or match.selectionStart() >= boundary_units:
                    break
                accepted_end = base + match.selectionEnd()
                yield index, base + match.selectionStart(), accepted_end
                local_position = match.selectionEnd()
            base += boundary_units
            position = boundary
            yield None
        # Empty lines also give the controller a cancellation opportunity.
        yield None
