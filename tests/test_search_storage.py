import os
import random
import sys
import unittest
from bisect import bisect_left, bisect_right

from logreader.search_storage import BlockSet, SearchMatches


class SearchStorageTests(unittest.TestCase):
    def test_positions_preserve_order_ranges_and_64_bit_values(self):
        matches = SearchMatches()
        expected = [(0, 2), (10, 14), (2**32 + 7, 2**32 + 18)]
        for start, end in expected:
            matches.append(start, end)
        self.assertEqual(tuple(matches), tuple(expected))
        self.assertEqual(matches[-1], expected[-1])
        self.assertEqual(matches[1:], tuple(expected[1:]))
        self.assertEqual(bisect_left(matches.starts, 10), 1)
        self.assertEqual(bisect_right(matches.ends, 14), 2)
        with self.assertRaises(IndexError):
            _ = matches[3]

    def test_match_storage_is_packed_and_does_not_retain_python_pairs(self):
        matches = SearchMatches()
        for number in range(60000):
            matches.append(number * 10, number * 10 + 6)
        self.assertEqual(len(matches), 60000)
        self.assertLess(sys.getsizeof(matches.starts) + sys.getsizeof(matches.ends), 1_100_000)

    def test_block_state_matches_set_across_page_boundaries_and_reuse(self):
        actual = BlockSet()
        expected = set()
        randomizer = random.Random(42)
        numbers = [0, 1, 255, 256, 257, 511, 512, 2**31 - 1]
        numbers.extend(randomizer.randrange(10000) for _ in range(10000))
        for number in numbers:
            actual.add(number)
            expected.add(number)
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(set(actual), expected)
        for number in numbers[::3]:
            actual.discard(number)
            expected.discard(number)
            self.assertEqual(number in actual, number in expected)
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(expected))
        actual.clear()
        self.assertFalse(actual)
        self.assertEqual(list(actual), [])
        actual.add(255)
        actual.add(256)
        actual.discard(255)
        actual.discard(255)
        self.assertEqual(list(actual), [256])
        self.assertEqual(len(actual._pages), 1)

    def test_sparse_state_does_not_allocate_for_distance_between_blocks(self):
        blocks = BlockSet()
        for number in (0, 100_000_000, 2**31 - 1):
            blocks.add(number)
        self.assertEqual(len(blocks._pages), 3)
        self.assertLess(sys.getsizeof(blocks._pages), 1024)

    def test_ordered_snapshot_survives_mutation_before_and_during_iteration(self):
        blocks = BlockSet()
        expected = list(range(256)) + [300, 511, 512, 100000]
        for number in reversed(expected):
            blocks.add(number)
        snapshot = blocks.ordered_snapshot()
        blocks.clear()
        blocks.add(999)
        self.assertEqual(next(snapshot), 0)
        blocks.add(1)
        self.assertEqual(list(snapshot), expected[1:])
        self.assertEqual(list(blocks.ordered_snapshot()), [1, 999])


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_helpers import wait_for_search
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.results_view import ResultsView


class SearchStorageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ResultsView()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)

    def test_render_search_copy_and_rerender_do_not_accumulate_undo_history(self):
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        analysis = analyze_lines(("ERROR: needle",) * 300, config.search_patterns(), combined=True)
        for request_id in (1, 2):
            self.view.start_rendering(request_id, "sample.log", analysis, config)
            for _ in range(500):
                if not self.view.is_rendering:
                    break
                QTest.qWait(5)
            self.assertFalse(self.view.is_rendering)
            self.view.prepend_performance_timings(.1, .2)
            self.view._search_input.setText("needle")
            self.view.search_results()
            wait_for_search(self.view)
            self.assertEqual(len(self.view._search_matches), 300)
            self.view.find_next()
            editor = self.view.editor
            cursor = editor.document().find("ERROR: needle")
            editor.setTextCursor(cursor)
            # Exercise the clipboard payload without changing the user's clipboard.
            self.assertEqual(editor.createMimeDataFromSelection().text(), "ERROR: needle")
            document = editor.document()
            self.assertTrue(editor.isReadOnly())
            self.assertFalse(document.isUndoRedoEnabled())
            self.assertEqual(document.availableUndoSteps(), 0)
            self.assertFalse(document.isUndoAvailable())
            self.assertFalse(document.isRedoAvailable())
            self.view.reset_for_loaded_file("sample.log")
            self.assertEqual(document.availableUndoSteps(), 0)

    def test_publishes_same_packed_buffer_then_releases_it_on_new_query(self):
        self.view.editor.setPlainText("needle needle\n" * 3000)
        self.view._search_input.setText("needle")
        self.view.search_results()
        pending = self.view._pending_matches
        wait_for_search(self.view)
        self.assertIs(self.view._search_matches, pending)
        self.assertIs(self.view._search_highlighter._matches, pending)
        self.assertIsNot(self.view._pending_matches, pending)
        self.assertEqual(len(pending), 6000)
        self.view._search_input.clear()
        wait_for_search(self.view)
        self.assertFalse(self.view._search_matches)
        self.assertIsNot(self.view._search_highlighter._matches, pending)

    def test_wrapped_scroll_extent_selection_and_highlights_remain_stable(self):
        self.view.resize(600, 400)
        self.view.set_line_wrapping(True)
        self.view.show()
        self.view.editor.setPlainText(("needle " + "x" * 160 + " needle\n") * 2000)
        cursor = self.view.editor.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        self.view.editor.setTextCursor(cursor)
        self.view._search_input.setText("needle")
        self.view.search_results()
        wait_for_search(self.view)
        self.assertEqual(self.view.editor.textCursor().selectedText(), "edl")
        bar = self.view.editor.verticalScrollBar()
        maximum = bar.maximum()
        line_count = self.view.editor.document().lineCount()
        self.assertGreater(line_count, 4000)
        for fraction in (.9, .1, .5, 1., 0.):
            bar.setValue(round(maximum * fraction))
            self.app.processEvents()
            self.view.editor.viewport().repaint()
            self.app.processEvents()
            self.assertEqual(bar.maximum(), maximum)
            self.assertEqual(self.view.editor.document().lineCount(), line_count)
            block = self.view.editor.firstVisibleBlock()
            if "needle" in block.text():
                self.assertEqual(len(block.layout().formats()), 2)
        self.assertEqual(len(self.view._search_matches), 4000)
