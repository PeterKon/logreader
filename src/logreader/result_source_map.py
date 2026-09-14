"""Compact, renderer-owned association between excerpts and source lines."""

from array import array
from bisect import bisect_right


class ResultSourceMap:
    def __init__(self) -> None:
        self.starts = array("Q")
        self.lengths = array("Q")
        self.source_lines = array("Q")
        self.header_blocks = 0

    def clear(self) -> None:
        self.starts = array("Q")
        self.lengths = array("Q")
        self.source_lines = array("Q")
        self.header_blocks = 0

    def append(self, block: int, length: int, source_line: int) -> None:
        self.starts.append(block)
        self.lengths.append(length)
        self.source_lines.append(source_line)

    def source_line(self, block: int) -> int | None:
        block -= self.header_blocks
        index = bisect_right(self.starts, block) - 1
        if index < 0 or block >= self.starts[index] + self.lengths[index]:
            return None
        return self.source_lines[index] + block - self.starts[index]
