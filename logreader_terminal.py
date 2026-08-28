"""Terminal and plain-text report rendering for Logreader."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import TextIO

from logreader_config import APP_VERSION, LogreaderConfig
from logreader_core import AnalysisResult, CategoryResult, ResultLine


SEPARATOR = "-------->"
RULE = "------------------------------------------------"
ANSI_RESET = "\033[0m"
ANSI_COLORS = {
    "red": "31",
    "green": "32",
    "blue": "34",
}


def render_report(
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
    *,
    color: bool = False,
) -> str:
    """Render a complete report, optionally using ANSI terminal colors."""

    output = [f"\n{APP_VERSION}\n", f"Filename:\n{source_name}\n"]
    output.extend(_render_summary(analysis, config))
    output.extend(
        [
            "",
            f"Printed with context of:                 {config.context}",
            f"Lines in file:                           {analysis.line_count}",
            "",
        ]
    )

    for key, result in analysis.categories.items():
        output.extend(_render_category(key, result, config, color=color))

    return "\n".join(output) + "\n"


def print_report(
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
    *,
    stream: TextIO | None = None,
    color: bool | None = None,
) -> None:
    """Write a report, automatically using color when the stream supports it."""

    output_stream = stream if stream is not None else sys.stdout
    use_color = _stream_supports_color(output_stream) if color is None else color
    output_stream.write(render_report(source_name, analysis, config, color=use_color))


def _stream_supports_color(stream: TextIO) -> bool:
    """Return whether ANSI colors can safely be written to a stream."""

    if os.environ.get("NO_COLOR") is not None:
        return False

    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError):
        return False

    if os.environ.get("TERM") == "dumb":
        return False
    if os.name != "nt":
        return True
    return _enable_windows_virtual_terminal(stream)


def _enable_windows_virtual_terminal(stream: TextIO) -> bool:
    """Enable ANSI processing for a Windows console, if supported."""

    try:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_console_mode = kernel32.GetConsoleMode
        get_console_mode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_console_mode.restype = wintypes.BOOL
        set_console_mode = kernel32.SetConsoleMode
        set_console_mode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        set_console_mode.restype = wintypes.BOOL

        mode = wintypes.DWORD()
        if not get_console_mode(handle, ctypes.byref(mode)):
            return False

        enable_virtual_terminal_processing = 0x0004
        if mode.value & enable_virtual_terminal_processing:
            return True
        return bool(
            set_console_mode(
                handle,
                mode.value | enable_virtual_terminal_processing,
            )
        )
    except (AttributeError, OSError, ValueError):
        return False


def write_report(
    output_path: str | Path,
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> None:
    """Write a color-free report to a text file."""

    Path(output_path).write_text(
        render_report(source_name, analysis, config, color=False),
        encoding="utf-8",
    )


def _render_summary(
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> list[str]:
    summary_order = (
        "error_colon",
        "error",
        "warning",
        "failed",
        "fatal",
        "failure",
        "illegal",
        "invalid",
        "exception",
        "critical",
    )
    output = []
    for key in summary_order:
        if key not in analysis.categories:
            continue
        label = config.label_for(key)
        prefix = f'Number of "{label}" in this file'
        output.append(f"{prefix:<45}{analysis.category(key).match_count}")

    for key, result in analysis.categories.items():
        if not key.startswith("custom_"):
            continue
        output.extend(
            [
                "",
                f"Custom pattern: {config.label_for(key)}",
                f"Hits on pattern:                         {result.match_count}",
            ]
        )
    return output


def _render_category(
    key: str,
    result: CategoryResult,
    config: LogreaderConfig,
    *,
    color: bool,
) -> list[str]:
    label = config.label_for(key)
    heading = (
        f"Pattern searched: {label}"
        if key.startswith("custom_")
        else f'"{label}" contained:'
    )
    output = [RULE, heading, RULE]

    is_limited = config.limit is not None and result.match_count > config.limit
    matches_rendered = 0
    stop_after_context = False

    for excerpt in result.excerpts:
        for line in excerpt.lines:
            if line.is_match:
                if is_limited and matches_rendered >= config.limit:
                    stop_after_context = True
                    break
                matches_rendered += 1
            output.append(_render_line(line, result.pattern.needle, color=color))

        if stop_after_context:
            break
        if is_limited and matches_rendered >= config.limit:
            break
        if config.show_separator_for(key):
            output.append(SEPARATOR)

    if is_limited:
        message = (
            f"Limited, showing {config.limit} out of "
            f"{result.match_count} elements."
        )
    else:
        message = f"Printed all {result.match_count} elements."
    output.extend([_ansi(message, "blue", bold=True, enabled=color), ""])
    return output


def _render_line(line: ResultLine, needle: str, *, color: bool) -> str:
    line_number = f"{line.number:<7}->"
    if not line.is_match:
        return f"{_ansi(line_number, 'blue', bold=True, enabled=color)} {line.text}"

    match = re.search(re.escape(needle), line.text, re.IGNORECASE)
    if match is None:
        return f"{_ansi(line_number, 'blue', bold=True, enabled=color)} {line.text}"

    before = line.text[: match.start()]
    matched = line.text[match.start() : match.end()]
    after = line.text[match.end() :]
    return "".join(
        (
            _ansi(line_number, "red", bold=True, enabled=color),
            " ",
            _ansi(before, "green", enabled=color),
            _ansi(matched, "red", enabled=color),
            _ansi(after, "green", enabled=color),
        )
    )


def _ansi(
    text: str,
    color: str,
    *,
    bold: bool = False,
    enabled: bool,
) -> str:
    if not enabled or not text:
        return text
    codes = [ANSI_COLORS[color]]
    if bold:
        codes.insert(0, "1")
    return f"\033[{';'.join(codes)}m{text}{ANSI_RESET}"
