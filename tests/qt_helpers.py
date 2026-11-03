"""Event-loop helpers for tests that need a loaded document or held analysis."""

from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QThreadPool, Qt
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor, QTextLine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from logreader.document_session import LoadPhase
from logreader.search_storage import utf16_length
from logreader.ui.results.results_editor import SummaryBlock
from logreader.ui.widgets.line_number_editor import GUTTER_LEFT_PADDING
from logreader.workers.load_worker import LoadWorker
from logreader.workers.work_queue import WorkQueue


# Files opened by GUI tests must never enter the user's history.
_history_dir = TemporaryDirectory()
os.environ["LOGREADER_HISTORY_DIR"] = _history_dir.name


def trigger_pattern_action(pattern_list, index, text):
    chosen = []

    def choose(menu, position):
        for action in menu.actions():
            if action.text() == text:
                chosen.append(text)
                action.trigger()

    row = pattern_list.itemWidget(pattern_list.item(index))
    with patch("logreader.ui.filter_panel.SearchPatternMenu.exec", new=choose):
        row.customContextMenuRequested.emit(QPoint(3, 3))
    if chosen != [text]:
        raise AssertionError(f"Pattern menu did not offer {text!r}")


def rename_pattern(pattern_list, index, name):
    from logreader.ui.dialogs import NameDialog

    def rename(dialog):
        dialog.name_input.setText(name)
        dialog.accept()
        return dialog.result()

    with patch.object(NameDialog, "exec", new=rename):
        trigger_pattern_action(pattern_list, index, "Rename…")


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


def wait_until(predicate):
    for _ in range(500):
        QCoreApplication.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Work did not reach the expected state")


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


def painted_character(editor, text, character=0, occurrence=0):
    """Locate a rendered structural character in editor coordinates for a real mouse event."""
    cursor = QTextCursor(editor.document())
    for _ in range(occurrence + 1):
        cursor = editor.document().find(text, cursor)
        if cursor.isNull():
            raise AssertionError(f"Could not find displayed text {text!r}")
    block = cursor.block()
    column = cursor.selectionStart() - block.position() + utf16_length(text[:character])
    line = block.layout().lineForTextPosition(column)
    left = line.cursorToX(column)[0]
    right = line.cursorToX(column, QTextLine.Edge.Trailing)[0]
    offset = editor.contentOffset()
    x = editor.gutter.x() + offset.x() + GUTTER_LEFT_PADDING - editor.document().documentMargin()
    if isinstance(block.userData(), SummaryBlock):
        x += 6
    y = editor.viewport().y() + editor.blockBoundingGeometry(block).top() + offset.y()
    return QPoint(round(x + (left + right) / 2), round(y + line.naturalTextRect().center().y()))


def click_summary_count(view, entry):
    editor = view.editor
    point = painted_character(editor, entry, -1)
    target = editor.childAt(point) or editor
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(editor.mapToGlobal(point)))


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
