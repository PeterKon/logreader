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
CANCELLATION_CHECK_INTERVAL = 256


def checked(items: Iterable[T], token: CancellationToken | None) -> Iterator[T]:
    """Poll once per batch, without polling empty inner loops.

    Analysis entry, stage boundaries, and completion check separately. Native
    iterator operations (including regex searches) must still return normally.
    """
    if token is None:
        yield from items
        return
    remaining = 0
    for item in items:
        if remaining == 0:
            token.check()
            remaining = CANCELLATION_CHECK_INTERVAL
        remaining -= 1
        yield item
