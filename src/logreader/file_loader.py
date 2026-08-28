"""Deterministic file loading and decoding for Logreader."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LoadedLog:
    """Decoded log contents together with the encoding that was selected."""

    lines: tuple[str, ...]
    encoding: str


class LogDecodeError(UnicodeError):
    """Raised when a file does not match any supported text encoding."""


def load_log(source_path: str | Path) -> LoadedLog:
    """Read and decode a log file using Logreader's explicit encoding policy."""

    data = Path(source_path).read_bytes()
    text, encoding = decode_log_bytes(data)
    return LoadedLog(lines=tuple(text.splitlines()), encoding=encoding)


def decode_log_bytes(data: bytes) -> tuple[str, str]:
    """Decode bytes using BOM detection, UTF-8, then Windows-1252."""

    bom_encodings = (
        (codecs.BOM_UTF32_LE, "utf-32", "UTF-32 LE"),
        (codecs.BOM_UTF32_BE, "utf-32", "UTF-32 BE"),
        (codecs.BOM_UTF8, "utf-8-sig", "UTF-8 with BOM"),
        (codecs.BOM_UTF16_LE, "utf-16", "UTF-16 LE"),
        (codecs.BOM_UTF16_BE, "utf-16", "UTF-16 BE"),
    )
    for byte_order_mark, codec, label in bom_encodings:
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
