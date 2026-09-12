"""Repeatable real-Qt multi-document benchmark; run from the repository root."""

import argparse
import ctypes
import gc
import json
import os
import platform
import sys
import tempfile
import weakref
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from PySide6 import __version__ as qt_binding_version
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from logreader.config import LogreaderConfig
from logreader.document_session import AnalysisPhase, LoadPhase
from logreader.qt_app import LogreaderWindow
from logreader.work_queue import WorkQueue


def memory_mib():
    """Current resident and private committed memory, not Python-only allocations."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                    "nonpaged", "pagefile", "peak_pagefile", "private",
                )
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"rss_mib": counters.ws / 2**20, "private_mib": counters.private / 2**20}
    if sys.platform.startswith("linux"):
        resident = int(Path("/proc/self/statm").read_text().split()[1])
        return {"rss_mib": resident * os.sysconf("SC_PAGE_SIZE") / 2**20}
    return {"rss_mib": None}


def distribution(values):
    values = sorted(values)
    return {"samples": len(values), "p95_ms": values[int((len(values) - 1) * .95)] if values else None,
            "max_ms": max(values, default=None)}


class Probe:
    def __init__(self, window):
        self.window = window
        self.phase = "idle"
        self.gaps = {}
        self.switches = {}
        self.peak = memory_mib()
        self.worker_refs = []
        self.worker_times = []
        self.last = perf_counter()
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.switch_timer = QTimer()
        self.switch_timer.setInterval(100)
        self.switch_timer.timeout.connect(self.switch)

    def observe_worker(self, worker):
        self.worker_refs.append(weakref.ref(worker))
        sample = {"kind": type(worker).__name__, "submitted": perf_counter()}
        self.worker_times.append(sample)
        worker.signals.started.connect(lambda _id: sample.update(started=perf_counter()))
        worker.signals.finished.connect(lambda _id: sample.update(finished=perf_counter()))

    def tick(self):
        now = perf_counter()
        self.gaps.setdefault(self.phase, []).append((now - self.last) * 1000)
        self.last = now
        for key, value in memory_mib().items():
            if value is not None:
                self.peak[key] = max(value, self.peak.get(key, 0))

    def switch(self):
        count = self.window._tabs.count()
        if count > 1:
            start = perf_counter()
            self.window._tabs.setCurrentIndex((self.window._tabs.currentIndex() + 1) % count)
            # Includes the first opportunity to process painting after switching.
            phase = self.phase
            QTimer.singleShot(0, lambda: self.switches.setdefault(phase, []).append(
                (perf_counter() - start) * 1000))

    def wait(self, phase, done, timeout=300):
        self.phase = phase
        self.last = perf_counter()
        start = self.last
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(5)
        timed_out = False

        def check():
            nonlocal timed_out
            timed_out = perf_counter() - start > timeout
            if timed_out or done():
                loop.quit()

        poll.timeout.connect(check)
        poll.start()
        loop.exec()
        poll.stop()
        if timed_out:
            raise RuntimeError(f"Timed out during {phase}")
        return perf_counter() - start

    def settle(self):
        start = perf_counter()
        self.wait("settle", lambda: perf_counter() - start > .2)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()


def run(args):
    app = QApplication.instance() or QApplication([])
    window = LogreaderWindow()
    window.resize(1100, 800)
    window.show()
    probe = Probe(window)
    report = {"environment": {"python": platform.python_version(), "pyside": qt_binding_version,
                              "platform": platform.platform(), "qt_platform": app.platformName()},
              "parameters": vars(args), "cycles": []}
    config = LogreaderConfig(context=0, max_lines_scanned=args.max_lines_scanned, enabled_patterns=("error_colon",))
    original_submit = WorkQueue.submit

    def track_submit(queue, worker):
        probe.observe_worker(worker)
        original_submit(queue, worker)

    tracking = patch.object(WorkQueue, "submit", new=track_submit)
    tracking.start()
    try:
        with tempfile.TemporaryDirectory(prefix="logreader-benchmark-") as directory:
            paths = []
            for index in range(args.documents):
                path = Path(directory) / f"synthetic-{index}.log"
                with path.open("w", encoding="utf-8", newline="\n") as stream:
                    for line in range(args.lines):
                        stream.write(f"{line:09d} ERROR: document {index} needle needle " + "x" * 100 + "\n")
                paths.append(path)
            report["input_mib"] = sum(path.stat().st_size for path in paths) / 2**20
            probe.settle()
            report["baseline_memory"] = memory_mib()
            for cycle in range(args.cycles):
                row = {"cycle": cycle + 1}
                report["cycles"].append(row)
                worker_start = len(probe.worker_refs)
                probe.switch_timer.start()
                start = perf_counter()
                window.load_files(paths)
                row["open_dispatch_seconds"] = perf_counter() - start
                pages = [window._pages.widget(i) for i in range(args.documents)]
                refs = [weakref.ref(page) for page in pages]
                probe.wait("loading", lambda: all(p.session.load_phase != LoadPhase.LOADING for p in pages))
                row["loading_seconds"] = perf_counter() - start
                assert all(len(p.session.lines) == min(args.lines, 1_000_000) for p in pages)
                row["loaded_memory"] = memory_mib()
                for page in pages:
                    page.build_config = lambda: config
                    page.analyze()
                probe.wait("analysis", lambda: all(p.session.analysis is not None for p in pages))
                row["analysis_seconds"] = [p.session.analysis_seconds for p in pages]
                assert all(sum(c.match_count for c in p.session.analysis.categories.values()) == min(args.lines, args.max_lines_scanned)
                           for p in pages)
                row["analyzed_memory"] = memory_mib()
                row["retained_analysis_lines"] = [sum(len(excerpt.lines)
                    for category in p.session.analysis.categories.values()
                    for excerpt in category.excerpts) for p in pages]
                probe.wait("rendering", lambda: all(p.session.phase == AnalysisPhase.IDLE for p in pages))
                row["rendering_seconds"] = [p.session.rendering_seconds for p in pages]
                row["rendered_memory"] = memory_mib()
                start = perf_counter()
                for page in pages:
                    page.results_view._search_input.setText("needle")
                    page.results_view.search_results()
                row["search_dispatch_seconds"] = perf_counter() - start
                probe.wait("searching", lambda: all(not p.results_view.is_searching and
                    not p.results_view._search_highlighter._highlight_timer.isActive() for p in pages))
                row["search_seconds"] = perf_counter() - start
                expected = 2 * min(args.max_lines_scanned, args.lines)
                assert all(len(p.results_view._search_matches) == expected for p in pages)
                row["searched_memory"] = memory_mib()
                probe.switch_timer.stop()
                start = perf_counter()
                while window._tabs.count():
                    window.close_tab(window._tabs.count() - 1)
                row["close_seconds"] = perf_counter() - start
                pages.clear()
                del page
                probe.settle()
                row["closed_memory"] = memory_mib()
                row["retained_pages"] = sum(ref() is not None for ref in refs)
                row["retained_workers"] = sum(ref() is not None for ref in probe.worker_refs[worker_start:])
                row["queue_references"] = sum(len(q._pending) + (q._active is not None)
                                              for q in (window._scheduler.loading, window._scheduler.analysis))
                assert row["retained_pages"] == row["retained_workers"] == row["queue_references"] == 0
                print(json.dumps(row), flush=True)
            report["cancellation"] = []
            for phase in ("loading", "analysis", "rendering", "searching"):
                worker_start = len(probe.worker_refs)
                window.load_files(paths)
                pages = [window._pages.widget(i) for i in range(args.documents)]
                refs = [weakref.ref(page) for page in pages]
                if phase != "loading":
                    probe.wait("cancel_setup", lambda: all(p.session.has_document for p in pages))
                    for page in pages:
                        page.build_config = lambda: config
                        page.analyze()
                    if phase in ("rendering", "searching"):
                        # Hidden tabs retain analysis without consuming renderer batches.
                        probe.wait("cancel_setup", lambda: pages[0].session.analysis is not None)
                    if phase == "searching":
                        probe.switch_timer.start()
                        probe.wait("cancel_setup", lambda: all(p.session.phase == AnalysisPhase.IDLE for p in pages))
                        probe.switch_timer.stop()
                        for page in pages:
                            page.results_view._search_input.setText("needle")
                            page.results_view.search_results()
                    del page
                pending_before = sum(len(q._pending) for q in (
                    window._scheduler.loading, window._scheduler.analysis))
                start = perf_counter()
                while window._tabs.count():
                    window.close_tab(window._tabs.count() - 1)
                close_seconds = perf_counter() - start
                pages.clear()
                probe.wait("cancelling", lambda: all(q._active is None and not q._pending for q in (
                    window._scheduler.loading, window._scheduler.analysis)))
                drained_seconds = perf_counter() - start
                probe.settle()
                report["cancellation"].append({"phase": phase, "queued_before_close": pending_before,
                    "close_seconds": close_seconds, "drained_seconds": drained_seconds,
                    "retained_pages": sum(ref() is not None for ref in refs),
                    "retained_workers": sum(ref() is not None for ref in probe.worker_refs[worker_start:]),
                    "memory": memory_mib()})
                assert report["cancellation"][-1]["retained_pages"] == 0
                assert report["cancellation"][-1]["retained_workers"] == 0
        report["heartbeat_intervals"] = {key: distribution(value) for key, value in probe.gaps.items()}
        report["switch_to_event_loop"] = {key: distribution(value) for key, value in probe.switches.items()}
        report["sampled_peak_memory"] = probe.peak
        report["worker_timings"] = [
            {"kind": sample["kind"], "queue_seconds": sample.get("started", sample["finished"]) - sample["submitted"],
             "service_seconds": sample["finished"] - sample["started"] if "started" in sample else None}
            for sample in probe.worker_times
        ]
        return report
    finally:
        tracking.stop()
        probe.timer.stop()
        probe.switch_timer.stop()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=3)
    parser.add_argument("--lines", type=int, default=100000)
    parser.add_argument("--max-lines-scanned", type=int, default=10000, help="Source lines analyzed from the tail of each file")
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--output", default="benchmark-results.json")
    args = parser.parse_args()
    if min(args.documents, args.lines, args.cycles, args.max_lines_scanned) < 1:
        parser.error("Counts and max lines scanned must be positive")
    result = run(args)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.output}")
