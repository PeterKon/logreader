import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QFont, QFontDatabase, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu

from qt_helpers import wait_for_search
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.results.results_view import ResultsView


class ContextTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists("C:/Windows/Fonts/consola.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    def setUp(self):
        self.view = ResultsView()
        self.view.resize(720, 500)
        for editor in (self.view.editor, self.view.source_view.editor):
            editor.setFont(QFont("Consolas", 11))
        self.view.show()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)
        lines = ("ERROR: keep selected", "ERROR: adjacent", "ERROR: " + "wrapped text " * 35,
                 "", "ERROR: last")
        self.view.set_source(lines, 1005, snapshot_id="snapshot")
        config = LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        result = analyze_lines(lines, config.search_patterns(), combined=True, line_offset=1000)
        self.view.start_rendering(1, "sample.log", result, config)
        for _ in range(1000):
            if not self.view.is_rendering:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.is_rendering)
        self.app.processEvents()

    def editor_and_block(self, source, row):
        self.view.set_source_active(source)
        editor = self.view.source_view.editor if source else self.view.editor
        number = row if source else self.view._source_map.block(row)
        return editor, editor.document().findBlockByNumber(number)

    def point_for(self, editor, block, *, last_visual_row=False):
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        return QPoint(30, round(rect.bottom() - 4 if last_visual_row else rect.top() + 4))

    def right_click(self, editor, point, inspect, *, gutter=False):
        calls = []
        failures = []
        create_menu = editor.createStandardContextMenu

        class Menu(QMenu):
            def __init__(menu):
                super().__init__()
                standard = create_menu()
                standard.setParent(menu)
                menu.addActions(standard.actions())

            def exec(menu, *args):
                calls.append(True)
                try:
                    inspect(menu)
                except BaseException as error:
                    failures.append(error)

        target = editor.gutter if gutter else editor.viewport()
        target_point = QPoint(2, point.y()) if gutter else point
        with patch.object(editor, "createStandardContextMenu", side_effect=Menu):
            QTest.mouseClick(target, Qt.MouseButton.RightButton, pos=target_point)
            if not calls:
                # QTest does not synthesize the platform context-menu event on all backends.
                event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, target_point,
                                          target.mapToGlobal(target_point))
                self.app.sendEvent(target, event)
        if failures:
            raise failures[0]
        self.assertEqual(len(calls), 1)

    @staticmethod
    def decorations(editor):
        return [(s.cursor.position(), s.cursor.anchor(), s.format.background().color().rgba())
                for s in editor.extraSelections()]

    def test_right_click_preserves_selection_copy_and_existing_highlights(self):
        for source in (False, True):
            with self.subTest(source=source):
                editor, target = self.editor_and_block(source, 1)
                self.view.bookmarks.add(SourceLocation("snapshot", 1002), "Target")
                self.view._search_input.setText("ERROR")
                self.view.search_results()
                wait_for_search(self.view)
                _, first = self.editor_and_block(source, 0)
                cursor = QTextCursor(first)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                editor.setTextCursor(cursor)
                selection = (cursor.position(), cursor.anchor())
                decorations = self.decorations(editor)

                def inspect(menu):
                    self.assertEqual(editor._context_target, target)
                    self.assertEqual((editor.textCursor().position(), editor.textCursor().anchor()), selection)
                    self.assertEqual(self.decorations(editor), decorations)
                    heading = next(a for a in menu.actions() if a.text() == "Line 1,002")
                    self.assertFalse(heading.isEnabled())
                    copy = next(a for a in menu.actions() if a.text().split("\t")[0].replace("&", "") == "Copy")
                    copy.trigger()
                    self.assertEqual(self.app.clipboard().text(), "ERROR: keep selected")

                self.right_click(editor, self.point_for(editor, target), inspect)
                self.assertIsNone(editor._context_target)
                self.assertEqual((editor.textCursor().position(), editor.textCursor().anchor()), selection)
                self.assertEqual(self.decorations(editor), decorations)

    def test_wrapped_lines_and_blank_lines_work_from_text_and_gutter(self):
        for source in (False, True):
            editor, _ = self.editor_and_block(source, 0)
            self.view.set_line_wrapping(True)
            self.app.processEvents()
            for row, gutter in ((2, False), (3, True)):
                with self.subTest(source=source, row=row):
                    _, block = self.editor_and_block(source, row)
                    cursor = QTextCursor(block)
                    editor.setTextCursor(cursor)
                    editor.centerCursor()
                    self.app.processEvents()
                    point = self.point_for(editor, block, last_visual_row=True)

                    def inspect(menu):
                        self.assertEqual(editor._context_target, block)
                        self.assertIn(f"Line {1001 + row:,}", [a.text() for a in menu.actions()])

                    self.right_click(editor, point, inspect, gutter=gutter)
                    self.assertIsNone(editor._context_target)

    def test_non_source_areas_do_not_acquire_a_target(self):
        for source in (False, True):
            editor, _ = self.editor_and_block(source, 0)
            points = [QPoint(20, editor.viewport().height() - 3)]
            if not source:
                points.append(self.point_for(editor, editor.document().firstBlock()))
            for point in points:
                def inspect(menu):
                    self.assertIsNone(editor._context_target)
                    self.assertFalse(any(a.text().startswith("Line ") for a in menu.actions()))
                    self.assertFalse(any(a.text() == "Add bookmark" for a in menu.actions()))
                self.right_click(editor, point, inspect)

    def test_target_survives_bookmark_dialog_and_clears_after_cancel(self):
        editor, target = self.editor_and_block(False, 1)
        observed = []

        def close_dialog():
            dialog = self.app.activeModalWidget()
            if not isinstance(dialog, QInputDialog):
                QTimer.singleShot(5, close_dialog)
                return
            observed.append(editor._context_target == target)
            dialog.reject()

        def inspect(menu):
            QTimer.singleShot(0, close_dialog)
            next(a for a in menu.actions() if a.text() == "Add bookmark").trigger()
            self.assertEqual(editor._context_target, target)

        self.right_click(editor, self.point_for(editor, target), inspect)
        self.assertEqual(observed, [True])
        self.assertIsNone(editor._context_target)
        self.assertFalse(self.view.bookmarks.items)

    def test_bookmark_uses_clicked_line_while_preserving_another_selection(self):
        for source in (False, True):
            with self.subTest(source=source):
                self.view.bookmarks.clear()
                editor, first = self.editor_and_block(source, 0)
                cursor = QTextCursor(first)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                editor.setTextCursor(cursor)
                _, target = self.editor_and_block(source, 1)

                def inspect(menu):
                    next(a for a in menu.actions() if a.text() == "Add bookmark").trigger()

                with patch.object(self.view.bookmarks, "_prompt_name", return_value=("Clicked", True)):
                    self.right_click(editor, self.point_for(editor, target), inspect)
                self.assertEqual(list(self.view.bookmarks.items), [SourceLocation("snapshot", 1002)])
                self.assertEqual(editor.textCursor().selectedText(), cursor.selectedText())
                self.assertIsNone(editor._context_target)

    def test_repeated_source_line_outlines_only_the_clicked_result_occurrence(self):
        lines = ("ERROR: first", "error second")
        # Context puts the same source line in both result categories.
        config = LogreaderConfig(context=1, combined_view=False, enabled_patterns=("error_colon", "error"))
        self.view.set_source(lines, 1002, snapshot_id="duplicates")
        result = analyze_lines(lines, config.search_patterns(), line_offset=1000)
        self.view.start_rendering(2, "sample.log", result, config)
        for _ in range(1000):
            if not self.view.is_rendering:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.is_rendering)
        rows = self.view.model.rows_for_source(SourceLocation("duplicates", 1001))
        self.assertEqual(len(rows), 2)
        editor, target = self.editor_and_block(False, rows[1])

        def inspect(menu):
            self.assertEqual(editor._context_target, target)
            self.assertNotEqual(editor._context_target.blockNumber(), self.view._source_map.block(rows[0]))

        self.right_click(editor, self.point_for(editor, target), inspect)

    def test_replacement_invalidates_target_and_old_navigation_action(self):
        editor, target = self.editor_and_block(False, 1)

        def inspect(menu):
            action = next(a for a in menu.actions() if a.text() == "Show in source")
            self.view.set_source(("replacement",), 1, snapshot_id="replacement")
            self.assertIsNone(editor._context_target)
            action.trigger()
            self.assertFalse(self.view.source_active)

        self.right_click(editor, self.point_for(editor, target), inspect)

    def test_source_page_replacement_and_view_switch_clear_target(self):
        editor, target = self.editor_and_block(True, 1)

        def inspect(menu):
            self.view.source_view._load_page(0)
            self.assertIsNone(editor._context_target)

        self.right_click(editor, self.point_for(editor, target), inspect)
        editor.set_context_target(editor.document().firstBlock())
        self.view.set_source_active(False)
        self.assertIsNone(editor._context_target)


if __name__ == "__main__":
    unittest.main()
