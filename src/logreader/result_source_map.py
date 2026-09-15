"""Transient Qt block projection of logical result rows and source numbers."""

from array import array
from bisect import bisect_right


class ResultSourceMap:
    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.starts = array("Q")
        self.lengths = array("Q")
        self.source_lines = array("Q")
        self.rows = array("Q")
        self.header_blocks = 0
        self.row_count = 0

    def append(self, block: int, length: int, source_line: int) -> None:
        self.starts.append(block)
        self.lengths.append(length)
        self.source_lines.append(source_line)
        self.rows.append(self.row_count)
        self.row_count += length

    def source_line(self, block: int) -> int | None:
        block -= self.header_blocks
        index = bisect_right(self.starts, block) - 1
        if index < 0 or block >= self.starts[index] + self.lengths[index]:
            return None
        return self.source_lines[index] + block - self.starts[index]

    def row(self, block: int) -> int | None:
        block -= self.header_blocks
        index = bisect_right(self.starts, block) - 1
        if index < 0 or block >= self.starts[index] + self.lengths[index]:
            return None
        return self.rows[index] + block - self.starts[index]

    def block(self, row: int) -> int | None:
        if not 0 <= row < self.row_count:
            return None
        index = bisect_right(self.rows, row) - 1
        return self.header_blocks + self.starts[index] + row - self.rows[index]
