import unittest
from unittest.mock import patch

from source_test_case import SourceViewCase
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor, QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from logreader.config import LogreaderConfig
from logreader.ui.results.result_coordinates import TextPoint
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.source_search import utf16_length
from logreader.ui.theme import THEME_COLORS
from qt_helpers import wait_for_search, wait_for_navigation
import test_source_view as existing_source


class SourceIntegrationTests(SourceViewCase):
    wait = existing_source.SourceViewTests.wait
    render = existing_source.SourceViewTests.render

    def open_source(self, lines, *, total=None):
        self.stage(tuple(lines), total=total)
        self.view.set_source_active(True)
        self.settle_source()
        self.wait_source_search()
        return self.source.editor

    def wait_source_search(self):
        self.wait(lambda: not self.source.is_searching and not self.source._visible_timer.isActive())

    def search(self, query):
        self.view._search_input.setText(query)
        QTest.keyClick(self.view._search_input, Qt.Key.Key_Return)
        self.wait_source_search()

    def navigate(self, forward=True):
        (self.view.find_next if forward else self.view.find_previous)()
        self.settle_source()
        self.wait_source_search()

    def current_text(self):
        return next(s.cursor.selectedText() for s in self.source.editor.extraSelections()
                    if s.format.background().color().name() == THEME_COLORS["search_current"])

    def test_search_finds_unvisited_unicode_matches_without_inserting_them(self):
        lines = [f"source row {i}" for i in range(120000)]
        target = 102500
        lines[target] = "😀\tNEEDLE needle"
        editor = self.open_source(lines, total=140000)
        editor.select(TextPoint(0, 2), TextPoint(4, 6))
        before = editor.top_point(), editor.anchor, editor.caret, editor.insertion_count
        self.page.filter_panel._limit_spin.setValue(3)
        self.assertTrue(self.view._search_input.isEnabled())
        self.search("needle")
        self.assertEqual(list(self.source.matches.lines), [target, target])
        self.assertEqual(self.source.matches.starts[0], utf16_length("😀\t"))
        self.assertEqual(list(self.source.global_scroll.match_rows), [target])
        self.assertEqual((editor.top_point(), editor.anchor, editor.caret, editor.insertion_count), before)
        self.assertFalse(editor.ranges.contains(target))
        self.assertIsNone(self.page.session.analysis)
        self.navigate()
        self.assertEqual(editor.caret, TextPoint(target, 3))
        self.assertEqual(self.current_text(), "NEEDLE")
        self.assertFalse(editor.ranges.contains(60000))
        self.assertLess(editor.ranges.loaded_count, 256)
        self.assertEqual(editor.source_number(editor._block(target).blockNumber()), 122501)
        self.navigate()
        self.assertEqual(self.current_text(), "needle")
        count = editor.insertion_count
        self.navigate()
        self.assertEqual(self.source.current_match, 0)
        self.navigate(False)
        self.assertEqual(self.source.current_match, 1)
        self.assertEqual(editor.insertion_count, count)

    def test_dense_search_and_unvisited_bookmarks_only_project_visible_rows(self):
        editor = self.open_source((f"row {i}: needle needle" for i in range(8000)), total=16000)
        before = editor.insertion_count
        self.search("needle")
        self.assertEqual(len(self.source.matches), 16000)
        self.assertEqual(list(self.source.global_scroll.match_rows), list(range(8000)))
        self.assertEqual(editor.insertion_count, before)
        bookmark = SourceLocation(self.page.session.snapshot_id, 14001)
        self.assertTrue(self.view.bookmarks.add(bookmark, "Unvisited source"))
        self.settle_source()
        self.wait_source_search()
        self.assertFalse(editor.ranges.contains(6000))
        self.assertEqual(list(self.source.global_scroll.bookmark_rows), [6000])
        self.view.bookmarks.activate(bookmark)
        self.settle_source()
        self.wait_source_search()
        self.assertEqual(editor.caret.row, 6000)
        self.assertIn(editor._block(6000).blockNumber(), editor._bookmark_blocks)
        shown = {row for row, *_ in editor.visible_ranges()}
        self.assertTrue(all(editor.location_at(s.cursor.selectionStart()).row in shown
                            for s in editor.extraSelections()))
        self.assertFalse(editor.ranges.contains(3000))
        self.source.go_to_line(8001)
        self.settle_source()
        self.wait_source_search()
        self.assertEqual(editor._bookmark_blocks, {})
        self.assertTrue(any(s.format.property(QTextFormat.Property.FullWidthSelection)
                            for s in editor._transient_selections))
        self.view._search_input.clear()
        self.wait_source_search()
        self.assertEqual(list(self.source.global_scroll.match_rows), [])
        self.assertEqual(list(self.source.global_scroll.bookmark_rows), [6000])
        self.assertTrue(self.view.bookmarks.items)
        self.view.bookmarks.remove(bookmark)
        self.wait_source_search()
        self.assertEqual(list(self.source.global_scroll.bookmark_rows), [])

    def test_long_line_search_highlights_follow_horizontal_and_wrapped_view(self):
        lines = [f"row {i}" for i in range(1000)]
        lines[600] = "😀\tERROR: " + "needle " * 10000
        editor = self.open_source(lines)
        self.search("needle")
        self.navigate()
        editor.select(TextPoint(600, 0), TextPoint(600, 30))
        selected = editor.selected_text()
        editor.horizontalScrollBar().setValue(24000)
        self.wait_source_search()
        before = editor.insertion_count
        self.assertLess(len(editor._transient_selections), 100)
        self.assertTrue(all(s.cursor.positionInBlock() > 1000 for s in editor._transient_selections))
        self.view.set_line_wrapping(True)
        editor.navigate_to(TextPoint(600, 35000))
        self.settle_source()
        self.wait_source_search()
        self.assertEqual(editor.selected_text(), selected)
        self.assertLess(sum(s.cursor.selectionEnd() - s.cursor.selectionStart()
                            for s in editor._transient_selections), 10000)
        self.assertEqual(editor.insertion_count, before)
        self.assertEqual(editor._block(600).layout().formats(), [])
        self.view._search_input.clear()
        self.wait_source_search()
        self.assertEqual(editor._transient_selections, [])
        self.assertEqual(editor.selected_text(), selected)
        self.assertEqual(editor._block(600).text(), lines[600])

    def test_query_changes_snapshot_replacement_and_hidden_search_cancel_stale_jumps(self):
        lines = tuple("NEEDLE" if i == 10000 else "plain source" for i in range(20000))
        editor = self.open_source(lines)
        self.view._search_input.setText("needle")
        self.view.search_results()
        self.source._advance_search()
        self.assertTrue(self.source.is_searching)
        self.view.find_next()
        self.view._search_input.setText("missing")
        self.assertFalse(self.source.is_searching)
        self.assertIsNone(self.source._pending_navigation)
        self.assertEqual(len(self.source.matches), 0)
        self.search("needle")
        self.source.loader.interval_ms = 1000
        self.view.find_next()
        self.assertIsNotNone(editor.navigation.pending)
        self.view._search_input.clear()
        self.assertIsNone(editor.navigation.pending)
        self.source.loader._tick()
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertFalse(editor.ranges.contains(10000))
        self.source.loader.interval_ms = 1

        self.view._search_input.setText("needle")
        self.view.find_next()
        self.view.set_source_active(False)
        self.wait_source_search()
        self.assertEqual(len(self.source.matches), 1)
        self.assertIsNone(editor.navigation.pending)
        self.view.set_source_active(True)
        self.settle_source()
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertFalse(editor.ranges.contains(10000))
        self.view._search_input.setText("plain")
        self.view.search_results()
        self.stage(("new snapshot",), total=50)
        self.settle_source()
        self.wait_source_search()
        self.assertFalse(self.source.is_searching)
        self.assertEqual(self.view._search_input.text(), "")
        self.assertEqual(len(self.source.matches), 0)
        self.assertEqual(list(self.source.global_scroll.match_rows), [])
        editor = self.source.editor
        self.assertEqual(editor._block(0).text(), "new snapshot")
        self.search("absent")
        self.assertEqual(self.source.search_status, "No matches")
        self.stage(())
        self.settle_source()
        self.search("needle")
        self.assertEqual(self.source.search_status, "No matches")
        self.view.find_next()
        self.assertIsNone(self.source.editor.navigation.pending)

    def reading_state(self, editor):
        return (editor.top_point(), editor.anchor, editor.caret, editor.selected_text(),
                editor.horizontalScrollBar().value(), editor.lineWrapMode(), editor.font().toString())

    def test_views_keep_independent_search_selection_scroll_wrap_and_zoom(self):
        self.stage(tuple(f"ERROR: result {i} needle sourceflag " + "payload " * 40 for i in range(500)))
        self.render(LogreaderConfig(context=0, combined_view=True, enabled_patterns=("error_colon",)))
        result = self.view.editor
        self.view._search_input.setText("needle")
        self.view.search_results()
        wait_for_search(self.view)
        self.view.find_next()
        wait_for_search(self.view)
        self.view.zoom(2)
        result.navigate_to(TextPoint(result.presentation.display_row(300)))
        wait_for_navigation(self.view)
        result.select(TextPoint(result.presentation.display_row(100), 2),
                      TextPoint(result.presentation.display_row(400), 20))
        result.horizontalScrollBar().setValue(80)
        wait_for_search(self.view)
        result_state = self.reading_state(result)
        result_matches = self.view._search_matches
        result_current = self.view._current_search_match

        self.view.set_source_active(True)
        self.settle_source()
        self.search("sourceflag")
        self.navigate()
        self.view.set_line_wrapping(True)
        self.view.zoom(-1)
        source = self.source.editor
        source.navigate_to(TextPoint(350))
        self.settle_source()
        source.select(TextPoint(10, 3), TextPoint(420, 25))
        self.wait_source_search()
        source_state = self.reading_state(source)
        source_matches, source_current = self.source.matches, self.source.current_match
        for _ in range(3):
            self.view.set_source_active(False)
            wait_for_navigation(self.view)
            wait_for_search(self.view)
            self.assertEqual(self.reading_state(result), result_state)
            self.assertIs(self.view._search_matches, result_matches)
            self.assertEqual(self.view._current_search_match, result_current)
            self.assertEqual(self.view._search_input.text(), "needle")
            self.assertFalse(self.view._line_wrap_check.isChecked())
            self.view.set_source_active(True)
            self.settle_source()
            self.wait_source_search()
            self.assertEqual(self.reading_state(source), source_state)
            self.assertIs(self.source.matches, source_matches)
            self.assertEqual(self.source.current_match, source_current)
            self.assertEqual(self.view._search_input.text(), "sourceflag")
            self.assertTrue(self.view._line_wrap_check.isChecked())
        self.view.set_source_active(False)
        wait_for_navigation(self.view)
        wait_for_search(self.view)

    def test_context_menus_show_original_source_and_preserve_plain_text(self):
        lines = tuple(f"{'ERROR:' if i in (50, 4500) else 'INFO'} row {i}: needle 😀" for i in range(5000))
        self.stage(lines, total=10000)
        self.render(LogreaderConfig(context=0, combined_view=True, enabled_patterns=("error_colon",)))
        self.assertTrue(self.view.bookmarks.add(self.view.model.location(0), "Result bookmark"))
        self.assertFalse(self.source.editor.ranges.contains(50))
        self.assertEqual(list(self.source.global_scroll.bookmark_rows), [50])
        location = self.view.model.location(1)
        self.view.show_result_location(location)
        wait_for_navigation(self.view)
        result = self.view.editor
        block = result.document().findBlockByNumber(self.view._source_map.block(1))
        rect = result.blockBoundingGeometry(block).translated(result.contentOffset())
        point = QPoint(20, round(rect.top() + 4))
        actions = []

        def choose(menu, _point):
            actions.extend(a.text() for a in menu.actions())
            next(a for a in menu.actions() if a.text() == "Show in source").trigger()

        class ResultMenu(QMenu):
            exec = choose

        with patch("logreader.ui.results.result_coordinates.QMenu", ResultMenu):
            self.view._results_context_menu(point)
        self.assertIn("Add bookmark", actions)
        self.assertTrue(self.view.source_active)
        self.settle_source()
        self.wait_source_search()
        editor = self.source.editor
        self.assertEqual(editor.caret.row, 4500)
        self.assertEqual(self.source.target_line, 9501)
        self.assertFalse(editor.ranges.contains(2000))
        block = editor._block(4500)
        self.assertEqual(block.text(), lines[4500])
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 5)
        self.assertEqual(cursor.charFormat().foreground().color().name(), "#ffffff")
        self.assertIsNone(block.userData())
        self.assertTrue(any(s.format.property(QTextFormat.Property.FullWidthSelection)
                            for s in editor._transient_selections))
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        point = QPoint(-editor.gutter.width() // 2, round(rect.top() + 4))
        source = SourceLocation(self.page.session.snapshot_id, 9501)
        self.assertEqual(self.view.source_location_at(point), source)
        editor.select(TextPoint(20, 0), TextPoint(4500, 10))
        selection = editor.anchor, editor.caret

        def bookmark(menu, _point):
            self.assertNotIn("Show in source", [a.text() for a in menu.actions()])
            next(a for a in menu.actions() if a.text() == "Add bookmark").trigger()

        class SourceMenu(QMenu):
            exec = bookmark

        with patch("logreader.ui.results.result_coordinates.QMenu", SourceMenu), patch(
                "logreader.ui.bookmarks.ResultsBookmarks._prompt_name", return_value=("Original line", True)):
            self.view._source_context_menu(point)
        self.assertIn(source, self.view.bookmarks.items)
        self.assertEqual((editor.anchor, editor.caret), selection)
        self.settle_source()
        self.wait_source_search()
        self.assertIn(editor._block(4500).blockNumber(), editor._bookmark_blocks)
        self.assertFalse(any(s.format.property(QTextFormat.Property.FullWidthSelection)
                             for s in editor._transient_selections))
        menu = editor.createStandardContextMenu()
        next(a for a in menu.actions() if a.text().startswith("Select All")).trigger()
        next(a for a in menu.actions() if a.text().startswith("Copy")).trigger()
        menu.deleteLater()
        self.addCleanup(self.app.clipboard().clear)
        self.assertEqual(self.app.clipboard().text(), "\n".join(lines))
        # Retain the existing replacement regression, checking source text
        # after asynchronous preparation instead of Qt's internal boundary blocks.
        self.view.set_source(("ERROR: new",), 10000001, snapshot_id="replacement")
        self.settle_source()
        self.wait_source_search()
        self.assertIsNone(self.view.model)
        self.assertEqual(self.view.editor.toPlainText(), "")
        self.assertFalse(self.view.show_result_location(location))
        self.assertIsNone(self.view._return_position)
        editor = self.source.editor
        self.assertEqual(editor._block(0).text(), "ERROR: new")
        editor.selectAll()
        self.assertEqual(editor.selected_text(), "ERROR: new")
        self.assertFalse(self.view.bookmarks.items)


if __name__ == "__main__":
    unittest.main()
