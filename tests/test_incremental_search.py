import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from qt_helpers import wait_for_load, wait_for_search
from logreader.qt_app import LogreaderWindow
from logreader.results_view import ResultsView


class IncrementalSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ResultsView()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)

    def search(self, text, query):
        self.view.editor.setPlainText(text)
        self.view._search_input.setText(query)
        self.view.search_results()

    def test_matches_agree_with_qt_across_chunks_and_unicode(self):
        text = ("😀aAa non\u00a0breaking café\n" * 70
                + "a" * 120 + "\nTARGET\nlast")
        for query in ("aaa", "😀", "non breaking", "CAFÉ", "a" * 45,
                      "TARGET", "missing", "TARGET\nlast"):
            with self.subTest(query=query), patch(
                "logreader.results_view.SEARCH_CHUNK_SIZE", 17
            ):
                self.search(text, query)
                expected = []
                position = 0
                while True:
                    match = self.view.editor.document().find(query, position)
                    if match.isNull():
                        break
                    expected.append((match.selectionStart(), match.selectionEnd()))
                    position = match.selectionEnd()
                wait_for_search(self.view)
                self.assertEqual(self.view._search_matches, tuple(expected))

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
        self.assertEqual(self.view._pending_matches, [])
        wait_for_search(self.view)
        self.assertEqual(self.view._search_count_label.text(), "No matches")
        self.assertEqual(self.view._search_matches, ())
        self.assertEqual(self.view._search_highlighter._matches, ())

    def test_result_changes_invalidate_pending_and_cached_searches(self):
        self.search("error\n" * 15000, "error")
        generation = self.view._search_generation
        self.view.editor.setPlainText("error replacement")
        self.view._advance_search(generation)
        self.assertFalse(self.view.is_searching)
        self.assertIsNone(self.view._searched_query)
        self.view.search_results()
        wait_for_search(self.view)
        self.assertEqual(self.view._search_count_label.text(), "0 / 1")
        matches = self.view._search_matches
        with patch.object(self.view, "_refresh_search_matches") as refresh:
            self.view.search_results()
            self.view.search_results()
            refresh.assert_not_called()
        self.assertIs(matches, self.view._search_matches)
        cursor = QTextCursor(self.view.editor.document())
        cursor.insertText("new ")
        self.assertIsNone(self.view._searched_query)
        self.assertEqual(self.view._search_matches, ())

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
        self.assertEqual(self.view._pending_matches, [])

    def test_highlighting_yields_and_clear_replaces_pending_formats(self):
        self.search("error\n" * 6000, "error")
        # Finish scanning explicitly; then inspect the separate paint stage.
        while self.view.is_searching:
            self.view._search_next_batch()
        highlighter = self.view._search_highlighter
        with patch("logreader.results_view.INCREMENTAL_SEARCH_BATCH_MS", 0):
            highlighter._highlight_next_batch()
        self.assertTrue(highlighter._highlight_timer.isActive())
        self.assertTrue(self.view.editor.document().begin().layout().formats())
        self.view._search_input.clear()
        # Further typing must not cancel the unfinished removal of old formats.
        self.view._search_input.setText("n")
        self.view._search_input.setText("new")
        wait_for_search(self.view)
        self.assertEqual(self.view.editor.document().begin().layout().formats(), [])
        self.assertEqual(highlighter._matches, ())

    def test_scrolling_prioritizes_visible_highlights_ahead_of_backlog(self):
        self.view.resize(800, 400)
        self.view.show()
        self.view.editor.setPlainText("error\n" * 20000)
        self.app.processEvents()
        self.view._search_input.setText("error")
        self.view.search_results()
        while self.view.is_searching:
            self.view._search_next_batch()
        highlighter = self.view._search_highlighter
        with patch("logreader.results_view.INCREMENTAL_SEARCH_BATCH_MS", 0):
            for position in (15000, 8000):
                self.view.editor.verticalScrollBar().setValue(position)
                visible = self.view.editor.firstVisibleBlock()
                self.assertGreater(visible.blockNumber(), 7000)
                highlighter._highlight_next_batch()
                self.assertTrue(visible.layout().formats())
                # The viewport was serviced before the beginning of the backlog.
                self.assertEqual(self.view.editor.document().begin().layout().formats(), [])
            self.view._search_input.clear()
            highlighter._highlight_next_batch()
            self.assertEqual(self.view.editor.firstVisibleBlock().layout().formats(), [])
        wait_for_search(self.view)
        self.assertEqual(
            self.view.editor.document().findBlockByNumber(15000).layout().formats(), [],
        )

    def test_sparse_highlighting_skips_unmatched_blocks(self):
        self.search("ordinary\n" * 20000 + "TARGET", "TARGET")
        while self.view.is_searching:
            self.view._search_next_batch()
        highlighter = self.view._search_highlighter
        with patch.object(highlighter, "rehighlightBlock", wraps=highlighter.rehighlightBlock) as paint:
            wait_for_search(self.view)
            self.assertEqual(paint.call_count, 1)
        self.assertTrue(self.view.editor.document().lastBlock().layout().formats())

    def test_switch_and_close_during_dense_search_keep_other_tab_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            window = LogreaderWindow()
            try:
                paths = [Path(directory) / name for name in ("one.log", "two.log")]
                for path in paths:
                    path.write_text("error\n", encoding="utf-8")
                window.load_files(paths)
                first = window._pages.widget(0)
                second = window._pages.widget(1)
                wait_for_load(first)
                wait_for_load(second)
                view = first.results_view
                second.results_view.editor.setPlainText("other results")
                view.editor.setPlainText("error\n" * 20000)
                view._search_input.setText("error")
                view.search_results()
                observations = []

                def switch():
                    window._tabs.setCurrentIndex(1)
                    observations.append((view.is_searching, window._document is second))

                QTimer.singleShot(0, switch)
                self.app.processEvents()
                self.assertEqual(observations, [(True, True)])
                generation = view._search_generation
                window.close_tab(0)
                view._advance_search(generation)
                self.assertFalse(view.is_searching)
                self.assertFalse(view._search_timer.isActive())
                self.assertFalse(view._search_highlighter._highlight_timer.isActive())
                self.assertEqual(second.results_view.editor.toPlainText(), "other results")
                self.assertIsNone(second.results_view._searched_query)
                second.results_view._search_input.setText("other")
                second.results_view.search_results()
                self.assertTrue(second.results_view.is_searching)
                window.close()
                self.assertFalse(second.results_view.is_searching)
                self.assertFalse(second.results_view._search_timer.isActive())
            finally:
                window.close()
                window.deleteLater()
