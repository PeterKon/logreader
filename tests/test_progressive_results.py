"""Retained-range regressions transferred from the accepted viewer experiment."""
import os
import unittest
from time import perf_counter
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QTextCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.ui.results.results_view import ResultsView
from logreader.ui.results.result_coordinates import TextPoint
from logreader.ui.results.result_presentation import PresentationModel, Decoration
from logreader.ui.results.loaded_ranges import RangeIndex, UnloadedGap
from logreader.ui.results.results_model import ResultsModel
from logreader.ui.results.results_editor import ExcerptGapBlock, StructuralBlock, SummaryBlock
from logreader.ui.source_search import utf16_length
from logreader.ui.theme import THEME_COLORS

def sample(rows=6000, combined=False):
    events = (
        "INFO  Starting worker; service=payments region=eu-north-1",
        "INFO  Opening connection to database db-primary:5432",
        "ERROR: Connection refused; retrying in 5 seconds; request=8f24a1",
        "INFO  Retry scheduled; attempt=2 max_attempts=5",
        "INFO  Worker heartbeat received",
        "INFO  Health check completed; status=healthy",
        "INFO  Request accepted; route=/api/payments",
        "WARNING: Slow response from upstream; duration=2450ms",
        "INFO  Request completed; status=200 duration=2468ms",
        "INFO  Idle worker returned to pool",
        "INFO  Refreshing cached configuration",
        "INFO  Configuration unchanged; version=42",
        "INFO  Processing queued payment; queue=settlement",
        "ERROR: Request failed; upstream timeout; trace=af37c892",
        "INFO  Returning payment to queue; backoff=10s",
        "INFO  Queue depth=18 active_workers=4",
        "INFO  Metrics flushed successfully",
        "INFO  Request completed; status=200 duration=38ms",
    )
    lines = tuple(f"2026-09-29 10:{i // 60 % 60:02}:{i % 60:02}  {events[i % len(events)]}" for i in range(rows))
    config = LogreaderConfig(context=1, combined_view=combined, separate_entries=True,
                             enabled_patterns=("error_colon", "warning"))
    analysis = analyze_lines(lines, config.search_patterns(), combined=combined)
    model = ResultsModel(analysis, "appearance-preview")
    list(model.prepare())
    return lines, config, model


def prepared_model(lines, *, combined=True, custom=(), context=0, line_offset=10000):
    config = LogreaderConfig(context=context, combined_view=combined,
                            enabled_patterns=("error_colon",), custom_patterns=custom)
    model = ResultsModel(analyze_lines(tuple(lines), config.search_patterns(),
                                     combined=combined, line_offset=line_offset), "prototype")
    for _ in model.prepare():
        pass
    return model


class PaintObserver(QObject):
    def __init__(self, editor, widget):
        super().__init__(widget)
        self.editor = editor
        self.rows = []
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.rows.append(self.editor.top_point())
        return False


def slider_rect(bar):
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                     QStyle.SubControl.SC_ScrollBarSlider, bar)


class ProgressiveResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for name in ("consola.ttf", "consolab.ttf"):
            path = "C:/Windows/Fonts/" + name
            if os.path.exists(path):
                QFontDatabase.addApplicationFont(path)

    def window(self, *, fraction=.01, wrapped=False, lines=None):
        if lines is None:
            lines, config, model = sample(12000)
        else:
            config = LogreaderConfig(context=0, combined_view=True, enabled_patterns=("error_colon",))
            model = prepared_model(lines)
        view = ResultsView()
        view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        view.resize(780, 400)
        view.set_source(tuple(lines), max(model.max_source_line, len(lines)), snapshot_id=model.snapshot_id)
        view._install_presentation(PresentationModel(model, config))
        view.loader.background = False
        view._render_request_id = 1
        view._render_started = perf_counter()
        total = view.editor.ranges.total
        view.initial_end = (view.loader._commit_end(0, min(total, 64)) if fraction is None
                            else min(total, max(1, round(total * fraction))))
        view.editor.insert_range(0, view.initial_end)
        view._line_wrap_check.setChecked(wrapped)
        view.show()
        self.app.processEvents()
        with view.editor.changing():
            view.editor.set_top(TextPoint(0))
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        return view

    def background(self, view):
        view.loader.background = True
        view.loader.start()

    def wait_jump(self, editor):
        for _ in range(1000):
            if editor.navigation.pending is None:
                self.app.processEvents()
                # A newly visible horizontal scrollbar can resize the view
                # and request a corrected final screen during event delivery.
                if editor.navigation.pending is None:
                    return
            QTest.qWait(2)
        self.fail("Requested screen did not finish")


    def jump(self, editor, row, column=0):
        editor.navigate_to(TextPoint(row, column))
        self.wait_jump(editor)


    def wait(self, predicate):
        for _ in range(2000):
            if predicate():
                return
            QTest.qWait(2)
        self.fail("Timed out waiting for cooperative work")


    def finish_wheel(self, editor):
        deadline = perf_counter() + 10
        while editor._pending_wheel and perf_counter() < deadline:
            self.app.processEvents()
            QTest.qWait(1)
        self.assertFalse(editor._pending_wheel)
        self.app.processEvents()


    def wheel(self, editor, *, angle=0, pixels=0, phase=Qt.ScrollPhase.NoScrollPhase,
              modifiers=Qt.KeyboardModifier.NoModifier):
        event = QWheelEvent(QPointF(30, 30), QPointF(30, 30), QPoint(0, pixels),
                            QPoint(0, angle), Qt.MouseButton.NoButton,
                            modifiers, phase, False)
        QApplication.sendEvent(editor.viewport(), event)


    def quiet(self, view):
        view.editor.navigation.cancel()
        view.loader.buffer = None
        view.loader.timer.stop()


    def state(self, editor):
        point = editor.top_point()
        return (point, editor.point_y(point), editor.anchor, editor.caret, editor.selected_text(),
                editor.horizontalScrollBar().value())


    def assert_final_screen(self, view):
        editor = view.editor
        evidence = editor.viewport_evidence()
        self.assertTrue(editor.at_bottom())
        self.assertEqual(evidence["rows"][-1], editor.ranges.total - 1)
        self.assertGreaterEqual(evidence["bottom"], editor.viewport().height() - editor.fontMetrics().height() - 2)
        self.assertLessEqual(evidence["bottom"], editor.viewport().height() + 2)
        self.assertEqual(view.global_scroll.value(), view.global_scroll.maximum())

    def test_scrollbar_disappears_when_results_fit_and_returns_after_resize(self):
        view = self.window(fraction=1, lines=[f"ERROR: row {i}" for i in range(20)])
        editor, bar = view.editor, view.global_scroll
        view.resize(780, 900)
        self.wait(lambda: editor.end_top() == TextPoint(0) and bar.isHidden())
        self.assertEqual(bar.maximum(), 0)
        view.resize(780, 220)
        self.wait(lambda: editor.end_top() is not None and bar.isVisible() and bar.maximum() > 0)
        self.assertEqual(editor.top_point(), TextPoint(0))
        bar.setValue(bar.maximum())
        self.wait_jump(editor)
        self.assert_final_screen(view)
        view.resize(780, 900)
        self.wait(lambda: editor.end_top() == TextPoint(0) and bar.isHidden())
        self.assertEqual(editor.top_point(), TextPoint(0))
        self.assertEqual(bar.maximum(), 0)

    def test_scrollbar_drag_has_no_unused_travel_after_the_final_screen(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                lines = [f"ERROR: row {i}" for i in range(100)]
                if wrapped:
                    lines[-1] += " long wrapped payload" * 300
                view = self.window(fraction=1, wrapped=wrapped, lines=lines)
                editor, bar = view.editor, view.global_scroll
                self.wait(lambda: editor.end_top() is not None)
                endpoint = editor.end_top()
                if wrapped:
                    self.assertGreater(endpoint.column, 0)
                else:
                    self.assertLess(bar.maximum(), editor.presentation.row_count - 1)
                maximum = bar.maximum()
                previous = TextPoint(0)
                bar.setSliderDown(True)
                try:
                    for value in range(maximum - 3, maximum + 1):
                        bar.setSliderPosition(value)
                        self.wait_jump(editor)
                        self.assertGreater(editor.top_point(), previous)
                        self.assertEqual(bar.maximum(), maximum)
                        self.assertEqual(bar.value(), value)
                        previous = editor.top_point()
                    self.assertEqual(editor.top_point(), endpoint)
                finally:
                    bar.setSliderDown(False)
                self.assert_final_screen(view)
                bar.setValue(0)
                self.wait_jump(editor)
                self.assertEqual(editor.top_point(), TextPoint(0))

    def test_resize_keeps_scrollbar_range_stable_until_new_geometry_is_ready(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                view = self.window(fraction=1, wrapped=wrapped,
                                   lines=[f"ERROR: row {i}" for i in range(60)])
                editor, bar = view.editor, view.global_scroll
                self.wait(lambda: editor.end_top() is not None)
                pending_paints = 0
                for bottom in (False, True):
                    bar.setValue(bar.maximum() if bottom else bar.maximum() // 2)
                    self.wait_jump(editor)
                    for height in (420, 440, 430, 400):
                        before = bar.maximum()
                        top = editor.top_point()
                        updates = []
                        before_image = bar.grab().toImage()
                        set_range = bar.setRange

                        def record_range(minimum, maximum):
                            set_range(minimum, maximum)
                            updates.append(bar.maximum())

                        with patch.object(bar, "setRange", side_effect=record_range):
                            view.resize(view.width(), height)
                            self.assertTrue(bar.updatesEnabled())
                            if editor.end_top() is None:
                                pending_paints += 1
                                pending_image = bar.grab().toImage()
                                shared_height = min(before_image.height(), pending_image.height())
                                self.assertEqual(
                                    before_image.copy(0, 0, before_image.width(), shared_height),
                                    pending_image.copy(0, 0, pending_image.width(), shared_height))
                                for y in range(pending_image.height()):
                                    self.assertEqual(pending_image.pixelColor(0, y).name(),
                                                     THEME_COLORS["scrollbar_track"])
                            self.wait(lambda: editor.end_top() is not None
                                      and editor.navigation.pending is None)
                            self.app.processEvents()
                        after = bar.maximum()
                        self.assertTrue(updates)
                        self.assertTrue(all(min(before, after) <= value <= max(before, after)
                                            for value in updates), updates)
                        self.assertTrue(bar.updatesEnabled())
                        if bottom:
                            self.assert_final_screen(view)
                        else:
                            self.assertEqual(editor.top_point(), top)
                self.assertGreater(pending_paints, 0)


    def test_resize_remeasures_known_endpoint_without_loading_all_results(self):
        view = self.window(fraction=.01, lines=[f"ERROR: row {i}" for i in range(2000)])
        editor, bar = view.editor, view.global_scroll
        self.jump(editor, editor.ranges.total - 1)
        self.jump(editor, 500)
        self.quiet(view)
        top, maximum = editor.top_point(), bar.maximum()
        view.resize(view.width(), 900)
        self.wait(lambda: editor.end_top() is not None)
        self.assertLess(bar.maximum(), maximum)
        self.assertEqual(bar.maximum(), editor.end_scroll_maximum())
        self.assertEqual(editor.top_point(), top)
        self.assertFalse(view.loader.done)

    def test_compact_index_scales_with_intervals_and_round_trips(self):
        index = RangeIndex(10**9)
        index.fill(0, 100)
        index.fill(900000000, 900000050)
        self.assertEqual(index.loaded_count, 150)
        self.assertEqual(index.block_count, 155)
        for row in (0, 99, 900000000, 900000049):
            self.assertEqual(index.logical_at(index.block_for(row)), row)
        self.assertIsNone(index.block_for(800000000))
        self.assertEqual(index.logical_at(100), UnloadedGap(100, 900000000))
        index.fill(100, 900000000)
        self.assertEqual(index.loaded_ranges, [(0, 900000050)])


    def test_scattered_insertions_keep_bounded_scalar_history_and_exact_totals(self):
        view = self.window(lines=[f"ERROR: row {i}" for i in range(5000)], fraction=None)
        editor = view.editor
        initial_rows, initial_count = editor.inserted_rows, editor.insertion_count
        for i in range(editor.insertion_history_limit + 40):
            start = 128 + i * 8
            editor.insert_range(start, start + 1)
        self.assertEqual(len(editor.insertions), editor.insertion_history_limit)
        self.assertEqual(editor.insertion_count, initial_count + editor.insertion_history_limit + 40)
        self.assertEqual(editor.inserted_rows, initial_rows + editor.insertion_history_limit + 40)
        self.assertEqual(editor.inserted_rows, editor.ranges.loaded_count)
        self.assertGreater(len(editor.ranges.loaded_ranges), editor.insertion_history_limit)
        self.assertEqual([record['sequence'] for record in editor.insertions],
                         list(range(editor.insertion_count - editor.insertion_history_limit + 1,
                                    editor.insertion_count + 1)))
        self.assertTrue(all(isinstance(value, (int, float))
                            for record in editor.insertions for value in record.values()))
        editor.insert_range(128, 129)
        self.assertEqual(editor.inserted_rows, editor.ranges.loaded_count)
        editor.set_results(editor.presentation)
        self.assertEqual((editor.insertion_count, editor.inserted_rows, editor.insertions), (0, 0, []))


    def test_far_destination_precedes_intervening_insertion_at_both_initial_fractions(self):
        for fraction in (.01, .10):
            with self.subTest(fraction=fraction):
                view = self.window(fraction=fraction)
                editor = view.editor
                document = editor.document()
                initial = editor.ranges.loaded_count
                row = int(editor.presentation.row_count * .9)
                top = editor.top_point()
                editor.navigate_to(TextPoint(row))
                self.assertEqual(editor.top_point(), top)
                self.assertFalse(editor.ranges.contains(row))
                self.wait_jump(editor)
                self.assertEqual(editor.top_point().row, row)
                self.assertTrue(editor.viewport_evidence()["useful"])
                self.assertFalse(editor.ranges.contains((initial + row) // 2))
                self.assertEqual(editor.ranges.loaded_ranges[0], (0, initial))
                self.assertLess(editor.ranges.loaded_count, initial + editor._screen_rows() + 70)
                self.assertEqual(document.blockCount(), editor.ranges.loaded_count + 2 * len(editor.ranges.gaps)
                                 + editor.ranges.guard_count + 1)
                self.assertIs(editor.document(), document)
                self.assertEqual(editor.created_documents, 1)
                self.assertFalse(document.isUndoAvailable())


    def test_headings_excerpt_gaps_and_utf16_positions_survive_reverse_order_fills(self):
        view = self.window()
        editor = view.editor
        total = editor.presentation.row_count
        for start, end in ((total * 2 // 3, total), (total // 3, total * 2 // 3), (0, total // 3)):
            editor.insert_range(start, end)
        self.assertFalse(editor.ranges.gaps)
        for row in range(total):
            block = editor._block(row)
            self.assertEqual(block.text(), editor.presentation.line(row).text)
            for column in (0, block.length() - 1):
                point = TextPoint(row, column)
                self.assertEqual(editor.location_at(editor.position_for(point)), point)
            entry = editor.presentation.entry(row)
            if isinstance(entry, Decoration):
                self.assertIsInstance(block.userData(), StructuralBlock)
                self.assertEqual(isinstance(block.userData(), SummaryBlock), entry.kind == "summary")
                self.assertEqual(isinstance(block.userData(), ExcerptGapBlock), entry.kind == "gap")
                self.assertIsNone(editor.source_number(block.blockNumber()))
            else:
                self.assertEqual(editor.source_number(block.blockNumber()), editor.presentation.line(row).number)
        before = editor.document().characterCount()
        self.assertEqual(editor.insert_range(12, total - 3), 0)
        self.assertEqual(editor.document().characterCount(), before)


    def test_unloaded_positions_are_explicit_gaps_not_invented_log_rows(self):
        view = self.window()
        editor = view.editor
        row = editor.presentation.row_count // 2
        self.assertIsNone(editor.position_for(TextPoint(row, 12)))
        number = editor.ranges.block_for(row, project_gap=True)
        block = editor.document().findBlockByNumber(number)
        self.assertEqual(editor.location_at(block.position()), UnloadedGap(view.initial_end, editor.presentation.row_count))
        self.assertIsNone(editor.source_number(number))


    def test_fill_earlier_gap_preserves_wrapped_offset_horizontal_and_reverse_selection(self):
        lines = [f"ERROR: {i:05} alpha β 😀 omega " + "payload " * 100 for i in range(1400)]
        for wrapped in (False, True):
            for reverse in (False, True):
                with self.subTest(wrapped=wrapped, reverse=reverse):
                    view = self.window(wrapped=wrapped, lines=lines)
                    editor = view.editor
                    row = editor.presentation.display_row(1250)
                    # Explicitly retain a few adjacent rows for native selection.
                    editor.insert_range(row, row + 8)
                    self.jump(editor, row)
                    pair = (TextPoint(row, 20), TextPoint(row + 1, 34))
                    editor.select(*(reversed(pair) if reverse else pair))
                    self.wait_jump(editor)
                    self.jump(editor, row, 180 if wrapped else 0)
                    if not wrapped:
                        editor.horizontalScrollBar().setValue(120)
                    self.app.processEvents()
                    before = (editor.top_point(), editor.anchor, editor.caret,
                              editor.selected_text(), editor.horizontalScrollBar().value())
                    retained = editor._block(row)
                    revision = retained.userState()
                    native_before = retained.blockNumber()
                    first, last = editor.ranges.gaps[0]
                    editor.insert_range(first, min(last, first + 80))
                    self.app.processEvents()
                    after = (editor.top_point(), editor.anchor, editor.caret,
                             editor.selected_text(), editor.horizontalScrollBar().value())
                    self.assertEqual(after, before)
                    self.assertTrue(retained.isValid())
                    self.assertEqual(retained.userState(), revision)
                    self.assertGreater(retained.blockNumber(), native_before)
                    self.assertEqual(editor.location_at(editor.textCursor().anchor()), editor.anchor)
                    self.assertEqual(editor.location_at(editor.textCursor().position()), editor.caret)
                    for point in pair:
                        self.assertEqual(editor.location_at(editor.position_for(point)), point)


    def test_background_fill_does_not_layout_every_retained_row_or_replace_document(self):
        view = self.window()
        editor = view.editor
        row = int(editor.presentation.row_count * .9)
        self.jump(editor, row)
        top = editor.top_point()
        before = editor.layout_visits
        initial = view.initial_end
        for start in range(initial, initial + 1024, 64):
            editor.insert_range(start, start + 64)
            self.app.processEvents()
            self.assertEqual(editor.top_point(), top)
        self.assertEqual(editor.layout_visits, before)
        self.assertEqual(editor._block(initial + 500).layout().lineCount(), 0)


    def test_newest_request_and_cancel_after_preparation_do_not_move_old_screen(self):
        view = self.window()
        editor = view.editor
        total = editor.presentation.row_count
        editor.navigate_to(TextPoint(total * 9 // 10))
        obsolete = editor.navigation.pending
        editor.navigate_to(TextPoint(total // 2))
        editor.navigation.ready(obsolete)
        self.wait_jump(editor)
        self.assertEqual(editor.top_point().row, total // 2)
        self.assertFalse(editor.ranges.contains(total * 9 // 10))
        # A cached screen now finishes inline. Use a missing destination to
        # exercise cancellation between preparation and queued application.
        editor.navigate_to(TextPoint(total // 3))
        self.assertIsNotNone(editor.navigation.pending)
        editor.navigation.ready(editor.navigation.pending)
        editor.navigation.cancel()
        QTest.qWait(10)
        self.assertEqual(editor.top_point().row, total // 2)


    def test_actual_track_click_and_thumb_release_load_chosen_range(self):
        view = self.window()
        bar, editor = view.global_scroll, view.editor
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        groove = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                          QStyle.SubControl.SC_ScrollBarGroove, bar)
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                         pos=QPoint(groove.center().x(), groove.top() + int(groove.height() * .9)))
        self.wait_jump(editor)
        first = editor.top_point().row
        self.assertGreater(first, editor.presentation.row_count * .8)
        self.assertFalse(editor.ranges.contains(editor.presentation.row_count // 2))
        bar.initStyleOption(option)
        slider = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                          QStyle.SubControl.SC_ScrollBarSlider, bar)
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=slider.center())
        QTest.mouseMove(bar, QPoint(groove.center().x(), groove.top() + int(groove.height() * .6)))
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton,
                           pos=QPoint(groove.center().x(), groove.top() + int(groove.height() * .6)))
        self.wait_jump(editor)
        self.assertLess(editor.top_point().row, first)
        self.assertTrue(editor.viewport_evidence()["useful"])
        self.assertEqual(bar.value(), editor.top_point().row)


    def test_giant_destination_layout_survives_earlier_fills_and_merge(self):
        lines = ["ERROR: ordinary payload"] * 1200
        lines[1080] = "ERROR: " + "x" * 250000
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                view = self.window(lines=lines, wrapped=wrapped)
                editor = view.editor
                row = editor.presentation.display_row(1080)
                self.jump(editor, row, 1000 if wrapped else 0)
                retained = editor._block(row)
                layout = retained.layout()
                line_count = layout.lineCount()
                before = editor.layout_visits
                top = editor.top_point()
                for start in range(view.initial_end, row, 64):
                    editor.insert_range(start, min(row, start + 64))
                    self.app.processEvents()
                    self.assertEqual(editor.top_point(), top)
                    self.assertEqual(layout.lineCount(), line_count)
                self.assertIs(editor._block(row).layout(), layout)
                self.assertEqual(editor.layout_visits, before)
                self.assertTrue(editor.viewport_evidence()["useful"])


    def test_completion_has_exact_unique_coverage_and_retains_later_selection(self):
        view = self.window(lines=[f"ERROR: row {n} alpha β 😀" for n in range(400)])
        editor = view.editor
        row = editor.presentation.display_row(350)
        self.jump(editor, row)
        editor.select(TextPoint(row + 1, 20), TextPoint(row, 10))
        self.wait_jump(editor)
        before = editor.top_point(), editor.anchor, editor.caret, editor.selected_text()
        view.loader.background = True
        view.loader.start()
        for _ in range(1000):
            if not editor.ranges.gaps:
                break
            QTest.qWait(2)
        self.assertFalse(editor.ranges.gaps)
        self.assertEqual(editor.ranges.loaded_ranges, [(0, editor.presentation.row_count)])
        self.assertEqual(editor.ranges.loaded_count, editor.presentation.row_count)
        self.assertEqual((editor.top_point(), editor.anchor, editor.caret, editor.selected_text()), before)
        for row in range(editor.presentation.row_count):
            self.assertEqual(editor._block(row).text(), editor.presentation.line(row).text)


    def test_retained_frame_matches_fresh_paint_and_invalidates_on_interaction(self):
        view = self.window(lines=["ERROR: alpha β 😀 " + "payload " * 80 for _ in range(1500)])
        editor = view.editor
        row = editor.presentation.display_row(1350)
        self.jump(editor, row)
        editor.select(TextPoint(row, 15), TextPoint(row + 1, 30))
        self.wait_jump(editor)
        editor.insert_range(view.initial_end, view.initial_end + 64)
        self.app.processEvents()
        def pixels():
            # A viewport-local grab changes the raster origin at fractional
            # scale. Compare actual window pixels on their physical grid.
            image = view.grab().toImage()
            scale = view.devicePixelRatioF()
            origin = editor.mapTo(view, QPoint())
            return image.copy(round(origin.x() * scale), round(origin.y() * scale),
                              round(editor.width() * scale), round(editor.height() * scale))
        retained = pixels()
        self.assertIsNotNone(editor._retained_frame)
        selection = editor.anchor, editor.caret, editor.selected_text()
        previous = retained
        for target in (editor._block(row), editor._block(row + 1), None):
            editor.set_context_target(target)
            self.assertIsNone(editor._retained_frame)
            current = pixels()
            self.assertNotEqual(current, previous)
            editor._retain_frame()
            self.assertEqual(pixels(), current)
            previous = current
        self.assertEqual(previous, retained)
        self.assertEqual((editor.anchor, editor.caret, editor.selected_text()), selection)
        editor._retained_frame = None
        self.assertEqual(pixels(), retained)
        editor.insert_range(view.initial_end + 64, view.initial_end + 128)
        self.assertIsNotNone(editor._retained_frame)
        editor.select(TextPoint(row, 0), TextPoint(row, 5))
        self.wait_jump(editor)
        self.assertIsNone(editor._retained_frame)
        self.assertNotEqual(pixels(), retained)
        editor.insert_range(view.initial_end + 128, view.initial_end + 192)
        editor.scroll_visual_lines(2)
        self.app.processEvents()
        self.assertIsNone(editor._retained_frame)


    def test_cached_upward_navigation_restores_once_like_downward_navigation(self):
        view = self.window(lines=["ERROR: ordinary payload"] * 6000)
        view.resize(1180, 900)
        editor = view.editor
        editor.insert_range(0, editor.ranges.total)
        self.jump(editor, 1000)
        self.jump(editor, 4000)
        self.quiet(view)
        for row in (1000, 4000):
            with patch.object(editor, "_set_top_local", wraps=editor._set_top_local) as restore:
                self.jump(editor, row)
                self.assertLessEqual(restore.call_count, 2)
                self.assertEqual(editor.top_point().row, row)


    def test_gutter_and_overlay_receive_normal_paint_events_after_completed_navigation(self):
        view = self.window()
        editor = view.editor
        self.background(view)
        self.wait(lambda: view.loader.done)
        self.assertEqual(view.loading_status, "Results loaded")
        self.quiet(view)
        QTest.qWait(20)
        gutter = PaintObserver(editor, editor.gutter)
        overlay = PaintObserver(editor, editor.structure_area)
        for row in (editor.ranges.total * 8 // 10, editor.ranges.total // 5):
            gutter.rows.clear()
            overlay.rows.clear()
            self.jump(editor, row)
            QTest.qWait(20)
            # No grab(), render(), repaint(), selection, or forced update.
            self.assertIn(editor.top_point(), gutter.rows)
            self.assertIn(editor.top_point(), overlay.rows)
            self.assertEqual(editor.top_point().row, row)


    def test_copy_full_result_and_unloaded_utf16_endpoints_preserves_screen(self):
        lines = [f"ERROR: {i:04} \tα😀\u00a0omega  " for i in range(700)]
        view = self.window(lines=lines, wrapped=True)
        editor = view.editor
        row = editor.presentation.display_row(600)
        self.jump(editor, row)
        self.quiet(view)
        top = editor.top_point()
        first, last = 210, 390
        left = utf16_length(lines[first].split("😀")[0])
        right = utf16_length(lines[last].split("😀")[0] + "😀")
        expected = "\n".join([lines[first][lines[first].index("😀"):], *lines[first+1:last],
                              lines[last][:lines[last].index("😀") + 1]])
        points = TextPoint(editor.presentation.display_row(first), left), TextPoint(editor.presentation.display_row(last), right)
        self.assertFalse(editor.ranges.contains(points[0].row))
        self.assertFalse(editor.ranges.contains(points[1].row))
        self.addCleanup(self.app.clipboard().clear)
        for pair in (points, tuple(reversed(points))):
            editor.select(*pair)
            self.assertEqual(editor.top_point(), top)
            QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(self.app.clipboard().text(), expected)
            editor.insert_range(points[0].row + 4, points[0].row + 10)
            self.assertEqual((editor.anchor, editor.caret), pair)
            self.assertEqual(editor.selected_text(), expected)
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.top_point(), top)
        QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), "\n".join(lines) + "\n")
        editor.insert_range(0, editor.ranges.total)
        self.assertEqual(editor.top_point(), top)
        QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), "\n".join(lines) + "\n")


    def test_structural_rows_are_excluded_from_copy_across_multiple_unloaded_gaps(self):
        view = self.window()
        editor = view.editor
        first, last = 120, 180
        a, b = editor.presentation.display_row(first), editor.presentation.display_row(last)
        logical = editor.presentation.logical
        expected = logical.line(first).text[7:] + "\n"
        expected += "".join(logical.line(row).text + "\n" for row in range(first + 1, last))
        expected += logical.line(last).text[:12]
        # Source offsets here are ASCII; the separate UTF-16 test covers emoji.
        editor.insert_range(a, a + 2)
        editor.insert_range(b, b + 2)
        editor.select(TextPoint(a, 7), TextPoint(b, 12))
        self.assertEqual(editor.selected_text(), expected)
        editor.insert_range(a + 2, b)
        self.assertEqual(editor.selected_text(), expected)
        self.assertEqual(editor.location_at(editor.textCursor().anchor()), editor.anchor)
        self.assertEqual(editor.location_at(editor.textCursor().position()), editor.caret)


    def test_filling_and_merging_every_gap_preserves_reading_selection_and_horizontal_position(self):
        lines = [f"ERROR: row {i:04} α😀 " + "payload\twords " * 25 for i in range(700)]
        for wrapped in (False, True):
            for logical_row in (3, 350, 690):
                for reverse in (False, True):
                    with self.subTest(wrapped=wrapped, logical_row=logical_row, reverse=reverse):
                        view = self.window(lines=lines, wrapped=wrapped)
                        editor = view.editor
                        row = editor.presentation.display_row(logical_row)
                        editor.insert_range(row, row + 3)
                        self.jump(editor, row, 180 if wrapped else 0)
                        self.quiet(view)
                        points = (TextPoint(row, 10), TextPoint(row + 1, 32))
                        editor.select(*(reversed(points) if reverse else points))
                        if not wrapped:
                            editor.horizontalScrollBar().setValue(120)
                        before = self.state(editor)
                        retained = editor._block(row)
                        revision = retained.userState()
                        maximum = view.global_scroll.maximum()
                        # Create an island inside a gap, then join both sides.
                        editor.insert_range(200, 215)
                        editor.insert_range(100, 200)
                        editor.insert_range(215, 280)
                        self.assertEqual(self.state(editor), before)
                        for start, end in reversed(editor.ranges.gaps):
                            for part in range(start, end, 64):
                                editor.insert_range(part, min(end, part + 64))
                                self.app.processEvents()
                                self.assertEqual(self.state(editor), before)
                                end_maximum = editor.end_scroll_maximum()
                                self.assertEqual(view.global_scroll.maximum(),
                                                 maximum if end_maximum is None else end_maximum)
                        self.assertFalse(editor.ranges.gaps)
                        self.assertTrue(retained.isValid())
                        self.assertEqual(retained.userState(), revision)
                        self.assertEqual(editor.location_at(editor.textCursor().anchor()), editor.anchor)
                        self.assertEqual(editor.location_at(editor.textCursor().position()), editor.caret)
                        view.loader._tick()
                        self.assertEqual(view.loading_status, "Results loaded")
                        self.assertEqual(self.state(editor), before)


    def test_selection_drag_loads_adjacent_text_and_release_stops_automatic_navigation(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                view = self.window(lines=[f"ERROR: row {i:04} α😀 whitespace  " for i in range(1600)])
                editor = view.editor
                # Boundary movement must work without incidental prefetch.
                view.loader.buffer_rows = 0
                row = editor.presentation.display_row(800)
                editor.insert_range(row, row + 30)
                with editor.changing():
                    editor.set_top(TextPoint(row))
                self.quiet(view)
                start = QPoint(120, 25)
                QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=start)
                anchor = editor.anchor
                outside = QPoint(170, editor.viewport().height() + 20 if direction > 0 else -20)
                QTest.mouseMove(editor.viewport(), outside)
                QTest.qWait(300)
                self.assertTrue(editor._dragging)
                self.assertEqual(editor.anchor, anchor)
                self.assertGreater((editor.top_point().row - row) * direction, 6)
                self.assertGreater((editor.caret.row - row) * direction, 6)
                self.assertTrue(editor.ranges.contains(editor.caret.row))
                QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=outside)
                state = self.state(editor)
                QTest.qWait(40)
                self.assertEqual(self.state(editor), state)
                self.assertIsNone(editor.navigation.pending)
                self.assertEqual(editor.location_at(editor.textCursor().anchor()), editor.anchor)
                self.assertEqual(editor.location_at(editor.textCursor().position()), editor.caret)
                self.assertIn("α😀", editor.selected_text())


    def test_cold_upward_preparation_preserves_wrapped_point_between_turns(self):
        view = self.window(lines=[f"ERROR: row {i} " + "payload " * 130 for i in range(1200)], wrapped=True)
        editor, loader = view.editor, view.loader
        self.jump(editor, editor.presentation.display_row(1000), 240)
        self.quiet(view)
        top = editor.top_point()
        editor.select(TextPoint(top.row + 1, 27), TextPoint(top.row, 15))
        before = self.state(editor)
        editor.navigate_to(TextPoint(editor.presentation.display_row(500), 100))
        loader.budget_ms = .5
        for _ in range(100):
            loader._tick()
            self.assertEqual(self.state(editor), before)
            if editor.navigation._ready:
                break
        self.assertIsNotNone(editor.navigation._ready)
        editor.navigation.cancel()
        self.app.processEvents()
        self.assertEqual(self.state(editor), before)


    def test_releasing_selection_drag_cancels_its_waiting_boundary_request(self):
        view = self.window(lines=[f"ERROR: row {i:04} α😀 text" for i in range(1600)])
        editor, loader = view.editor, view.loader
        loader.buffer_rows = 0
        row = editor.presentation.display_row(800)
        editor.insert_range(row, row + 40)
        with editor.changing():
            editor.set_top(TextPoint(row))
        self.quiet(view)
        loader.interval_ms = 1000
        QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(110, 25))
        outside = QPoint(150, -20)
        QTest.mouseMove(editor.viewport(), outside)
        self.wait(lambda: editor.navigation.pending is not None)
        request = editor.navigation.pending
        self.assertIsNotNone(request)
        self.assertTrue(request.reading)
        QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=outside)
        before = self.state(editor)
        count = editor.ranges.loaded_count
        loader._tick()
        editor.navigation._finish(request, perf_counter())
        self.assertIsNone(editor.navigation.pending)
        self.assertEqual(editor.ranges.loaded_count, count)
        self.assertEqual(self.state(editor), before)


    def test_full_selection_copy_and_gap_filling_do_not_layout_offscreen_giant(self):
        lines = ["ERROR: short β😀 "] * 1100
        lines[400] = "ERROR: " + "x" * 250000
        view = self.window(lines=lines, wrapped=True)
        editor = view.editor
        self.jump(editor, editor.presentation.display_row(900))
        self.quiet(view)
        editor.selectAll()
        expected = editor.selected_text()
        before = self.state(editor)
        giant = editor.presentation.display_row(400)
        with patch.object(editor, "_layout_visible", wraps=editor._layout_visible) as visible:
            for a, b in ((giant, giant + 1), (giant + 1, giant + 4), (30, 90)):
                editor.insert_range(a, b)
                self.assertEqual(editor._block(giant).layout().lineCount(), 0)
                self.assertEqual(self.state(editor), before)
            self.assertEqual(visible.call_count, 0)
        self.assertEqual(editor.selected_text(), expected)
        self.assertEqual(editor.textCursor().selectionEnd(), editor.document().characterCount() - 1)


    def test_removing_one_row_gap_relocates_native_top_even_when_visual_value_is_unchanged(self):
        view = self.window(lines=["ERROR: " + "payload " * 130] * 700, wrapped=True)
        editor = view.editor
        row = editor.presentation.display_row(500)
        editor.insert_range(0, row - 1)
        editor.insert_range(row, row + 4)
        self.jump(editor, row, 180)
        self.quiet(view)
        editor.select(TextPoint(row + 1, 28), TextPoint(row, 19))
        state = self.state(editor)
        value = editor.verticalScrollBar().value()
        editor.insert_range(row - 1, row)
        self.assertEqual(editor.verticalScrollBar().value(), value)
        self.assertEqual(editor.firstVisibleBlock(), editor._block(row))
        self.app.processEvents()
        self.assertEqual(self.state(editor), state)


    def test_superseded_preparation_bounds_layout_cache_without_a_destination_paint(self):
        view = self.window(lines=["ERROR: " + "payload " * 130] * 1600, wrapped=True)
        editor, loader = view.editor, view.loader
        self.jump(editor, editor.presentation.display_row(1200), 180)
        self.quiet(view)
        before = self.state(editor)
        loader.max_rows = 1
        for row in range(200, 900, 2):
            editor.navigate_to(TextPoint(row))
            loader._tick()
            self.quiet(view)
            self.assertEqual(self.state(editor), before)
            self.assertLessEqual(len(editor._cached_rows), 256)
            self.assertLessEqual(editor._cached_units, editor.cache_units)
        self.assertLessEqual(len(loader._prepared), 512)


    def test_oversized_destination_preparation_survives_until_navigation(self):
        lines = ["ERROR: short"] * 800
        lines[720] = "ERROR: " + "x" * 250000
        view = self.window(lines=lines, wrapped=True)
        editor = view.editor
        editor.cache_units = 65536
        row = editor.presentation.display_row(720)
        prepare = editor._prepare_block
        cold = []
        def counted(number):
            block = editor._block(number)
            if number == row and block.isValid() and not block.layout().lineCount():
                cold.append(number)
            return prepare(number)
        with patch.object(editor, "_prepare_block", side_effect=counted):
            self.jump(editor, row)
        self.assertEqual(cold, [row])
        self.assertTrue(editor.viewport_evidence()["useful"])


    def test_real_thumb_drag_holds_latest_destination_through_insertion_and_release(self):
        view = self.window()
        bar, editor = view.global_scroll, view.editor
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        slider = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                          QStyle.SubControl.SC_ScrollBarSlider, bar)
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=slider.center())
        for fraction in (.75, .55, .9):
            QTest.mouseMove(bar, QPoint(bar.width() // 2, round(bar.height() * fraction)))
            request = editor.navigation.pending
            self.assertIsNotNone(request)
            value = bar.value()
            view.loader._tick()
            self.assertEqual(bar.value(), value)
            self.assertTrue(bar.isSliderDown())
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton,
                           pos=QPoint(bar.width() // 2, round(bar.height() * .9)))
        self.assertEqual(bar.value(), editor.navigation.pending.point.row)
        self.wait_jump(editor)
        self.assertEqual(bar.value(), editor.top_point().row)
        self.assertFalse(editor.ranges.contains(editor.ranges.total // 2))


    def test_wheel_crosses_adjacent_gap_in_both_directions_without_skipping_to_next_island(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                view = self.window()
                editor = view.editor
                row = editor.ranges.total // 2
                editor.insert_range(row, row + 4)
                editor.insert_range(row + 100, row + 120)
                with editor.changing():
                    editor.set_top(TextPoint(row))
                editor.navigate_to(TextPoint(editor.ranges.total * 9 // 10))
                old = editor.navigation.pending
                self.wheel(editor, angle=-120 * direction)
                self.finish_wheel(editor)
                self.assertIsNot(editor.navigation.pending, old)
                self.wait_jump(editor)
                self.assertEqual(editor.top_point().row, row + direction * 3)
                self.assertTrue(editor.viewport_evidence()["useful"])
                self.assertFalse(editor.ranges.contains(row + 60))
                self.assertFalse(editor.ranges.contains(old.point.row))


    def test_page_and_vertical_keys_cross_wrapped_boundaries_and_preserve_shift_anchor(self):
        for key, delta in ((Qt.Key.Key_Down, 1), (Qt.Key.Key_Up, -1),
                           (Qt.Key.Key_PageDown, 1), (Qt.Key.Key_PageUp, -1)):
            with self.subTest(key=key):
                view = self.window(lines=[f"ERROR: {i} " + "wrapped payload " * 15 for i in range(700)], wrapped=True)
                editor = view.editor
                row = editor.presentation.display_row(350)
                editor.insert_range(row, row + 1)
                block = editor._prepare_block(row)
                origin = TextPoint(row, block.layout().lineAt(block.layout().lineCount() - 1).textStart() if delta > 0 else 0)
                with editor.changing():
                    editor.anchor = editor.caret = origin
                    editor.set_top(origin)
                QTest.keyClick(editor, key, Qt.KeyboardModifier.ShiftModifier)
                self.assertIsNotNone(editor.navigation.pending)
                self.wait_jump(editor)
                self.assertEqual(editor.anchor, origin)
                self.assertGreater((editor.caret.row - row) * delta, 0)
                self.assertLess(abs(editor.caret.row - row), editor._screen_rows() + 1)
                self.assertTrue(editor.ranges.contains(editor.caret.row))
                self.assertIsInstance(editor.location_at(editor.textCursor().position()), TextPoint)


    def test_left_right_at_gap_never_land_on_marker_or_jump_over_missing_text(self):
        view = self.window()
        editor = view.editor
        row = editor.ranges.total // 2
        editor.insert_range(row, row + 2)
        editor.insert_range(row + 100, row + 120)
        for forward in (True, False):
            origin = TextPoint(row + 1, editor._units(row + 1)) if forward else TextPoint(row)
            with editor.changing():
                editor.anchor = editor.caret = origin
                editor.set_top(TextPoint(row))
            QTest.keyClick(editor, Qt.Key.Key_Right if forward else Qt.Key.Key_Left)
            self.wait_jump(editor)
            expected = row + 2 if forward else row - 1
            self.assertEqual(editor.caret.row, expected)
            self.assertIsInstance(editor.location_at(editor.textCursor().position()), TextPoint)
        self.assertFalse(editor.ranges.contains(row + 60))


    def test_cached_jump_supersedes_ready_callback_and_resumes_background_without_changing_selection(self):
        view = self.window(lines=[f"ERROR: row {i} alpha" for i in range(2400)])
        editor, loader, nav = view.editor, view.loader, view.editor.navigation
        self.jump(editor, 1000)
        editor.select(TextPoint(1002, 15), TextPoint(1000, 4))
        selection = editor.anchor, editor.caret, editor.selected_text()
        editor.navigate_to(TextPoint(2100), move_caret=True)
        for _ in range(100):
            loader._tick()
            if nav._ready:
                break
        self.assertIsNotNone(nav._ready)
        obsolete = nav.pending
        nav.timer.stop()
        loader.timer.stop()
        view.global_scroll.setValue(1000)
        self.assertIsNone(nav.pending)
        self.assertEqual(editor.top_point().row, 1000)
        nav._finish(obsolete, perf_counter())
        self.assertEqual((editor.anchor, editor.caret, editor.selected_text()), selection)
        self.assertEqual(editor.top_point().row, 1000)
        loader.set_paused(True)
        self.background(view)
        coverage = editor.ranges.loaded_count
        editor.navigate_to(TextPoint(1000))
        self.assertIsNone(nav.pending)
        self.assertFalse(loader.paused)
        self.wait(lambda: editor.ranges.loaded_count > coverage)
        self.assertEqual(editor.top_point().row, 1000)
        self.assertEqual((editor.anchor, editor.caret, editor.selected_text()), selection)


    def test_cached_screen_probe_is_readonly_and_rejects_evicted_layout_and_changed_geometry(self):
        view = self.window(lines=["ERROR: " + "long words " * 70 for _ in range(900)], wrapped=True)
        editor, loader = view.editor, view.loader
        self.jump(editor, 700)
        loader.timer.stop()
        point = editor.top_point()
        # Native painting can prepare a row without a Python preparation record.
        editor._prepared_layouts.pop(point.row)
        with patch.object(editor, "_prepare_block", side_effect=AssertionError("Readiness must not lay out")), \
                patch.object(editor, "blockBoundingRect", side_effect=AssertionError("Readiness must not lay out")):
            self.assertEqual(loader._cached_screen(point)[0], point)
            self.assertIsNone(loader._cached_screen(TextPoint(500)))
            with patch.object(editor, "tabStopDistance", return_value=editor.tabStopDistance() + 1):
                self.assertIsNone(loader._cached_screen(point))
        # A retained block reference and cache key do not imply retained glyphs.
        editor._block(point.row).layout().beginLayout()
        editor._block(point.row).layout().endLayout()
        self.assertIsNone(loader._cached_screen(point))
        editor.navigate_to(point)
        self.assertIsNotNone(editor.navigation.pending)
        self.wait_jump(editor)
        self.assertEqual(editor.top_point(), point)
        # Resize can immediately prepare the visible screen. The old
        # offscreen geometry must still be rejected without laying it out.
        self.jump(editor, 600)
        view.resize(view.width() + 100, view.height() + 60)
        self.assertIsNone(loader._cached_screen(point))

    def test_tall_cached_scrollbar_navigation_is_immediate_and_preserves_copy(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                view = self.window(fraction=1, wrapped=wrapped,
                                   lines=[f"ERROR: row {i} alpha" for i in range(1600)])
                editor, loader = view.editor, view.loader
                editor.viewport().setFixedHeight(1200)
                view.resize(780, 1400)
                self.app.processEvents()
                self.wait(lambda: editor.end_top() is not None)
                self.jump(editor, 500)
                self.jump(editor, 600)
                self.assertGreater(len(editor._visible_rows), loader.max_rows)
                self.quiet(view)
                editor.select(TextPoint(502, 15), TextPoint(500, 4))
                selection = editor.anchor, editor.caret, editor.selected_text()
                before = editor.inserted_rows, editor.layout_visits, loader.tick_count
                statuses = []
                view.loading_status_changed.connect(statuses.append)
                for row in (500, 600, 500, 600):
                    view.global_scroll.setValue(row)
                    self.assertIsNone(editor.navigation.pending)
                    self.assertEqual(editor.top_point().row, row)
                    self.app.processEvents()
                self.assertEqual((editor.inserted_rows, editor.layout_visits, loader.tick_count), before)
                self.assertEqual((editor.anchor, editor.caret, editor.selected_text()), selection)
                editor.copy()
                self.assertEqual(self.app.clipboard().text(), selection[2])
                self.assertFalse(any("Preparing view" in value for value in statuses))
                self.assertEqual(loader.max_rows, 64)
                self.assertLessEqual(len(editor._cached_rows), 256)
                self.assertLessEqual(editor._cached_units, editor.cache_units)

    def test_background_loading_percentage_increases_until_complete(self):
        view = self.window(fraction=0, lines=[f"ERROR: row {i}" for i in range(1600)])
        editor = view.editor
        total = editor.ranges.total
        statuses = []
        view.loading_status_changed.connect(statuses.append)
        view._progress()
        self.assertEqual(view.loading_status, "Background loading: \u2007\u20071%")
        for end, percentage in ((total // 2, 50), (total - 1, 99)):
            editor.insert_range(0, end)
            view._progress()
            self.assertEqual(view.loading_status, f"Background loading: {percentage:\u2007>3}%")
        percentages = [int(status.removeprefix("Background loading: ").removesuffix("%"))
                       for status in statuses]
        self.assertEqual(percentages, sorted(percentages))
        editor.insert_range(0, total)
        view._progress()
        self.assertEqual(view.loading_status, "Results loaded")

    def test_preparing_view_status_waits_for_slow_layout_and_clears_on_completion(self):
        view = self.window(fraction=1, lines=[f"ERROR: row {i}" for i in range(1600)])
        editor = view.editor
        statuses = []
        view.loading_status_changed.connect(statuses.append)
        editor.navigate_to(TextPoint(800))
        view.loader.timer.stop()
        self.assertIsNotNone(editor.navigation.pending)
        self.assertTrue(view._navigation_status_timer.isActive())
        self.assertEqual(view.loading_status, "Results loaded")
        QTest.qWait(35)
        self.assertFalse(any("Preparing view" in value for value in statuses))
        self.wait(lambda: view.loading_status.startswith("Preparing view: "))
        view.loader.start()
        self.wait_jump(editor)
        self.assertEqual(view.loading_status, "Results loaded")
        self.assertFalse(view._navigation_status_timer.isActive())
        statuses.clear()
        self.jump(editor, 1200)
        QTest.qWait(140)
        self.assertFalse(any("Preparing view" in value for value in statuses))

    def test_navigation_status_timer_cannot_outlive_cancellation_replacement_or_close(self):
        for action in ("cancel", "replace", "close"):
            with self.subTest(action=action):
                view = self.window(fraction=1, lines=[f"ERROR: row {i}" for i in range(1600)])
                view.editor.navigate_to(TextPoint(800))
                view.loader.timer.stop()
                self.assertTrue(view._navigation_status_timer.isActive())
                if action == "cancel":
                    view.cancel_rendering()
                elif action == "replace":
                    view.reset_for_loaded_file("replacement.log")
                else:
                    view.close()
                self.assertFalse(view._navigation_status_timer.isActive())
                statuses = []
                view.loading_status_changed.connect(statuses.append)
                QTest.qWait(140)
                self.assertEqual(statuses, [])
        view = self.window(lines=[f"ERROR: row {i}" for i in range(1600)])
        view.editor.navigate_to(TextPoint(800))
        self.assertTrue(view.loading_status.startswith("Loading requested area: "))
        self.assertFalse(view._navigation_status_timer.isActive())
