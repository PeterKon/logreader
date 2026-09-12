"""Deterministic file loading and decoding for Logreader."""

from __future__ import annotations

import codecs
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from .cancellation import CancellationToken, checked


DEFAULT_MAX_LINES_SCANNED = 1_000_000
READ_CHUNK_BYTES = 64 * 1024
_LINE_END = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
_BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32", "UTF-32 LE"),
    (codecs.BOM_UTF32_BE, "utf-32", "UTF-32 BE"),
    (codecs.BOM_UTF8, "utf-8-sig", "UTF-8 with BOM"),
    (codecs.BOM_UTF16_LE, "utf-16", "UTF-16 LE"),
    (codecs.BOM_UTF16_BE, "utf-16", "UTF-16 BE"),
)


@dataclass(frozen=True, slots=True)
class LoadedLog:
    """Decoded log contents together with the encoding that was selected."""

    lines: tuple[str, ...]
    encoding: str
    total_line_count: int | None = None

    def __post_init__(self) -> None:
        if self.total_line_count is None:
            object.__setattr__(self, "total_line_count", len(self.lines))
        if self.total_line_count < len(self.lines):
            raise ValueError("Source line count cannot be smaller than retained lines")


class LogDecodeError(UnicodeError):
    """Raised when a file does not match any supported text encoding."""


def load_log(
    source_path: str | Path,
    *,
    max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED,
    cancellation: CancellationToken | None = None,
) -> LoadedLog:
    """Count all source lines while retaining only the requested tail.

    Decode bounded byte chunks using the existing encoding and splitlines policy.
    A late UTF-8 failure restarts from the same file handle as Windows-1252.
    """

    if isinstance(max_lines_scanned, bool) or not isinstance(max_lines_scanned, int) or max_lines_scanned < 1:
        raise ValueError("Max lines scanned must be a positive integer")
    if cancellation is not None:
        cancellation.check()
    with Path(source_path).open("rb") as stream:
        prefix = stream.read(4)
        for bom, codec, label in _BOM_ENCODINGS:
            if prefix.startswith(bom):
                try:
                    return _read_tail(stream, codec, label, max_lines_scanned, cancellation)
                except UnicodeDecodeError as error:
                    raise LogDecodeError(f"Invalid {label} text: {error}") from error
        try:
            return _read_tail(stream, "utf-8", "UTF-8", max_lines_scanned, cancellation)
        except UnicodeDecodeError:
            pass
        # Leave the exception scope before retrying, releasing the failed scan.
        try:
            return _read_tail(stream, "cp1252", "Windows-1252", max_lines_scanned, cancellation)
        except UnicodeDecodeError as error:
            raise LogDecodeError(
                "File is not valid UTF-8, UTF-16/32 with a byte-order mark, "
                "or Windows-1252 text."
            ) from error


def _read_tail(
    stream: BinaryIO, codec: str, label: str, limit: int,
    cancellation: CancellationToken | None,
) -> LoadedLog:
    stream.seek(0)
    tail: deque[str] = deque(maxlen=limit)
    count = 0
    for line in checked(_iter_decoded_lines(stream, codec, cancellation), cancellation):
        tail.append(line)
        count += 1
    if cancellation is not None:
        cancellation.check()
    loaded = LoadedLog(tuple(tail), label, count)
    if cancellation is not None:
        cancellation.check()
    return loaded


def _iter_decoded_lines(
    stream: BinaryIO, codec: str, cancellation: CancellationToken | None,
) -> Iterator[str]:
    """Match str.splitlines(), including CRLF and Unicode boundaries in chunks."""
    decoder = codecs.getincrementaldecoder(codec)()
    fragments: list[str] = []
    pending_cr = ""
    while True:
        if cancellation is not None:
            cancellation.check()
        data = stream.read(READ_CHUNK_BYTES)
        text = pending_cr + decoder.decode(data, final=not data)
        pending_cr = ""
        if data and text.endswith("\r"):
            text, pending_cr = text[:-1], "\r"
        start = 0
        for end in checked(_LINE_END.finditer(text), cancellation):
            fragments.append(text[start:end.start()])
            line = "".join(fragments)
            fragments.clear()
            yield line
            start = end.end()
        if start < len(text):
            fragments.append(text[start:])
        if not data:
            break
    if fragments:
        yield "".join(fragments)


def decode_log_bytes(data: bytes) -> tuple[str, str]:
    """Decode bytes using BOM detection, UTF-8, then Windows-1252."""

    for byte_order_mark, codec, label in _BOM_ENCODINGS:
        if data.startswith(byte_order_mark):
            try:
                return data.decode(codec), label
            except UnicodeDecodeError as error:
                raise LogDecodeError(f"Invalid {label} text: {error}") from error

    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass

    try:
        return data.decode("cp1252"), "Windows-1252"
    except UnicodeDecodeError as error:
        raise LogDecodeError(
            "File is not valid UTF-8, UTF-16/32 with a byte-order mark, "
            "or Windows-1252 text."
        ) from error
