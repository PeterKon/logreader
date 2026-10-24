import unittest
from unittest.mock import patch

from source_test_case import SourceViewCase
from logreader.ui.results.result_coordinates import TextPoint


class SourceCacheTests(SourceViewCase):

    def test_pending_oversized_layout_survives_old_screen_refresh(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                lines = ["small row"] * 1000
                lines[700] = "long text " * 25000
                self.stage(tuple(lines))
                self.view.set_source_active(True)
                self.view.set_line_wrapping(wrapped)
                self.settle_source()
                editor, loader = self.source.editor, self.source.loader
                editor.cache_units = 65536
                editor.insert_range(700, 764)
                with patch.object(loader, "start"), patch.object(loader, "_cached_screen", return_value=None):
                    editor.navigate_to(TextPoint(700), move_caret=True)
                loader.timer.stop()
                request = editor.navigation.pending
                with editor.changing():
                    block = editor._prepare_block(700)
                count = block.layout().lineCount()
                self.assertGreater(count, 0)
                # Old-screen refreshes occur between preparation and the
                # queued navigation, and again while applying that navigation.
                editor._layout_visible()
                self.assertEqual(block.layout().lineCount(), count)
                prepare = editor._prepare_block
                cold = []

                def counted(row):
                    if row == 700 and not editor._block(row).layout().lineCount():
                        cold.append(row)
                    return prepare(row)

                with patch.object(editor, "_prepare_block", side_effect=counted):
                    editor.navigation.ready(request, immediate=True)
                    self.settle_source()
                self.assertEqual(cold, [])
                self.assertEqual(editor.caret, TextPoint(700))
                self.assertTrue(editor.viewport_evidence()["useful"])
                self.source.go_to_line(1)
                self.settle_source()
                self.assertNotIn(700, editor._cached_rows)
                self.assertEqual(block.layout().lineCount(), 0)
                self.assertEqual(block.text(), lines[700])
                self.assertLessEqual(editor._cached_units, editor.cache_units)

    def test_superseded_and_cancelled_oversized_layouts_can_be_evicted(self):
        lines = ["small row"] * 1000
        lines[700] = lines[800] = "long text " * 25000
        self.stage(tuple(lines))
        self.view.set_source_active(True)
        self.settle_source()
        editor, loader = self.source.editor, self.source.loader
        editor.cache_units = 65536
        editor.insert_range(700, 701)
        editor.insert_range(800, 801)
        with patch.object(loader, "start"), patch.object(loader, "_cached_screen", return_value=None):
            for row in (700, 800):
                editor.navigate_to(TextPoint(row))
                with editor.changing():
                    editor._prepare_block(row)
                editor._layout_visible()
                self.assertGreater(editor._block(row).layout().lineCount(), 0)
            self.assertNotIn(700, editor._cached_rows)
            editor.navigation.cancel()
            editor._trim_layout_cache()
        self.assertNotIn(800, editor._cached_rows)
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertEqual(editor._block(700).text(), lines[700])
        self.assertEqual(editor._block(800).text(), lines[800])

    def test_eof_preparation_keeps_oversized_row_in_pending_screen(self):
        lines = ["small row"] * 1000
        lines[-2] = "long text " * 25000
        self.stage(tuple(lines))
        self.view.set_source_active(True)
        self.settle_source()
        editor, loader = self.source.editor, self.source.loader
        editor.cache_units = 65536
        self.source.go_to_line(1000)
        # Drive preparation without dispatching navigation. The oversized
        # preceding row exhausts a turn before the EOF screen is complete.
        with patch.object(loader, "start"):
            for _ in range(50):
                loader.timer.stop()
                loader._tick()
                if 998 in editor._prepared_layouts:
                    break
        self.assertIsNotNone(editor.navigation.pending)
        self.assertIn(998, editor._prepared_layouts)
        self.assertGreater(editor._block(998).layout().lineCount(), 0)
        loader.start()
        self.settle_source()
        self.assertTrue(editor.at_bottom())
        self.assertTrue(editor.viewport_evidence()["useful"])

    def test_buffer_batches_preserve_alternating_coverage_and_budgets(self):
        for limit, giant in ((64, False), (3, False), (64, True)):
            with self.subTest(max_rows=limit, giant=giant):
                lines = [f"row {i}" for i in range(500)]
                if giant:
                    lines[198] = "x" * 100000
                self.stage(tuple(lines))
                self.view.set_source_active(True)
                self.settle_source()
                editor, loader = self.source.editor, self.source.loader
                editor.insert_range(200, 240)
                before = {r for a, b in editor.ranges.loaded_ranges for r in range(a, b)}
                count = editor.insertion_count
                loader.max_rows = limit
                loader.budget_ms = 100
                loader.buffer = [editor.navigation._sequence, 199, 240, 0, 0, 0]
                with patch.object(loader, "start"):
                    for _ in range(40):
                        if loader.buffer is None:
                            break
                        loader._tick()
                        self.assertIsNone(loader.error)
                        self.assertLessEqual(loader.ticks[-1]["rows"], limit)
                        self.assertLessEqual(loader.ticks[-1]["units"], loader.max_units)
                self.assertIsNone(loader.buffer)
                after = {r for a, b in editor.ranges.loaded_ranges for r in range(a, b)}
                expected = {199, 240} if giant else set(range(184, 200)) | set(range(240, 256))
                self.assertEqual(after - before, expected)
                for row in expected:
                    self.assertEqual(editor._block(row).text(), lines[row])
                if limit == 64:
                    self.assertEqual(editor.insertion_count - count, 2)
                self.assertFalse(loader.background)

    def test_buffer_supersession_discards_uncommitted_batch(self):
        self.stage(tuple(f"row {i}" for i in range(1000)))
        self.view.set_source_active(True)
        self.settle_source()
        editor, loader = self.source.editor, self.source.loader
        editor.insert_range(200, 240)
        loader.buffer = [editor.navigation._sequence, 199, 240, 0, 0, 0]
        insert = loader._insert

        def supersede(*args, **kwargs):
            inserted = insert(*args, **kwargs)
            self.source.go_to_line(800)
            return inserted

        with patch.object(loader, "_insert", side_effect=supersede):
            loader._tick()
        self.settle_source()
        self.assertEqual(editor.caret.row, 799)
        self.assertFalse(editor.ranges.contains(240))
        self.assertTrue(editor.ranges.contains(184))


if __name__ == "__main__":
    unittest.main()
