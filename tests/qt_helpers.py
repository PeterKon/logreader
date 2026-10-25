"""Event-loop helpers for tests that need a loaded document or held analysis."""

from contextlib import contextmanager
import os
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QThreadPool
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from logreader.document_session import LoadPhase
from logreader.workers.load_worker import LoadWorker
from logreader.workers.work_queue import WorkQueue


def trigger_pattern_action(pattern_list, index, text):
    chosen = []

    def choose(menu, position):
        for action in menu.actions():
            if action.text() == text:
                chosen.append(text)
                action.trigger()

    row = pattern_list.itemWidget(pattern_list.item(index))
    with patch("logreader.ui.filter_panel.TitleMenu.exec", new=choose):
        row.customContextMenuRequested.emit(QPoint(3, 3))
    if chosen != [text]:
        raise AssertionError(f"Pattern menu did not offer {text!r}")


def qt_application():
    app = QApplication.instance() or QApplication([])
    if os.name == "nt" and app.platformName() == "offscreen" and not app.property("testFontsLoaded"):
        # Windows' offscreen plugin does not discover the desktop fonts.
        for name in ("segoeui.ttf", "segoeuib.ttf", "cour.ttf", "consola.ttf", "consolab.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        app.setFont(QFont("Segoe UI", 9))
        app.setProperty("testFontsLoaded", True)
    return app


def retire_window(window):
    app = QApplication.instance()
    app.removeEventFilter(window)
    window.close()
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    window.deleteLater()
    retire_results()


def wait_source(view):
    source = view.source_view
    if not view.source_active or not source.isVisible():
        return
    for _ in range(2000):
        QTest.qWait(2)
        loader = source.loader
        if loader.error:
            raise AssertionError(loader.error)
        if (source.editor.navigation.pending is None and not loader.timer.isActive()
                and loader.buffer is None and not source.is_searching
                and not source._visible_timer.isActive()):
            return
    raise AssertionError("Source did not settle")


def wait_for_load(page):
    for _ in range(500):
        if page.session.load_phase is not LoadPhase.LOADING and not any(
            isinstance(worker, LoadWorker) for worker in page._workers.values()
        ):
            return
        QTest.qWait(10)
    raise AssertionError("File loading did not finish")


@contextmanager
def capture_analysis(workers):
    submit = WorkQueue.submit

    def dispatch(queue, worker):
        if isinstance(worker, LoadWorker):
            submit(queue, worker)
        else:
            worker.signals.started.emit(worker.request_id)
            workers.append(worker)

    with patch.object(WorkQueue, "submit", new=dispatch):
        yield


def wait_for_search(widget):
    from logreader.ui.results.results_view import ResultsView
    views = [widget] if isinstance(widget, ResultsView) else widget.findChildren(ResultsView)
    for _ in range(1000):
        if all(not view.is_searching and not view._visible_timer.isActive()
               and view.editor.navigation.pending is None
               for view in views):
            return
        QTest.qWait(5)
    raise AssertionError("Results search did not finish")


def wait_for_render(view):
    for _ in range(2000):
        if not view.is_rendering:
            return
        QTest.qWait(5)
    raise AssertionError("Results did not finish loading")


def wait_for_navigation(view):
    for _ in range(2000):
        QTest.qWait(2)
        if view.editor.navigation.pending is None:
            return
    raise AssertionError("Destination did not become ready")


def retire_results():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def render_results(view, lines, *, complete=True):
    from logreader.config import LogreaderConfig
    from logreader.core import analyze_lines
    config = LogreaderConfig(context=0, combined_view=True, enabled_patterns=(), regex_patterns=(".*",))
    view.window().show()
    QCoreApplication.processEvents()
    lines = tuple(lines)
    view.set_source(lines, len(lines))
    if not complete:
        def hold_background():
            view.loader.background = False
        view.results_prepared.connect(hold_background)
    view.start_rendering(1, "test.log", analyze_lines(lines, config.search_patterns(), combined=True), config)
    if complete:
        wait_for_render(view)
    else:
        for _ in range(2000):
            if view.results_ready and view._renderer is None:
                break
            QTest.qWait(2)
        else:
            raise AssertionError("Results were not prepared")
        view.results_prepared.disconnect(hold_background)
    return view.editor
