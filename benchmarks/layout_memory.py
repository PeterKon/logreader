"""Isolate repeated-search memory from Qt block layout and undo history.

Run each mode in a fresh process. --qt-path can select an already prepared,
isolated PySide6/shiboken6 directory without changing installed dependencies.
"""

import argparse
import gc
import json
import os
from pathlib import Path
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("searches", "scan-only", "layout-only", "empty-rehighlight"),
                        default="searches")
    parser.add_argument("--qt-path")
    parser.add_argument("--platform", default="offscreen")
    parser.add_argument("--undo-enabled", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.qt_path:
        sys.path.insert(0, str(Path(args.qt_path).resolve()))
    os.environ["QT_QPA_PLATFORM"] = args.platform

    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, qVersion
    from PySide6.QtWidgets import QApplication
    from documents import memory_mib
    from search_storage import storage_bytes
    from logreader.config import LogreaderConfig, PAIRED_PATTERN_KEYS
    from logreader.core import analyze_lines
    from logreader.results_view import ResultsView

    app = QApplication([])
    view = ResultsView()
    view.resize(1080, 760)
    view.show()
    view.set_line_wrapping(False)
    view.editor.setUndoRedoEnabled(args.undo_enabled)
    highlighter = view._search_highlighter
    rows = []

    def wait(done):
        started = perf_counter()
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: loop.quit() if done() or perf_counter() - started > 90 else None)
        timer.start()
        loop.exec()
        timer.stop()
        assert done(), "Timed out"

    def snapshot(stage):
        app.processEvents()
        gc.collect()
        document = view.editor.document()
        rows.append({"stage": stage, **memory_mib(), "blocks": document.blockCount(),
                     "matches": len(view._search_matches), "undo_steps": document.availableUndoSteps(),
                     "python_search_mib": storage_bytes((view._search_matches,
                         highlighter._painted_blocks, highlighter._fresh_blocks)) / 2**20})

    levels = ("ERROR:", "ERROR", "WARNING:", "WARNING", "EXCEPTION:", "EXCEPTION")
    lines = tuple(f"{i:08d} {levels[i % 6]} " + "x" * 200 for i in range(6000))
    config = LogreaderConfig(context=3, enabled_patterns=PAIRED_PATTERN_KEYS,
                             separate_entries=False, combined_view=False)
    analysis = analyze_lines(lines, config.search_patterns(), combined=False)
    view.start_rendering(1, "synthetic", analysis, config)
    wait(lambda: not view.is_rendering)
    snapshot("rendered")
    assert view.editor.document().blockCount() == 36015
    if not args.undo_enabled:
        assert view.editor.document().availableUndoSteps() == 0

    if args.mode in ("searches", "scan-only"):
        if args.mode == "scan-only":
            # Diagnostic control only: keep scanning, storage, and markers but
            # suppress the native rehighlight operation. Never used by the app.
            highlighter.rehighlightBlock = lambda block: None
        for cycle in (1, 2):
            for query in ("error", "warning", "exception"):
                stage = f"cycle {cycle} {query}"
                view._search_input.setText(query)
                view.search_results()
                wait(lambda: not view.is_searching and not highlighter._highlight_timer.isActive())
                assert len(view._search_matches) > 0
                snapshot(stage)
                bar = view.editor.verticalScrollBar()
                for fraction in (.25, .65, 1., 0.):
                    bar.setValue(int(bar.maximum() * fraction))
                    app.processEvents()
                    view.editor.viewport().repaint()
                    app.processEvents()
                wait(lambda: not highlighter._highlight_timer.isActive())
                snapshot(stage + " scrolled")
                view._search_input.clear()
                wait(lambda: not highlighter._highlight_timer.isActive())
                assert not view._search_matches
                snapshot(stage + " query cleared")
    else:
        document = view.editor.document()
        block = document.begin()
        while block.isValid():
            if args.mode == "layout-only":
                document.documentLayout().ensureBlockLayout(block)
            else:
                highlighter.rehighlightBlock(block)
            block = block.next()
        snapshot(args.mode)

    view.reset_for_loaded_file("synthetic")
    wait(lambda: not highlighter._highlight_timer.isActive())
    snapshot("rendered document cleared; source and analysis retained")
    report = {"qt": qVersion(), "python": sys.version.split()[0], "platform": app.platformName(),
              "mode": args.mode, "undo_enabled": args.undo_enabled,
              "source_lines": len(lines), "displayed_result_lines": 35994, "measurements": rows}
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
