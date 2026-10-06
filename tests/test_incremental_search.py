import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from qt_helpers import render_results, wait_for_load, wait_for_navigation, wait_for_search
from logreader.ui.qt_app import LogreaderWindow
from logreader.ui.results.results_view import ResultsView


class IncrementalSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ResultsView()
        self.view.resize(800, 400)
        self.view.show()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)

    def search(self, text, query):
        render_results(self.view, text.splitlines(), complete=False)
        self.view._search_input.setText(query)
        self.view.search_results()

    def test_matches_agree_with_qt_across_chunks_and_unicode(self):
        text = "😀aAa non\u00a0breaking café\n" * 70 + "a" * 120 + "\nTARGET\nlast"
        for query in ("aaa", "😀", "non breaking", "CAFÉ", "a" * 45, "TARGET", "missing", "TARGET\nlast"):
            with self.subTest(query=query):
                self.search(text, query)
                expected = []
                for row, line in enumerate(text.splitlines()):
                    document = QTextDocument(line)
                    position = 0
                    while True:
                        match = document.find(query, position)
                        if match.isNull():
                            break
                        expected.append((row, match.selectionStart(), match.selectionEnd()))
                        position = match.selectionEnd()
                wait_for_search(self.view)
                self.assertEqual(tuple(self.view._search_matches), tuple(expected))

    def test_query_change_and_stale_batch_cannot_publish(self):
        self.search("error\n" * 15000, "error")
        generation = self.view._search_generation
        self.view._search_next_batch()
        self.assertTrue(self.view.is_searching)
        self.assertTrue(self.view._pending_matches)
        self.view._search_input.setText("missing")
        self.view.search_results()
        work = self.view._search_work
        self.view._advance_search(generation)
        self.assertIs(self.view._search_work, work)
        self.assertFalse(self.view._pending_matches)
        wait_for_search(self.view)
        self.assertEqual(self.view._search_count_label.text(), "No matches")
        self.assertFalse(self.view._search_matches)

    def test_replacement_invalidates_search_and_cached_matches_are_reused(self):
        self.search("error\n" * 15000, "error")
        generation = self.view._search_generation
        render_results(self.view, ("error replacement",))
        self.view._advance_search(generation)
        self.assertFalse(self.view.is_searching)
        self.assertIsNone(self.view._searched_query)
        self.view._search_input.setText("error")
        self.view.search_results()
        wait_for_search(self.view)
        self.assertEqual(self.view._search_count_label.text(), "0 / 1")
        matches = self.view._search_matches
        with patch.object(self.view, "_refresh_search_matches") as refresh:
            self.view.search_results()
            self.view.search_results()
            refresh.assert_not_called()
        self.assertIs(matches, self.view._search_matches)

    def test_sparse_search_yields_and_can_be_cancelled(self):
        self.search("ordinary line\n" * 30000, "missing")
        observations = []
        QTimer.singleShot(0, lambda: observations.append(self.view.is_searching))
        self.app.processEvents()
        self.assertEqual(observations, [True])
        self.view._search_input.clear()
        self.assertFalse(self.view.is_searching)
        self.assertFalse(self.view._search_timer.isActive())
        self.assertIsNone(self.view._search_work)
        self.assertFalse(self.view._pending_matches)

    def test_highlights_are_visible_only_and_clear_releases_formats(self):
        self.search("error\n" * 6000, "error")
        wait_for_search(self.view)
        self.assertTrue(self.view._formats)
        self.assertLess(len(self.view._formats), 100)
        self.view._search_input.clear()
        self.view._search_input.setText("n")
        self.view._search_input.setText("new")
        wait_for_search(self.view)
        self.assertFalse(self.view._formats)
        self.assertFalse(self.view._search_matches)

    def test_scrolling_highlights_destinations_before_intervening_rows(self):
        self.search("error\n" * 20000, "error")
        wait_for_search(self.view)
        editor = self.view.editor
        for position in (15000, 8000):
            self.view.global_scroll.setValue(position)
            wait_for_navigation(self.view)
            self.view._paint_decorations()
            self.assertTrue(editor.firstVisibleBlock().layout().formats())
            self.assertFalse(editor.ranges.contains(4000))
            self.assertLess(len(self.view._formats), 100)
        self.view._search_input.clear()
        wait_for_search(self.view)
        self.assertFalse(editor.firstVisibleBlock().layout().formats())

    def test_sparse_highlighting_leaves_unmatched_blocks_unformatted(self):
        self.search("ordinary\n" * 20000 + "TARGET", "TARGET")
        wait_for_search(self.view)
        self.assertEqual(self.view.format_updates, 0)
        self.view.find_next()
        wait_for_search(self.view)
        self.assertFalse(self.view.editor.ranges.contains(10000))
        self.assertTrue(self.view.editor.textCursor().block().layout().formats())

    def test_switch_and_close_during_dense_search_keep_other_tab_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            window = LogreaderWindow()
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
            paths = [Path(directory) / name for name in ("one.log", "two.log")]
            for path in paths:
                path.write_text("error\n", encoding="utf-8")
            window.load_files(paths)
            first, second = window._pages.widget(0), window._pages.widget(1)
            wait_for_load(first)
            wait_for_load(second)
            render_results(second.results_view, ("other results",))
            view = first.results_view
            render_results(view, ("error",) * 20000, complete=False)
            view._search_input.setText("error")
            view.search_results()
            window._tabs.setCurrentIndex(1)
            self.assertTrue(view.is_searching)
            generation = view._search_generation
            window.close_tab(0)
            view._advance_search(generation)
            self.assertFalse(view.is_searching)
            self.assertFalse(view._search_timer.isActive())
            self.assertEqual(second.results_view.model.line(0).text, "other results")
            self.assertIsNone(second.results_view._searched_query)
            second.results_view._search_input.setText("other")
            second.results_view.search_results()
            self.assertTrue(second.results_view.is_searching)
            window.close()
            self.assertFalse(second.results_view.is_searching)
