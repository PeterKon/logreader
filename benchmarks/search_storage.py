"""Compare search storage and UI latency against a git revision in fresh processes."""

import argparse
import gc
import json
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
import types

from documents import distribution, memory_mib


def storage_bytes(value, seen=None):
    """Owned Python allocations, including packed array buffers; exclude Qt."""
    if seen is None:
        seen = set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(storage_bytes(k, seen) + storage_bytes(v, seen) for k, v in value.items())
    if isinstance(value, (tuple, list, set)):
        return size + sum(storage_bytes(v, seen) for v in value)
    for slot in getattr(type(value), "__slots__", ()):
        size += storage_bytes(getattr(value, slot), seen)
    return size


def reset_state_report(view):
    """Isolate synchronous reset cost without allocating a million Qt blocks.

    Populate the actual search caches and highlight bookkeeping, then call the
    real reset path. Stop its timer before any synthetic block numbers are used.
    This measures query-edit dispatch, not document painting or total memory.
    """
    from array import array

    results = []
    highlighter = view._search_highlighter
    for count in (30000, 1000000):
        timings = []
        for _ in range(5):
            if isinstance(view._search_matches, tuple):
                matches = tuple((i * 20, i * 20 + 6) for i in range(count))
            else:
                matches = type(view._search_matches)()
                for i in range(count):
                    matches.append(i * 20, i * 20 + 6)
            view._search_matches = highlighter._matches = matches
            del matches
            view._search_match_blocks = highlighter._match_blocks = array("I", range(count))
            highlighter._painted_blocks = type(highlighter._painted_blocks)()
            highlighter._fresh_blocks = type(highlighter._fresh_blocks)()
            for number in range(count):
                highlighter._painted_blocks.add(number)
                highlighter._fresh_blocks.add(number)
            gc.collect()
            started = perf_counter()
            view._clear_search_results()
            timings.append((perf_counter() - started) * 1000)
            highlighter.cancel()
            assert not view._search_matches and not highlighter._matches
        results.append({"highlighted_lines": count, "matches": count,
                        "dispatch_ms": timings, "median_ms": statistics.median(timings)})
    view.close()
    return results


