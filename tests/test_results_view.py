import os
import unittest
import weakref
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qt_helpers import painted_character, qt_application, retire_window, wait_source
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QFont, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

from qt_helpers import wait_for_search, wait_for_navigation, retire_results
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.regex_presets import REGEX_PRESETS
from logreader.ui.results.results_editor import StructuralBlock
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.results.results_view import ResultsView
from logreader.ui.results.result_coordinates import TextPoint
from logreader.ui.source_search import utf16_length
from logreader.ui.theme import THEME_COLORS


class ResultsViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        self.addCleanup(self.app.clipboard().clear)
        self.view = ResultsView()
        self.view.editor.setFont(QFont("Consolas", 11))
        self.view.resize(900, 550)
        self.view.show()
        self.addCleanup(retire_window, self.view)

    def render(self, lines, config=None, *, new_snapshot=True):
        config = config or LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        if new_snapshot:
            self.view.set_source(tuple(lines), 10000000 + len(lines), snapshot_id="snapshot")
        analysis = analyze_lines(lines, config.search_patterns(),
                                 combined=config.combined_view, line_offset=10000000)
        self.view.start_rendering(1, "test.log", analysis, config)
        for _ in range(2000):
            if not self.view.is_rendering:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.is_rendering)
        self.app.processEvents()
        return self.view.editor

    def cursor(self, row, column=0):
        block = self.view.editor.document().findBlockByNumber(self.view._source_map.block(row))
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + column)
        return cursor

    def painted_character(self, text, character=0, occurrence=0):
        return painted_character(self.view.editor, text, character, occurrence)

    def click_painted_point(self, point, *, active=True):
        editor = self.view.editor
        target = editor.childAt(point) or editor
        global_point = editor.mapToGlobal(point)
        local = target.mapFromGlobal(global_point)
        # The QWidget overload moves the desktop cursor, which may hit an unrelated window.
        QTest.mouseMove(self.view.windowHandle(), self.view.mapFromGlobal(global_point))
        self.assertEqual(target.cursor().shape() == Qt.CursorShape.PointingHandCursor, active, point)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=local)
        wait_for_search(self.view)

    def test_total_in_both_views_and_combined_results_follow_summary(self):
        for combined in (False, True):
            with self.subTest(combined=combined):
                config = LogreaderConfig(context=0, combined_view=combined,
                                         enabled_patterns=("error_colon",), custom_patterns=("needle",))
                editor = self.render(("ERROR: needle", "ERROR: second"), config)
                output = editor.toPlainText()
                self.assertTrue(output.startswith("Matches (3 total):\n"))
                self.assertNotIn("Total matches -", output)
                if combined:
                    self.assertIn("needle 1\n\nERROR: needle", output)
                else:
                    self.assertIn("ERROR: - 2 matches\n\nERROR: needle", output)
                    self.assertIn("needle - 1 matches\n\nERROR: needle", output)
                for row, line in enumerate(self.view.model.iter_lines()):
                    self.assertEqual(self.cursor(row).block().text(), line.text)

    def test_inline_summary_keeps_multiword_labels_with_counts_when_wrapping(self):
        labels = ("ERROR:", "FATAL", "Exception", "Timeout", "HTTP 5xx", "HTTP 4xx",
                  "Connection refused", "Retry exhausted")
        editor = self.render(labels, LogreaderConfig(context=0, enabled_patterns=(),
                                                    custom_patterns=labels))
        self.view.resize(690, 550)
        self.view.set_line_wrapping(True)
        self.app.processEvents()
        for label in labels:
            cursor = editor.document().find(label + " 1")
            self.assertFalse(cursor.isNull(), label)
            block = cursor.block()
            layout = block.layout()
            start = cursor.selectionStart() - block.position()
            end = cursor.selectionEnd() - block.position() - 1
            self.assertEqual(layout.lineForTextPosition(start).lineNumber(),
                             layout.lineForTextPosition(end).lineNumber(), label)

    def test_total_uses_thousands_separator_in_both_views(self):
        from logreader.ui.results.result_formatting import _iter_analysis_render_operations

        for combined in (False, True):
            with self.subTest(combined=combined):
                config = LogreaderConfig(context=0, combined_view=combined,
                                         enabled_patterns=("error_colon",), custom_patterns=("needle",))
                analysis = analyze_lines(("ERROR: needle",) * 6250, config.search_patterns(),
                                         combined=combined)
                operations = _iter_analysis_render_operations("test.log", analysis, config)
                self.assertEqual(next(operations)[0], "Matches (12,500 total):\n")

    def test_regex_presets_use_names_in_summaries_and_headings(self):
        for combined in (False, True):
            with self.subTest(combined=combined):
                config = LogreaderConfig(
                    context=0, combined_view=combined, enabled_patterns=(),
                    regex_patterns=tuple(expression for _, expression in REGEX_PRESETS) + (r"code=\d+",),
                )
                output = self.render(("alex@example.org code=42",), config).toPlainText()
                for name, expression in REGEX_PRESETS:
                    self.assertIn(f"{name} (regex)", output)
                    self.assertNotIn(expression, output)
                self.assertIn(r"code=\d+", output)
                if not combined:
                    self.assertIn("Email addresses (regex) - 1 matches", output)

    def test_click_summary_names_and_counts_by_key_across_the_gutter(self):
        email = dict(REGEX_PRESETS)["Email addresses"]
        config = LogreaderConfig(context=0, combined_view=False, enabled_patterns=("error_colon", "fatal"),
                                 custom_patterns=("needle",), custom_pattern_names=("Needle",),
                                 regex_patterns=(email, r"id=\d+", r"code=\d+"),
                                 regex_pattern_names=("", "Twin", "Twin"))
        view = self.view
        editor = self.render(("ERROR: needle alex@example.org id=17 code=503",) * 12, config)
        self.assertIs(editor.childAt(self.painted_character("ERROR: 12")), editor.gutter)
        for key, label, occurrence in (
            ("error_colon", "ERROR:", 0), ("custom_1", "Needle (text match)", 0),
            ("regex_1", "Email addresses (regex)", 0),
            ("regex_2", "Twin (regex)", 0), ("regex_3", "Twin (regex)", 1),
        ):
            entry = label + " 12"
            for character in (0, len(label), len(entry) - 2, len(entry) - 1):
                with self.subTest(key=key, character=character):
                    before = editor.top_point(), editor.anchor, editor.caret
                    self.click_painted_point(self.painted_character(entry, character, occurrence))
                    self.assertEqual((editor.top_point(), editor.anchor, editor.caret), before)
                    self.assertEqual(view._results_query.key, key)
                    self.assertTrue(view._search_input.hasFocus())
                    self.assertEqual(view._search_input.selectedText(), label)
                    self.assertTrue(view._pattern_indicator.isVisible())

        view._search_input.clear()
        for text in ("Matches (", "   ", "No matches:", "FATAL", "ERROR: - 12 matches"):
            with self.subTest(inactive=text):
                self.click_painted_point(self.painted_character(text), active=False)
                self.assertEqual(view._search_input.text(), "")
                self.assertFalse(view._pattern_indicator.isVisible())
        last_digit = self.painted_character("Twin (regex) 12", -1, 1)
        self.click_painted_point(last_digit + QPoint(18, 0), active=False)

    def test_wrapped_and_zoomed_click_targets_follow_live_rename(self):
        view = self.view
        config = LogreaderConfig(context=0, enabled_patterns=(), regex_patterns=("a+", "b+"),
                                 regex_pattern_names=("Twin", "Twin"))
        editor = self.render(("aa bbb", "a bb"), config)
        view.resize(640, 480)
        view.set_line_wrapping(True)
        self.app.processEvents()
        entry = "Twin (regex) 2"
        old_neighbor = self.painted_character(entry, 0, 1)
        self.click_painted_point(self.painted_character(entry))
        view.find_next()
        wait_for_search(view)
        hits, current = view._search_matches, view._current_search_match
        name = "😀 " + "Long match name " * 6 + "(regex)"
        view.rename_category("regex_1", name)
        self.app.processEvents()
        self.assertIs(view._search_matches, hits)
        self.assertEqual(view._current_search_match, current)
        self.assertEqual(view._search_input.text(), name)
        self.click_painted_point(old_neighbor)
        self.assertEqual(view._results_query.key, "regex_1")
        for zoom in (0, 2):
            with self.subTest(zoom=zoom):
                if zoom:
                    view.zoom(zoom)
                self.app.processEvents()
                first = self.painted_character(name + " 2")
                count = self.painted_character(name + " 2", len(name) + 1)
                self.assertGreater(count.y(), first.y())
                self.click_painted_point(count)
                self.assertIs(view._search_matches, hits)
                self.assertEqual(view._current_search_match, current)
        self.click_painted_point(self.painted_character(entry, len(entry) - 1))
        self.assertEqual(view._results_query.key, "regex_2")
        QTest.keyClicks(view._search_input, "literal")
        self.assertEqual(view._search_input.text(), "literal")
        self.assertFalse(view._pattern_indicator.isVisible())
        self.assertEqual(view._search_input.textMargins().left(), 0)

        view.set_line_wrapping(False)
        self.app.processEvents()
        point = self.painted_character(name + " 2", len(name) // 2)
        editor.horizontalScrollBar().setValue(point.x() - editor.gutter.geometry().center().x())
        self.app.processEvents()
        point = self.painted_character(name + " 2", len(name) // 2)
        self.assertIs(editor.childAt(point), editor.gutter)
        before = editor.horizontalScrollBar().value()
        self.assertGreater(before, 0)
        self.click_painted_point(point)
        self.assertEqual(view._results_query.key, "regex_1")
        self.assertEqual(editor.horizontalScrollBar().value(), before)

    def test_dragging_or_right_clicking_a_summary_entry_uses_the_editor(self):
        view = self.view
        config = LogreaderConfig(context=1, enabled_patterns=("error_colon",),
                                 custom_patterns=("needle",), custom_pattern_names=("Needle",))
        editor = self.render(("ERROR: needle first", "needle second", "last"), config)
        viewport = editor.viewport()
        point = self.painted_character("Needle (text match) 2", 5)
        self.assertIs(editor.childAt(point), viewport)
        start = viewport.mapFromGlobal(editor.mapToGlobal(point))
        end = editor.cursorRect(self.cursor(2, 3)).center()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertIn("needle second", editor.selected_text())
        self.assertFalse(view._pattern_indicator.isVisible())

        selected = editor.selected_text()
        with patch.object(view, "_exec_line_context_menu") as menu:
            QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=start)
            if not menu.called:  # Offscreen Qt can leave context-menu dispatch to the platform.
                event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, start, viewport.mapToGlobal(start))
                self.app.sendEvent(viewport, event)
            menu.assert_called_once_with(editor, start, None, show_source=True)
        self.assertEqual(editor.selected_text(), selected)
        self.assertEqual(view._search_input.text(), "")

    def test_performance_status_keeps_text_mapping_and_selection_unchanged(self):
        editor = self.render(("ERROR: needle", "ERROR: second"))
        editor.selectAll()
        before = editor.document(), editor.anchor, editor.caret, editor.selected_text()
        self.view.prepend_performance_timings(.0012, .0034)
        self.assertIn("Analysis: 0.001 s | Rendering: 0.003 s", self.view.loading_status)
        self.assertEqual((editor.document(), editor.anchor, editor.caret, editor.selected_text()), before)


    def test_copy_all_excludes_structure_and_preserves_duplicate_rows_and_empty_source_lines(self):
        lines = ("before", "ERROR: needle", "", "omitted", "ERROR: needle -------->", "after")
        for combined in (False, True):
            for separate in (False, True):
                with self.subTest(combined=combined, separate=separate):
                    config = LogreaderConfig(context=1, combined_view=combined,
                                             separate_entries=separate,
                                             enabled_patterns=("error_colon",), custom_patterns=("needle",))
                    editor = self.render(lines, config)
                    self.view.prepend_performance_timings(.1, .2)
                    editor.selectAll()
                    mime = editor.createMimeDataFromSelection()
                    expected = "".join(line.text + "\n" for line in self.view.model.iter_lines())
                    self.assertEqual(mime.text(), expected)
                    self.assertFalse(mime.hasHtml())
                    self.assertIn("needle\n\n", mime.text())
                    self.assertIn("-------->", mime.text())  # Actual source text survives.
                    # Partial copy through the final structural row keeps raw
                    # interior lines, duplicates, blanks and the trailing newline.
                    start = self.cursor(0, 1).position()
                    stop = editor.document().characterCount() - 1
                    for anchor, caret in ((start, stop), (stop, start)):
                        cursor = QTextCursor(editor.document())
                        cursor.setPosition(anchor)
                        cursor.setPosition(caret, QTextCursor.MoveMode.KeepAnchor)
                        editor.setTextCursor(cursor)
                        self.assertEqual(editor.createMimeDataFromSelection().text(), expected[1:])
                    cursor = editor.document().find("Performance results")
                    editor.setTextCursor(cursor)
                    self.assertEqual(editor.createMimeDataFromSelection().text(), "")

    def test_partial_unicode_copy_and_cross_excerpt_selection_preserve_exact_raw_text(self):
        lines = ("\t😀ERROR: keep\u00a0spaces\tend", "skip", "ERROR: last 😀 tail")
        editor = self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        start = self.cursor(0, utf16_length("\t😀ERROR: ")).position()
        stop = self.cursor(1, utf16_length("ERROR: last 😀")).position()
        cursor = QTextCursor(editor.document())
        cursor.setPosition(stop)
        cursor.setPosition(start, QTextCursor.MoveMode.KeepAnchor)  # Reverse drag.
        editor.setTextCursor(cursor)
        self.assertEqual(editor.createMimeDataFromSelection().text(), "keep\u00a0spaces\tend\nERROR: last 😀")
        cursor = self.cursor(0, utf16_length("\t"))
        cursor.setPosition(cursor.position() + utf16_length("😀"), QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        self.assertEqual(editor.createMimeDataFromSelection().text(), "😀")

    def test_search_ignores_numbers_headings_and_timings_and_includes_duplicate_log_text(self):
        config = LogreaderConfig(context=0, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("needle",))
        self.render(("😀 ERROR: needle NEEDLE",), config)
        self.view.prepend_performance_timings(.1, .2)
        for query, expected in (("matches", 0), ("10000001", 0), ("Analysis:", 0),
                                ("needle", 4), ("😀", 2), ("ERROR:", 2)):
            with self.subTest(query=query):
                self.view._search_input.setText(query)
                self.view.search_results()
                wait_for_search(self.view)
                self.assertEqual(len(self.view._search_matches), expected)
                for row, start, end in self.view._search_matches:
                    block = self.cursor(row).block()
                    self.assertIsNotNone(self.view._source_map.row(block.blockNumber()))
                    self.assertLessEqual(end, block.length() - 1)

    def test_fixed_muted_gutter_and_green_red_text_survive_wrapping_search_and_scrolling(self):
        lines = ("before", "prefix ERROR: " + "body " * 100, "after")
        editor = self.render(lines)
        self.assertEqual(editor.source_number(self.view._source_map.block(0)), 10000001)
        self.assertEqual(editor.source_number(self.view._source_map.block(1)), 10000002)
        self.assertIsNone(editor.source_number(0))  # Summary has no number.
        self.assertEqual(editor.gutter.geometry().right() + 1, editor.viewport().geometry().left())
        width = editor.gutter.width()
        before = editor.gutter.grab().toImage()
        editor.horizontalScrollBar().setValue(200)
        self.app.processEvents()
        self.assertEqual(editor.gutter.grab().toImage(), before)
        self.view._search_input.setText("body")
        self.view.search_results()
        wait_for_search(self.view)
        self.view._search_input.clear()
        wait_for_search(self.view)
        for text, role in (("before", "body"), ("prefix", "matched_text"),
                           ("ERROR:", "match"), ("body ", "matched_text")):
            cursor = self.cursor(0 if text == "before" else 1)
            cursor = editor.document().find(text, cursor)
            self.assertEqual(cursor.charFormat().foreground().color().name(), THEME_COLORS[role])
        self.view.set_line_wrapping(True)
        self.app.processEvents()
        self.assertEqual(editor.gutter.width(), width)
        row = self.view._source_map.block(1)
        self.assertGreater(editor.document().findBlockByNumber(row).layout().lineCount(), 1)
        self.assertEqual(editor.source_number(row), 10000002)

    def test_excerpt_gap_is_blank_across_gutter_and_text(self):
        editor = self.render(("ERROR: first", "omit", "ERROR: last"),
                             LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        projection = self.view._source_map
        block = editor.document().findBlockByNumber(projection.block(0) + 1)
        self.assertEqual(block.text(), "")
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        y = round(rect.top() + editor.fontMetrics().height() / 2)
        image = editor.grab().toImage()
        y += editor.viewport().geometry().top()
        for x in range(editor.gutter.geometry().left(), editor.viewport().geometry().right()):
            self.assertEqual(image.pixelColor(x, y).name(), THEME_COLORS["background"])

    def test_excerpt_gap_is_four_pixels_shorter_without_shrinking_blank_source_lines(self):
        lines = ("ERROR: first", "", "omitted", "omitted", "before", "ERROR: last")
        config = LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        editor = self.render(lines, config)
        blank_source = self.cursor(1).block()
        gap = blank_source.next()
        self.assertEqual(blank_source.text(), "")
        self.assertEqual(gap.text(), "")
        self.assertIsNone(blank_source.userData())
        for zoom in (0, 1, -1):
            editor.zoomIn(zoom)
            self.app.processEvents()
            self.assertEqual(editor.blockBoundingRect(blank_source).height() -
                             editor.blockBoundingRect(gap).height(), 4)
        self.render(lines, replace(config, separate_entries=False))
        self.assertEqual(self.cursor(2).block().blockNumber(),
                         self.cursor(1).block().blockNumber() + 1)

    def test_summary_and_headings_paint_above_gutter_after_timing_insertion(self):
        editor = self.render(("Matches:", "ERROR: sample", "after"),
                             LogreaderConfig(context=1, combined_view=False,
                                             enabled_patterns=("error_colon",)))
        self.view.prepend_performance_timings(.1, .2)
        self.view.set_line_wrapping(True)
        self.app.processEvents()
        for row in range(self.view.model.row_count):
            self.assertIsNone(self.cursor(row).block().userData())
        for heading in ("Matches (1 total):", "ERROR:"):
            cursor = editor.document().find(heading)
            block = cursor.block()
            self.assertIsInstance(block.userData(), StructuralBlock)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()
            self.app.processEvents()
            rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
            top = round(rect.top()) + editor.viewport().geometry().top()
            image = editor.grab().toImage()
            colors = {
                image.pixelColor(x, y).name()
                for x in range(editor.gutter.geometry().left(), editor.viewport().geometry().left())
                for y in range(top, top + editor.fontMetrics().height())
            }
            self.assertGreater(len(colors), 1, heading)

    def test_source_and_results_share_tight_number_and_text_spacing(self):
        results = self.render(("ERROR: sample",))
        self.view.show_source_line(10000001)
        wait_source(self.view)
        self.app.processEvents()
        source = self.view.source_view.editor
        for editor in (results, source):
            with self.subTest(editor=type(editor).__name__):
                self.assertEqual(editor.gutter.geometry().left(), 4)
                self.assertEqual(editor.gutter.width(),
                                 editor.fontMetrics().horizontalAdvance("10000001") + 9)
                self.assertEqual(editor.document().documentMargin(), 4)

    def test_navigation_resolves_reanalysis_and_overrides_saved_return_position(self):
        lines = tuple("ERROR: needle " + str(i) for i in range(80))
        config = LogreaderConfig(context=0, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("needle",))
        editor = self.render(lines, config)
        target = self.view.model.location(120)  # Source line 41 in the second category.
        self.view.show_source_line(10000002)
        wait_source(self.view)
        self.assertIsNotNone(self.view._return_position)
        self.assertTrue(self.view.show_result_location(target))
        wait_for_navigation(self.view)
        editor = self.view.editor
        self.assertFalse(self.view.source_active)
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 120)
        self.assertIsNone(self.view._return_position)
        self.view.prepend_performance_timings(.1, .2)
        self.view.set_line_wrapping(True)
        self.assertTrue(self.view.show_result_location(target))
        wait_for_navigation(self.view)
        editor = self.view.editor
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 120)
        self.render(lines, replace(config, combined_view=True), new_snapshot=False)
        self.assertTrue(self.view.show_result_location(target))
        wait_for_navigation(self.view)
        editor = self.view.editor
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 40)
        before = editor.textCursor().position()
        self.assertFalse(self.view.show_result_location(SourceLocation("different", 10000041)))
        self.assertFalse(self.view.show_result_location(SourceLocation("snapshot", 1)))
        self.assertEqual(editor.textCursor().position(), before)

    def test_search_controls_center_matches_in_both_viewers_and_result_modes(self):
        prefix = "ERROR: 😀 " + "wrapped words " * 40
        lines = tuple((prefix + "needle tail" if i in (120, 220) else
                       f"{'ERROR:' if i % 2 == 0 else 'INFO'} row {i}") for i in range(400))
        for combined in (False, True):
            self.view.set_source_active(False)
            self.render(lines, LogreaderConfig(context=0, combined_view=combined,
                                              separate_entries=True, enabled_patterns=("error_colon",)))
            for source_active in (False, True):
                self.view.set_source_active(source_active)
                wait_source(self.view)
                editor = self.view.source_view.editor if source_active else self.view.editor
                for wrapped in (False, True):
                    with self.subTest(combined=combined, source=source_active, wrapped=wrapped):
                        self.view.set_line_wrapping(wrapped)
                        editor.navigate_to(TextPoint(0))
                        wait_for_navigation(self.view)
                        wait_source(self.view)
                        self.view._search_input.clear()
                        self.view._search_input.setText("needle")
                        self.view._search_input.returnPressed.emit()
                        wait_for_search(self.view)
                        wait_source(self.view)
                        self.assertEqual(editor.top_point(), TextPoint(0))
                        for action, row in (
                            (self.view._search_input.returnPressed.emit, 120),
                            (self.view._search_navigation.stepDown, 220),
                            (self.view._search_navigation.stepUp, 120),
                            (self.view._search_input.returnPressed.emit, 220),
                        ):
                            action()
                            wait_for_navigation(self.view)
                            wait_for_search(self.view)
                            wait_source(self.view)
                            self.assertEqual(editor.source_number(editor.textCursor().blockNumber()),
                                             10000001 + row)
                            self.assertEqual(editor.caret.column, utf16_length(prefix))
                            self.assertLess(abs(editor.cursorRect().center().y() - editor.viewport().height() / 2),
                                            editor.fontMetrics().height())
                            self.assertTrue(editor.viewport_evidence()["useful"])

    def test_reset_releases_completed_model_and_clears_gutter_projection_and_navigation(self):
        self.render(("ERROR: sample",))
        location = self.view.model.location(0)
        reference = weakref.ref(self.view.model)
        self.view.reset_for_loaded_file("new.log")
        retire_results()
        self.assertIsNone(reference())
        self.assertIsNone(self.view.model)
        self.assertEqual(self.view.editor.gutter.width(), 0)
        self.assertEqual(self.view.editor.ranges.total, 0)
        self.assertFalse(self.view.show_result_location(location))

    def test_pattern_search_shares_highlights_markers_and_viewport_navigation(self):
        view = self.view
        lines = tuple("row 😀 12! 34!" if i in (30, 150) else "row" for i in range(210))
        for combined in (True, False):
            with self.subTest(combined=combined):
                config = LogreaderConfig(context=0, combined_view=combined, enabled_patterns=(),
                                         custom_patterns=("row",), regex_patterns=(r"\d+(?=!)",),
                                         regex_pattern_names=("IDs",))
                editor = self.render(lines, config)
                identity = editor.result_set_id
                view.global_scroll.setValue(editor.presentation.display_row(143))
                wait_for_navigation(view)
                top = editor.top_point()
                self.assertTrue(view.activate_pattern_search("regex_1", result_set_id=identity))
                wait_for_search(view)
                rows = [30, 150] if combined else [30, 150, 210, 211]
                self.assertEqual(view._search_input.text(), "IDs (regex)")
                self.assertEqual(view._search_count_label.text(), f"0 / {len(rows) * 2}")
                self.assertEqual(editor.top_point(), top)
                self.assertEqual(list(view.global_scroll.match_rows),
                                 [editor.presentation.display_row(row) for row in rows])
                formats = self.cursor(150).block().layout().formats()
                self.assertEqual([(f.start, f.length) for f in formats], [(7, 2), (11, 2)])

                view._search_input.returnPressed.emit()
                wait_for_search(view)
                self.assertEqual(editor.caret, TextPoint(editor.presentation.display_row(150), 7))
                self.assertLess(abs(editor.cursorRect().center().y() - editor.viewport().height() / 2),
                                editor.fontMetrics().height())
                hits = view._search_matches
                current = view._current_search_match
                self.assertTrue(view.activate_pattern_search("regex_1", result_set_id=identity))
                self.assertIs(view._search_matches, hits)
                self.assertEqual(view._current_search_match, current)
                view._search_navigation.stepDown()
                wait_for_navigation(view)
                self.assertEqual(editor.caret.column, 11)
                view.global_scroll.triggerAction(view.global_scroll.SliderAction.SliderToMinimum)
                wait_for_navigation(view)
                view._search_navigation.stepUp()
                wait_for_navigation(view)
                self.assertEqual(view._current_search_match, len(hits) - 1)
                view._search_input.returnPressed.emit()
                wait_for_navigation(view)
                self.assertEqual(view._current_search_match, 0)

    def test_switching_pending_patterns_with_identical_names_and_editing_the_label(self):
        view = self.view
        config = LogreaderConfig(context=0, enabled_patterns=(), regex_patterns=("x+", "y+", "z+"),
                                 regex_pattern_names=("Same", "Same", "Missing"))
        identity = self.render(("x xx yyy Same (regex)",), config).result_set_id
        self.assertTrue(view.activate_pattern_search("regex_1", result_set_id=identity))
        old_work, generation = view._search_work, view._search_generation
        with patch("logreader.ui.results.results_view.perf_counter",
                   side_effect=lambda: float(bool(view._pending_matches))):
            view._search_next_batch()
        self.assertEqual(list(view._pending_matches), [(0, 0, 1)])
        view.find_next()  # A queued jump for the first regex must not affect the second.
        self.assertTrue(view.activate_pattern_search("regex_1", result_set_id=identity))
        self.assertIs(view._search_work, old_work)
        self.assertTrue(view.activate_pattern_search("regex_2", result_set_id=identity))
        view._advance_search(generation)
        wait_for_search(view)
        self.assertEqual(view._search_input.text(), "Same (regex)")
        clear = view._search_input.findChild(QToolButton, "resultsSearchClearButton")
        self.assertTrue(clear.isVisible())
        self.assertEqual(list(view._search_matches), [(0, 5, 8)])
        self.assertEqual(view._search_count_label.text(), "0 / 1")
        self.assertFalse(view.activate_pattern_search("regex_3", result_set_id=identity))
        self.assertFalse(view.activate_pattern_search("unknown", result_set_id=identity))
        view._search_input.selectAll()
        view._search_input.insert("Same (regex)")
        self.assertFalse(view.global_scroll.match_rows)
        view._search_input.returnPressed.emit()
        wait_for_search(view)
        self.assertEqual(list(view._search_matches), [(0, 9, 21)])
        view.activate_pattern_search("regex_1", result_set_id=identity)
        view._paint_decorations()
        self.assertFalse(self.cursor(0).block().layout().formats())
        QTest.mouseClick(clear, Qt.MouseButton.LeftButton)
        wait_for_search(view)
        self.assertFalse(view._search_matches)
        self.assertTrue(view._search_count_label.isHidden())

    def test_pattern_search_survives_source_view_and_expires_with_its_results(self):
        view = self.view
        lines = ("one two sourceflag", "one sourceflag")
        config = LogreaderConfig(context=0, enabled_patterns=(), regex_patterns=("one",),
                                 regex_pattern_names=("Selected",))
        identity = self.render(lines, config).result_set_id
        view.activate_pattern_search("regex_1", result_set_id=identity)
        wait_for_search(view)
        view.find_next()
        wait_for_navigation(view)
        hits = view._search_matches
        view.set_source_active(True)
        wait_source(view)
        self.assertFalse(view._pattern_indicator.isVisible())
        view._search_input.setText("sourceflag")
        view.search_results()
        wait_source(view)
        view.set_source_active(False)
        wait_for_navigation(view)
        self.assertEqual(view._search_input.text(), "Selected (regex)")
        self.assertTrue(view._pattern_indicator.isVisible())
        self.assertIs(view._search_matches, hits)
        self.assertEqual(view._search_count_label.text(), "1 / 2")

        view.set_source_active(True)
        view.begin_analysis()
        replacement = self.render(lines, replace(config, regex_patterns=("two",)), new_snapshot=False)
        self.assertEqual(view._search_input.text(), "sourceflag")
        self.assertEqual(len(view.source_view.matches), 2)
        view.set_source_active(False)
        self.assertEqual(view._search_input.text(), "")
        self.assertFalse(view._pattern_indicator.isVisible())
        self.assertFalse(view.global_scroll.match_rows)
        self.assertFalse(view.activate_pattern_search("regex_1", result_set_id=identity))
        replacement_id = replacement.result_set_id
        self.assertTrue(view.activate_pattern_search("regex_1", result_set_id=replacement_id))
        wait_for_search(view)
        self.assertEqual(list(view._search_matches), [(0, 4, 7)])
        view.set_source(("another file",), 1, snapshot_id="replacement")
        self.assertFalse(view.activate_pattern_search("regex_1", result_set_id=replacement_id))
        self.assertEqual(view._search_input.text(), "")

    def test_cancelling_preparation_drops_stale_completion(self):
        from PySide6.QtCore import QThreadPool
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        analysis = analyze_lines(("ERROR: sample", "skip") * 100, config.search_patterns(), combined=True)
        workers = []
        with patch.object(QThreadPool, "start", side_effect=workers.append):
            self.view.start_rendering(1, "sample", analysis, config)
        worker = workers[0]
        self.view.cancel_rendering()
        worker.run()
        self.assertTrue(worker.cancellation.is_cancelled)
        self.assertIsNone(worker.analysis)
        self.assertIsNone(self.view.model)
        self.assertFalse(self.view.is_rendering)


    def test_timing_helper_keeps_raw_copy_search_and_source_mapping_aligned(self):
        editor = self.render(("before", "ERROR: needle", "after"))
        location = self.view.model.location(1)
        for _ in range(2):
            self.view.prepend_performance_timings(.1, .2)
        self.assertTrue(self.view.show_result_location(location))
        wait_for_navigation(self.view)
        self.assertEqual(editor.textCursor().block().text(), "ERROR: needle")
        editor.selectAll()
        self.assertEqual(editor.createMimeDataFromSelection().text(), "before\nERROR: needle\nafter\n")
        self.view._search_input.setText("needle")
        self.view.search_results()
        wait_for_search(self.view)
        self.assertEqual(len(self.view._search_matches), 1)

    def test_replacing_source_invalidates_results_and_old_locations(self):
        editor = self.render(("ERROR: old",))
        location = self.view.model.location(0)
        self.view.show_source_line(10000001)
        wait_source(self.view)
        self.view.set_source(("ERROR: new",), 10000001, snapshot_id="replacement")
        self.assertIsNone(self.view.model)
        self.assertEqual(self.view.editor.toPlainText(), "")
        self.assertFalse(self.view.show_result_location(location))
        self.assertIsNone(self.view._return_position)
        wait_source(self.view)
        self.assertEqual(self.view.source_view.editor._block(0).text(), "ERROR: new")
