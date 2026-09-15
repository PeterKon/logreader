import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from qt_helpers import wait_for_search
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.document_page import DocumentPage
from logreader.file_loader import LoadedLog
from logreader.results_model import SourceLocation
from logreader.results_view import ResultsView
from logreader.theme import THEME_COLORS


class BookmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists("C:/Windows/Fonts/consola.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    def setUp(self):
        self.view = ResultsView()
        self.view.resize(900, 550)
        for editor in (self.view.editor, self.view.source_view.editor):
            editor.setFont(QFont("Consolas", 11))
        self.view.show()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)
        self.bookmarks = self.view.bookmarks

    def render(self, lines, config=None, *, load=True):
        config = config or LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        if load:
            self.view.set_source(tuple(lines), 1000 + len(lines), snapshot_id="snapshot")
        analysis = analyze_lines(lines, config.search_patterns(),
                                 combined=config.combined_view, line_offset=1000)
        self.view.start_rendering(1, "sample.log", analysis, config)
        self.wait_render()

    def wait_render(self):
        for _ in range(2000):
            if not self.view.is_rendering:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.is_rendering)
        self.app.processEvents()

    def add(self, row=0, name="Important"):
        location = self.view.model.location(row)
        self.assertTrue(self.bookmarks.add(location, name))
        self.app.processEvents()
        return location

    def selected_row(self):
        return self.view._source_map.row(self.view.editor.textCursor().blockNumber())

    def test_dialog_cancel_default_name_and_duplicate_menu(self):
        self.render(("ERROR: needle",), LogreaderConfig(
            context=0, combined_view=False, enabled_patterns=("error_colon",),
            custom_patterns=("needle",)))
        location = self.view.model.location(0)
        with patch("logreader.bookmarks.QInputDialog.getText", return_value=("No", False)):
            self.bookmarks.prompt(location)
        self.assertFalse(self.bookmarks.items)
        self.assertTrue(self.bookmarks.strip.isHidden())
        with patch("logreader.bookmarks.QInputDialog.getText", return_value=(" ", True)):
            self.bookmarks.prompt(location)
        self.assertEqual(self.bookmarks.items[location.source].name, "Line 1,001")
        duplicate = self.view.model.location(1)
        self.assertFalse(self.bookmarks.add(duplicate, "duplicate"))
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, duplicate)
        self.assertEqual([a.text() for a in menu.actions()], ["Rename bookmark…", "Remove bookmark"])
        with patch("logreader.bookmarks.QInputDialog.getText", return_value=("A & B 😀", True)):
            menu.actions()[0].trigger()
        self.assertEqual(self.bookmarks.items[location.source].name, "A & B 😀")
        self.assertEqual(self.bookmarks.items[location.source].location, location)
        menu.actions()[1].trigger()
        self.assertFalse(self.view.editor.extraSelections())
        self.assertTrue(self.bookmarks.strip.isHidden())

    def test_original_category_restored_after_fallback_and_combined_view(self):
        lines = ("before", "ERROR: needle", "after")
        config = LogreaderConfig(context=1, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("needle",))
        self.render(lines, config)
        rows = self.view.model.rows_for_source(SourceLocation("snapshot", 1002))
        location = self.add(rows[-1])
        blocks = self.view.editor._bookmark_blocks
        self.assertEqual(list(blocks.values()), [False, True])
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), rows[-1])
        for changed in (replace(config, custom_patterns=(), custom_pattern_match_case=(),
                                custom_pattern_exclude=()), replace(config, combined_view=True)):
            self.render(lines, changed, load=False)
            self.bookmarks.activate(location.source)
            self.assertEqual(self.selected_row(), self.view.model.resolve(location))
            self.assertEqual(self.bookmarks.items[location.source].location, location)
        self.render(lines, config, load=False)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), rows[-1])

    def test_identical_custom_categories_keep_distinct_preferred_occurrence(self):
        config = LogreaderConfig(context=0, combined_view=False, enabled_patterns=(),
                                 custom_patterns=("needle", "needle"))
        self.render(("needle",), config)
        location = self.add(1)
        self.assertNotEqual(self.view.model.location(0), location)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 1)
        self.render(("needle",), replace(config, custom_patterns=("unrelated", "needle", "needle"),
                                         custom_pattern_match_case=(), custom_pattern_exclude=()), load=False)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 1)

    def test_context_line_can_disappear_and_return_as_match(self):
        lines = ("context needle", "ERROR: failure", "after")
        self.render(lines)
        location = self.add(0)
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)), load=False)
        self.assertIn(" · source", self.bookmarks.strip.tabText(0))
        self.bookmarks.activate(location.source)
        self.assertTrue(self.view.source_active)
        source = self.view.source_view
        self.assertEqual(source.editor.first_source_line + source.editor.textCursor().blockNumber(), 1001)
        self.view.set_source_active(False)
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("needle",)), load=False)
        self.assertNotIn(" · source", self.bookmarks.strip.tabText(0))
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 0)
        self.assertEqual(self.bookmarks.items[location.source].location, location)

    def test_repeated_tab_clicks_center_result_and_source_after_scrolling(self):
        self.render(tuple(f"ERROR: {i}" for i in range(300)),
                    LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        location = self.add(150)
        strip = self.bookmarks.strip
        for source_active in (False, True):
            self.view.set_source_active(source_active)
            editor = self.view.source_view.editor if source_active else self.view.editor
            for _ in range(2):
                editor.moveCursor(QTextCursor.MoveOperation.Start)
                editor.verticalScrollBar().setValue(0)
                QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.tabRect(0).center())
                self.assertEqual(editor.source_number(editor.textCursor().blockNumber()), location.source.line)
                self.assertLess(abs(editor.cursorRect().center().y() - editor.viewport().height() / 2),
                                editor.fontMetrics().height() * 2)

    def test_source_page_edge_reload_and_markers_follow_original_numbers(self):
        lines = tuple(f"ERROR: {i}" for i in range(15000))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        location = self.add(9999)
        self.view.set_source_active(True)
        source = self.view.source_view
        source.first_page()
        old_start = source.page_start
        self.assertEqual(source.page_end, 10000)
        self.bookmarks.activate(location.source)
        self.assertGreater(source.page_start, old_start)
        row = location.source.line - source.first_line - source.page_start
        self.assertEqual(source.editor._bookmark_blocks, {row: True})
        self.assertLess(abs(source.editor.cursorRect().center().y() - source.editor.viewport().height() / 2), 40)
        source.first_page()
        self.assertEqual(source.editor._bookmark_blocks, {9999: True})

    def test_search_and_copy_preserve_bookmarks_and_native_text_colors(self):
        self.render(("before", "prefix ERROR: needle 😀", "after"))
        location = self.add(1)
        self.view._search_input.setText("needle")
        self.view.search_results()
        wait_for_search(self.view)
        self.view._navigate_search(forward=True)
        self.assertEqual(len(self.view.editor.extraSelections()), 3)
        self.view._search_input.clear()
        self.assertEqual(len(self.view.editor.extraSelections()), 2)
        for text, role in (("prefix", "matched_text"), ("ERROR:", "match")):
            cursor = self.view.editor.document().find(text)
            self.assertEqual(cursor.charFormat().foreground().color().name(), THEME_COLORS[role])
        self.view.editor.selectAll()
        self.assertEqual(self.view.editor.createMimeDataFromSelection().text(),
                         "before\nprefix ERROR: needle 😀\nafter\n")
        self.view.show_source_line(location.source.line)
        self.view._search_input.setText("needle")
        self.view.search_results()
        for _ in range(1000):
            if not self.view.source_view.is_searching:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.source_view.is_searching)
        self.view.source_view.navigate(True)
        self.assertEqual(len(self.view.source_view.editor.extraSelections()), 3)
        self.view._search_input.clear()
        self.assertEqual(len(self.view.source_view.editor.extraSelections()), 2)
        self.assertEqual(self.view.source_view.editor._bookmark_blocks, {1: True})

    def test_full_width_wrapped_background_and_gutter_keep_original_width(self):
        self.render(("before", "ERROR: " + "long line " * 40, "after"))
        editor = self.view.editor
        width = editor.gutter.width()
        self.view.set_line_wrapping(True)
        self.add(1)
        self.app.processEvents()
        block = editor.document().findBlockByNumber(self.view._source_map.block(1))
        self.assertGreater(block.layout().lineCount(), 1)
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        image = editor.viewport().grab().toImage()
        gutter = editor.gutter.grab().toImage()
        for visual_line in range(block.layout().lineCount()):
            y = int(rect.top() + block.layout().lineAt(visual_line).y() + 2)
            self.assertEqual(image.pixelColor(image.width() - 10, y).name(), THEME_COLORS["bookmark"])
            self.assertEqual(gutter.pixelColor(gutter.width() - 2, y).name(), THEME_COLORS["bookmark"])
        self.assertEqual(editor.gutter.width(), width)
        self.assertFalse(editor.textCursor().hasSelection())

    def test_headers_and_space_below_document_are_not_bookmarkable(self):
        self.render(("ERROR: one",))
        editor = self.view.editor
        self.assertIsNone(self.view.result_location_at(QPoint(10, editor.viewport().height() - 5)))
        header = editor.document().firstBlock()
        rect = editor.blockBoundingGeometry(header).translated(editor.contentOffset())
        self.assertIsNone(self.view.result_location_at(QPoint(10, round(rect.center().y()))))
        block = editor.document().findBlockByNumber(self.view._source_map.block(0))
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        for x in (-editor.gutter.width() // 2, editor.viewport().width() - 10):
            self.assertEqual(self.view.result_location_at(QPoint(x, round(rect.top()) + 4)),
                             self.view.model.location(0))

    def test_timing_headers_reproject_bookmark_and_navigation(self):
        self.render(("ERROR: one",))
        location = self.add()
        before = next(iter(self.view.editor._bookmark_blocks))
        self.view.prepend_performance_timings(.1, .2)
        after = next(iter(self.view.editor._bookmark_blocks))
        self.assertGreater(after, before)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.editor.textCursor().blockNumber(), after)

    def test_smaller_analysis_range_preserves_bookmark_in_retained_source(self):
        lines = tuple(f"ERROR: {i}" for i in range(50))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        location = self.add(5)
        analysis = analyze_lines(lines[-10:], config.search_patterns(), line_offset=1040)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.wait_render()
        self.assertIn(" · source", self.bookmarks.strip.tabText(0))
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 5)
        self.assertEqual(len(self.view.source_view.lines), 50)

    def test_many_bookmarks_scroll_in_one_strip_and_support_keyboard_activation(self):
        self.render(tuple(f"ERROR: {i}" for i in range(80)))
        for row in range(30):
            self.add(row, f"Bookmark {row}: a long descriptive name")
        strip = self.bookmarks.strip
        self.assertLessEqual(strip.width(), self.view.width())
        self.assertLess(strip.height(), 40)
        self.view.editor.moveCursor(QTextCursor.MoveOperation.End)
        strip.setFocus()
        QTest.keyClick(strip, Qt.Key.Key_Return)
        self.assertEqual(self.selected_row(), 29)
        self.bookmarks.remove(self.view.model.location(10).source)
        self.assertEqual(strip.count(), 29)
        self.assertEqual(strip.tabData(strip.currentIndex()), self.view.model.location(29).source)

    def test_pending_and_cancelled_render_keep_bookmarks_source_accessible(self):
        lines = tuple(f"ERROR: {i}" for i in range(50))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        location = self.add(20)
        analysis = analyze_lines(lines, config.search_patterns(), line_offset=1000)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.assertFalse(self.bookmarks.strip.isTabEnabled(0))
        self.view.set_source_active(True)
        self.assertTrue(self.bookmarks.strip.isTabEnabled(0))
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 20)
        self.view.cancel_rendering()
        self.assertEqual(len(self.bookmarks.items), 1)
        self.assertIn(" · source", self.bookmarks.strip.tabText(0))
        self.view.set_source_active(False)
        self.bookmarks.activate(location.source)
        self.assertTrue(self.view.source_active)

    def test_source_replacement_clears_bookmarks_even_without_result_model(self):
        self.render(("ERROR: one",))
        location = self.add()
        self.view.editor.set_model(None)
        notices = []
        self.view.bookmarks_cleared.connect(lambda: notices.append(True))
        self.view.set_source(("ERROR: new",), 1001, snapshot_id="replacement")
        self.assertFalse(self.bookmarks.items)
        self.assertEqual(notices, [True])
        self.assertFalse(self.bookmarks.add(location, "stale"))
        self.assertFalse(self.view.source_view.bookmarked_lines)

    def test_source_replaced_while_naming_does_not_bookmark_wrong_document(self):
        self.render(("ERROR: old",))
        location = self.view.model.location(0)
        def changed_source(*args):
            self.view.set_source(("ERROR: new",), 1001, snapshot_id="new")
            return "stale", True
        with patch("logreader.bookmarks.QInputDialog.getText", side_effect=changed_source):
            self.bookmarks.prompt(location)
        self.assertFalse(self.bookmarks.items)

    def test_control_wheel_zoom_retains_bookmark_in_both_editors(self):
        self.render(("ERROR: one",))
        self.add()
        for active in (False, True):
            self.view.set_source_active(active)
            editor = self.view.source_view.editor if active else self.view.editor
            before = editor.font().pointSizeF()
            point = QPointF(editor.viewport().rect().center())
            wheel = QWheelEvent(point, point, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
            self.app.sendEvent(editor.viewport(), wheel)
            self.assertGreater(editor.font().pointSizeF(), before)
            self.assertEqual(len(editor._bookmark_blocks), 1)

    def test_documents_keep_separate_bookmarks_and_replacement_notice(self):
        pages = [DocumentPage(), DocumentPage()]
        for page in pages:
            self.addCleanup(page.deleteLater)
            self.addCleanup(page.dispose)
            page.stage_loaded_log(Path("sample.log"), LoadedLog(("ERROR: one",), "utf-8", 1))
            config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
            view = page.results_view
            view.start_rendering(1, "sample.log", analyze_lines(("ERROR: one",), config.search_patterns()), config)
            for _ in range(100):
                if not view.is_rendering:
                    break
                QTest.qWait(5)
            self.assertTrue(view.bookmarks.add(view.model.location(0), "Important"))
        pages[0].stage_loaded_log(Path("sample.log"), LoadedLog(("ERROR: changed",), "utf-8", 1))
        self.assertFalse(pages[0].results_view.bookmarks.items)
        self.assertIn("Bookmarks cleared", pages[0].status_message)
        self.assertEqual(len(pages[1].results_view.bookmarks.items), 1)


if __name__ == "__main__":
    unittest.main()
