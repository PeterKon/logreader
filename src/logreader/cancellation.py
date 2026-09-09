"""Thread-safe cooperative cancellation without any Qt dependency."""

from threading import Event
from typing import Iterable, Iterator, TypeVar


class AnalysisCancelled(Exception):
    """The caller no longer needs this analysis."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.is_cancelled:
            raise AnalysisCancelled()


T = TypeVar("T")


def checked(items: Iterable[T], token: CancellationToken | None) -> Iterator[T]:
    """Check between work items; cannot interrupt an executing regex or sort."""
    if token is None:
        yield from items
        return
    iterator = iter(items)
    while True:
        token.check()
        try:
            item = next(iterator)
        except StopIteration:
            token.check()
            return
        token.check()
        yield item
