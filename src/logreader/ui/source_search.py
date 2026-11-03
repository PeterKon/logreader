"""Bounded Qt-compatible literal scanning over a retained source snapshot."""

from typing import Iterable

from PySide6.QtGui import QTextDocument

from ..search_storage import SEARCH_CHUNK_CHARACTERS, SourceMatches, utf16_length


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
