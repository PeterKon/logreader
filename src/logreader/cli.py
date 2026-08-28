"""Standalone command-line interface for Logreader."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .config import (
    APP_VERSION,
    DEFAULT_ENABLED_PATTERNS,
    PATTERN_KEYS,
    LogreaderConfig,
)
from .core import analyze_lines
from .terminal import print_report, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract common errors and surrounding context from a log file.",
    )
    parser.add_argument("logfile", type=Path, help="log file to analyze")
    parser.add_argument(
        "--context",
        type=_non_negative_int,
        help="lines of context around all matches (default: 3)",
    )
    parser.add_argument(
        "--generic-context",
        type=_non_negative_int,
        help="override context around every pattern except ERROR:",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        help="maximum matches shown per category (default: unlimited)",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        metavar="TEXT",
        help="add a case-insensitive custom literal pattern; may be repeated",
    )
    parser.add_argument(
        "--enable",
        action="extend",
        nargs="+",
        choices=PATTERN_KEYS,
        default=list(DEFAULT_ENABLED_PATTERNS),
        metavar="PRESET",
        help="enable one or more built-in patterns",
    )
    parser.add_argument(
        "--disable",
        action="extend",
        nargs="+",
        choices=PATTERN_KEYS,
        default=[],
        metavar="PRESET",
        help="disable one or more built-in patterns",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path("outfile.txt"),
        metavar="PATH",
        help="plain-text report path (default: outfile.txt)",
    )
    parser.add_argument(
        "--no-output-file",
        action="store_true",
        help="do not write a plain-text report",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colors in terminal output",
    )
    parser.add_argument(
        "--no-separators",
        action="store_true",
        help="hide separators between ERROR: excerpts",
    )
    parser.add_argument(
        "--generic-separators",
        action="store_true",
        help="show separators between optional and custom excerpts",
    )
    parser.add_argument(
        "--encoding",
        help="input file encoding (default: operating-system default)",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    disabled = set(args.disable)
    enabled_patterns = tuple(
        pattern for pattern in args.enable if pattern not in disabled
    )
    context = 3 if args.context is None else args.context
    generic_context = (
        args.generic_context
        if args.generic_context is not None
        else context
    )
    try:
        config = LogreaderConfig(
            context=context,
            generic_context=generic_context,
            limit=args.limit,
            enabled_patterns=enabled_patterns,
            custom_patterns=tuple(args.pattern),
            show_separators=not args.no_separators,
            show_generic_separators=args.generic_separators,
        )
        with args.logfile.open("r", encoding=args.encoding) as log_file:
            lines = log_file.read().splitlines()
    except (OSError, UnicodeError, ValueError) as error:
        print(f"logreader: {error}", file=sys.stderr)
        return 2

    analysis = analyze_lines(lines, config.search_patterns())
    print_report(
        str(args.logfile),
        analysis,
        config,
        color=False if args.no_color else None,
    )

    if not args.no_output_file:
        try:
            write_report(args.output_file, str(args.logfile), analysis, config)
        except OSError as error:
            print(f"logreader: unable to write {args.output_file}: {error}", file=sys.stderr)
            return 2

    return 0


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
