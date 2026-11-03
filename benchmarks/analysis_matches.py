"""Measure pure analysis time and retained Python allocations for pattern hits."""

import gc
import json
import platform
import sys
import tracemalloc
from statistics import median
from time import perf_counter

from logreader.core import SearchPattern, analyze_lines


LINE_COUNT = 20_000
REPEATS = 7
MATCHING_LINE = "retry=42 retry=7"
OTHER_LINE = "unrelated"
PATTERNS = (
    SearchPattern("prefix", "retry"),
    SearchPattern("full", r"retry=\d+", is_regex=True),
    SearchPattern("number", r"\d+", is_regex=True),
)


def measure(stride, combined):
    lines = tuple(MATCHING_LINE if i % stride == 0 else OTHER_LINE for i in range(LINE_COUNT))
    matching_lines = (LINE_COUNT + stride - 1) // stride
    warmup = analyze_lines(lines, PATTERNS, combined=combined)
    assert warmup.category_match_counts == {p.key: matching_lines for p in PATTERNS}
    del warmup

    timings = []
    for _ in range(REPEATS):
        gc.collect()
        start = perf_counter()
        result = analyze_lines(lines, PATTERNS, combined=combined)
        timings.append((perf_counter() - start) * 1000)
        del result

    # Trace a separate run while the finished result is still held.
    gc.collect()
    tracemalloc.start()
    try:
        result = analyze_lines(lines, PATTERNS, combined=combined)
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "stride": stride,
        "combined": combined,
        "matching_lines_per_pattern": matching_lines,
        "accepted_occurrences": matching_lines * 2 * len(PATTERNS),
        "median_ms": round(median(timings), 3),
        "times_ms": [round(t, 3) for t in timings],
        "retained_bytes": retained,
        "peak_bytes": peak,
    }


if __name__ == "__main__":
    print(json.dumps({
        "python": sys.version,
        "platform": platform.platform(),
        "repeats": REPEATS,
        "line_count": LINE_COUNT,
        "matching_line": MATCHING_LINE,
        "other_line": OTHER_LINE,
        "patterns": [{"key": p.key, "needle": p.needle, "is_regex": p.is_regex} for p in PATTERNS],
        "context": 0,
        "line_offset": 0,
        "cases": [measure(stride, combined) for stride in (100, 1) for combined in (True, False)],
    }, indent=2))
