"""Compact search positions and sparse highlight state, independent of Qt."""

from array import array
from collections.abc import Iterator, Sequence


class SearchMatches(Sequence[tuple[int, int]]):
    """Ordered UTF-16 start/end positions, shared after scanning without copying.

    The scanner owns append access until it hands this object to the view and
    highlighter. Separate arrays allow binary searches without allocating pairs
    or invoking a Python key function for each comparison.
    """

    __slots__ = ("starts", "ends")

    def __init__(self) -> None:
        self.starts = array("Q")
        self.ends = array("Q")

    def append(self, start: int, end: int) -> None:
        self.starts.append(start)
        self.ends.append(end)

    def __len__(self) -> int:
        return len(self.starts)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(zip(self.starts[index], self.ends[index]))
        return self.starts[index], self.ends[index]


class BlockSet:
    """Set of nonnegative block numbers, packed into sparse 256-bit pages.

    Space follows occupied pages, not the highest block number. Clearing a query
    never requires allocating or scanning flags for every line in the document.
    """

    __slots__ = ("_pages", "_count")

    def __init__(self) -> None:
        self._pages: dict[int, int] = {}
        self._count = 0

    def __len__(self) -> int:
        return self._count

    def __contains__(self, number: int) -> bool:
        return bool(self._pages.get(number >> 8, 0) & (1 << (number & 255)))

    def add(self, number: int) -> None:
        page = number >> 8
        mask = 1 << (number & 255)
        old = self._pages.get(page, 0)
        if not old & mask:
            self._pages[page] = old | mask
            self._count += 1

    def discard(self, number: int) -> None:
        page = number >> 8
        mask = 1 << (number & 255)
        old = self._pages.get(page, 0)
        if old & mask:
            remaining = old & ~mask
            if remaining:
                self._pages[page] = remaining
            else:
                del self._pages[page]
            self._count -= 1

    def clear(self) -> None:
        self._pages.clear()
        self._count = 0

    def __iter__(self) -> Iterator[int]:
        return self._numbers(self._pages.items())

    def ordered_snapshot(self) -> Iterator[int]:
        """Snapshot pages now; expand their numbers in later highlight batches.

        Copying one entry per occupied page avoids unpacking every highlighted
        line synchronously when the user edits a query. Immutable page values
        keep the snapshot stable while highlighting changes the live set.
        """
        return self._numbers(sorted(self._pages.items()))

    @staticmethod
    def _numbers(pages) -> Iterator[int]:
        for page, bits in pages:
            if bits == (1 << 256) - 1:
                yield from range(page << 8, (page + 1) << 8)
                continue
            while bits:
                lowest = bits & -bits
                yield (page << 8) + lowest.bit_length() - 1
                bits ^= lowest
