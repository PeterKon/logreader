import os
import unittest
import weakref
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from qt_helpers import wait_for_search
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.results_editor import StructuralBlock
from logreader.results_model import SourceLocation
from logreader.results_view import IncrementalAnalysisRenderer, ResultsView, prepend_performance_timings
from logreader.source_search import utf16_length
from logreader.theme import THEME_COLORS


class ResultsViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The Windows offscreen plugin needs an explicitly loaded font for QA.
        if os.path.exists("C:/Windows/Fonts/consola.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    def setUp(self):
        self.view = ResultsView()
        self.view.editor.setFont(QFont("Consolas", 11))
        self.view.resize(900, 550)
        self.view.show()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)

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
                    cursor = editor.document().find("Performance timing")
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
        for query, expected in (("matches", 0), ("10000001", 0), ("Analysis time", 0),
                                ("needle", 4), ("😀", 2), ("ERROR:", 2)):
            with self.subTest(query=query):
                self.view._search_input.setText(query)
                self.view.search_results()
                wait_for_search(self.view)
                self.assertEqual(len(self.view._search_matches), expected)
                for start, end in self.view._search_matches:
                    block = self.view.editor.document().findBlock(start)
                    self.assertIsNotNone(self.view._source_map.row(block.blockNumber()))
                    self.assertLessEqual(end, block.position() + block.length() - 1)

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
        for heading in ("Performance timing", "Matches:", "ERROR:"):
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
        self.assertIsNotNone(self.view._return_position)
        self.assertTrue(self.view.show_result_location(target))
        self.assertFalse(self.view.source_active)
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 120)
        self.assertIsNone(self.view._return_position)
        self.view.prepend_performance_timings(.1, .2)
        self.view.set_line_wrapping(True)
        self.assertTrue(self.view.show_result_location(target))
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 120)
        self.render(lines, replace(config, combined_view=True), new_snapshot=False)
        self.assertTrue(self.view.show_result_location(target))
        self.assertEqual(self.view._source_map.row(editor.textCursor().blockNumber()), 40)
        before = editor.textCursor().position()
        self.assertFalse(self.view.show_result_location(SourceLocation("different", 10000041)))
        self.assertFalse(self.view.show_result_location(SourceLocation("snapshot", 1)))
        self.assertEqual(editor.textCursor().position(), before)

    def test_reset_releases_completed_model_and_clears_gutter_projection_and_navigation(self):
        self.render(("ERROR: sample",))
        location = self.view.model.location(0)
        reference = weakref.ref(self.view.model)
        self.view.reset_for_loaded_file("new.log")
        self.assertIsNone(reference())
        self.assertIsNone(self.view.model)
        self.assertEqual(self.view.editor.gutter.width(), 0)
        self.assertFalse(self.view._source_map.starts)
        self.assertFalse(self.view.show_result_location(location))

    def test_cancelling_index_construction_releases_model_even_if_renderer_is_retained(self):
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        analysis = analyze_lines(("ERROR: sample", "skip") * 100,
                                 config.search_patterns(), combined=True)
        renderer = IncrementalAnalysisRenderer(1, self.view.editor, "sample", analysis, config)
        renderer.start()
        reference = weakref.ref(self.view.editor.model)
        with patch("logreader.results_view.INCREMENTAL_RENDER_BATCH_MS", 0):
            renderer._render_next_batch()
        self.assertFalse(self.view.editor.model.ready)
        renderer.cancel()
        self.assertIsNone(reference())
        self.assertIsNone(self.view.editor.model)
        self.assertFalse(self.view.editor.projection.starts)
        renderer.deleteLater()

    def test_timing_helper_keeps_raw_copy_search_and_source_mapping_aligned(self):
        editor = self.render(("before", "ERROR: needle", "after"))
        location = self.view.model.location(1)
        for _ in range(2):
            prepend_performance_timings(editor, .1, .2)
        self.assertTrue(self.view.show_result_location(location))
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
        self.view.set_source(("ERROR: new",), 10000001, snapshot_id="replacement")
        self.assertIsNone(self.view.model)
        self.assertEqual(editor.toPlainText(), "")
        self.assertFalse(self.view.show_result_location(location))
        self.assertIsNone(self.view._return_position)
        self.assertEqual(self.view.source_view.editor.toPlainText(), "ERROR: new")