def run_child(args):
    # Only replace results_view, whose dependencies are unchanged by this work.
    # The reference is read from git without changing the checkout or worktree.
    if args.implementation == "baseline":
        source = subprocess.check_output(
            ["git", "show", f"{args.reference}:src/logreader/results_view.py"], encoding="utf-8",
        )
        module = types.ModuleType("logreader.results_view")
        module.__package__ = "logreader"
        sys.modules[module.__name__] = module
        exec(compile(source, "<baseline-results_view>", "exec"), module.__dict__)

    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QApplication
    from logreader.config import LogreaderConfig
    from logreader.core import analyze_lines
    from logreader.results_view import ResultsView

    app = QApplication([])
    view = ResultsView()
    view.resize(1080, 760)
    if args.case == "reset-state":
        return {"implementation": args.implementation, "reference": args.reference,
                "case": args.case, "python": sys.version.split()[0], "pyside": qt_version,
                "qt_platform": app.platformName(), "reset_state": reset_state_report(view),
                "correctness_checks_passed": True}
    view.show()
    wrap = args.case == "dense-wrap"
    view.set_line_wrapping(wrap)
    count = 10000 if args.case == "many-hits" else 30000
    per_line = 12 if args.case == "many-hits" else 2
    every = 100 if args.case == "sparse" else 1
    source = tuple(
        f"{i:09d} ERROR: " + ("needle " * per_line if i % every == 0 else "ordinary ") + "x" * 100
        for i in range(count)
    )
    expected_count = ((count - 1) // every + 1) * per_line
    config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
    analysis = analyze_lines(source, config.search_patterns(), combined=True)
    gaps = []
    last_tick = perf_counter()

    def tick():
        nonlocal last_tick
        now = perf_counter()
        gaps.append((now - last_tick) * 1000)
        last_tick = now

    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(tick)
    heartbeat.start()

    def wait(done, timeout=90):
        start = perf_counter()
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(5)
        poll.timeout.connect(lambda: loop.quit() if done() or perf_counter() - start > timeout else None)
        poll.start()
        loop.exec()
        poll.stop()
        if not done():
            raise AssertionError("Benchmark timed out")

    def settle():
        start = perf_counter()
        wait(lambda: perf_counter() - start > .1)
        gc.collect()

    highlighter = view._search_highlighter
    bar = view.editor.verticalScrollBar()
    view.start_rendering(1, "synthetic.log", analysis, config)
    wait(lambda: not view.is_rendering)
    settle()
    report = {
        "implementation": args.implementation, "reference": args.reference, "case": args.case,
        "python": sys.version.split()[0], "pyside": qt_version, "qt_platform": app.platformName(),
        "lines": count, "expected_matches": expected_count, "rendered_memory": memory_mib(),
    }
    cursor = view.editor.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
    view.editor.setTextCursor(cursor)
    selection = (cursor.anchor(), cursor.position())
    initial_scroll = bar.value()
    scan_completed = None
    original_set_matches = highlighter.set_matches

    def observed_set_matches(matches, match_blocks=None):
        nonlocal scan_completed
        if view._searched_query == "needle" and not view.is_searching:
            scan_completed = perf_counter()
            report["scanned_memory"] = memory_mib()
        original_set_matches(matches, match_blocks)

    highlighter.set_matches = observed_set_matches
    gaps.clear()
    last_tick = perf_counter()
    started = perf_counter()
    view._search_input.setText("needle")
    view.search_results()
    wait(lambda: not view.is_searching and not highlighter._highlight_timer.isActive())
    finished = perf_counter()
    report["scan_seconds"] = scan_completed - started
    report["highlight_seconds"] = finished - scan_completed
    report["search_seconds"] = finished - started
    report["search_heartbeat"] = distribution(gaps)
    settle()
    report["searched_memory"] = memory_mib()
    report["hit_storage_bytes"] = storage_bytes(view._search_matches)
    report["block_state_bytes"] = storage_bytes((highlighter._painted_blocks, highlighter._fresh_blocks))
    assert len(view._search_matches) == expected_count
    assert view._search_matches is highlighter._matches
    assert view._search_match_blocks is bar._match_blocks
    cursor = view.editor.textCursor()
    assert (cursor.anchor(), cursor.position()) == selection
    assert bar.value() == initial_scroll
    scroll_range = bar.maximum()
    visual_lines = view.editor.document().lineCount()
    report["visual_lines"] = visual_lines
    report["scroll_max"] = scroll_range

    # Measure paint completion, not just setting a scrollbar's numeric value.
    points = [((i * 7919) % 30001) / 30000 for i in range(1, 81)]
    for label in ("first_scroll", "repeated_scroll"):
        timings = []
        for fraction in points:
            started = perf_counter()
            bar.setValue(round(scroll_range * fraction))
            app.processEvents()
            view.editor.viewport().repaint()
            app.processEvents()
            timings.append((perf_counter() - started) * 1000)
        report[label] = distribution(timings)
        assert bar.maximum() == scroll_range, "Scroll extent changed while visiting results"
        assert view.editor.document().lineCount() == visual_lines

    bar.setValue(0)
    app.processEvents()
    navigation = []
    for _ in range(100):
        started = perf_counter()
        view.find_next()
        app.processEvents()
        navigation.append((perf_counter() - started) * 1000)
    report["navigation"] = distribution(navigation)
    assert len(view.editor.extraSelections()) == 1
    report["after_scroll_memory"] = memory_mib()

    # Validate all highlight ranges against the independent synthetic workload.
    for number in view._search_match_blocks:
        block = view.editor.document().findBlockByNumber(number)
        text = block.text()
        expected = []
        position = 0
        while (position := text.find("needle", position)) >= 0:
            expected.append((position, 6))
            position += 6
        formats = block.layout().formats()
        assert [(f.start, f.length) for f in formats] == expected
        assert all(f.format == highlighter._match_format for f in formats)

    started = perf_counter()
    view._search_input.clear()
    report["clear_dispatch_ms"] = (perf_counter() - started) * 1000
    wait(lambda: not highlighter._highlight_timer.isActive())
    report["clear_seconds"] = perf_counter() - started
    assert not view._search_matches and not view.editor.extraSelections()
    for i in range(view.editor.document().blockCount()):
        assert not view.editor.document().findBlockByNumber(i).layout().formats()
    view.cancel_search()
    heartbeat.stop()
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    report["correctness_checks_passed"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="8364966")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", default="benchmarks/search-storage.json")
    parser.add_argument("--implementation", choices=("baseline", "current"))
    cases = ("dense", "dense-wrap", "many-hits", "sparse", "reset-state")
    parser.add_argument("--case", choices=cases)
    args = parser.parse_args()
    if args.implementation:
        print(json.dumps(run_child(args)))
        return
    args.reference = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.reference}^{{commit}}"], text=True,
    ).strip()
    rows = []
    for case in cases:
        for repeat in range(args.repeats):
            # Alternate execution order to reduce systematic warm-up/load bias.
            order = ("baseline", "current") if repeat % 2 == 0 else ("current", "baseline")
            for implementation in order:
                command = [sys.executable, "-B", str(Path(__file__).resolve()), "--reference", args.reference,
                           "--case", case, "--implementation", implementation]
                process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=180)
                if process.returncode:
                    raise RuntimeError(process.stdout + process.stderr)
                row = json.loads(process.stdout)
                row["repeat"] = repeat + 1
                rows.append(row)
                Path(args.output).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
                progress = {"case": case, "repeat": repeat + 1, "implementation": implementation}
                if case == "reset-state":
                    progress["reset_medians_ms"] = [r["median_ms"] for r in row["reset_state"]]
                else:
                    progress.update(search_seconds=row["search_seconds"],
                                    scroll_p95_ms=row["first_scroll"]["p95_ms"],
                                    storage_mib=(row["hit_storage_bytes"] + row["block_state_bytes"]) / 2**20)
                print(json.dumps(progress), flush=True)


if __name__ == "__main__":
    main()
