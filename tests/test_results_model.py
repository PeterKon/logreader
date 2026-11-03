import unittest
from dataclasses import replace
from unittest.mock import patch

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.document_session import DocumentSession
from logreader.file_loader import LoadedLog
from logreader.search_storage import SEARCH_CHUNK_CHARACTERS, utf16_length
from logreader.ui.results.results_model import ResultsModel, SourceLocation


class ResultsModelTests(unittest.TestCase):
    def model(self, lines, config, snapshot="snapshot", offset=10000):
        analysis = analyze_lines(lines, config.search_patterns(),
                                 combined=config.combined_view, line_offset=offset)
        model = ResultsModel(analysis, snapshot)
        for _ in model.prepare():
            pass
        return model

    def test_rows_reference_analysis_and_resolve_duplicate_categories_and_context(self):
        config = LogreaderConfig(context=1, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("needle",))
        model = self.model(("before", "ERROR: needle", "after"), config)
        self.assertEqual(model.row_count, 6)
        self.assertEqual(model.rows_for_source(SourceLocation("snapshot", 10002)), (1, 4))
        self.assertEqual(model.rows_for_source(SourceLocation("snapshot", 10001)), (0, 3))
        for row in range(model.row_count):
            location = model.location(row)
            self.assertEqual(model.resolve(location), row)
            self.assertEqual(location.source.line, model.line(row).number)
        original = model.analysis.categories["error_colon"].excerpts[0].lines[1]
        self.assertIs(model.line(1), original)
        self.assertIs(model.line(1).text, original.text)
        self.assertEqual(model.max_source_line, 10003)

    def test_location_survives_custom_pattern_renumbering_context_and_combined_mode(self):
        config = LogreaderConfig(context=0, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("other", "needle"))
        lines = ("other", "before", "ERROR: needle", "after")
        old = self.model(lines, config)
        location = old.location(old.rows_for_source(SourceLocation("snapshot", 10003))[-1])
        changed = replace(config, context=1, custom_patterns=("needle",),
                          custom_pattern_match_case=(False,), custom_pattern_exclude=(False,),
                          custom_pattern_exclusive=(False,))
        model = self.model(lines, changed)
        row = model.resolve(location)
        self.assertEqual(model.location(row).category, location.category)
        self.assertEqual(model.line(row).number, 10003)
        combined = self.model(lines, replace(changed, combined_view=True))
        self.assertEqual(combined.line(combined.resolve(location)).number, 10003)

    def test_pattern_matches_project_every_accepted_copy_in_display_order(self):
        lines = ("lead tail", "😀 r😀 r😀", "lead tail SKIP r😀", "😀r😀", "lead tail")
        config = LogreaderConfig(context=1, enabled_patterns=(),
                                 custom_patterns=("lead", "tail", "SKIP"),
                                 custom_pattern_exclude=(False, False, True),
                                 regex_patterns=("r😀",))
        offset = 1 << 64
        for combined, row_pairs in ((True, [(1, 3)]), (False, [(1, 2), (5, 6), (9, 11)])):
            with self.subTest(combined=combined):
                model = self.model(lines, replace(config, combined_view=combined), offset=offset)
                self.assertTrue(model.rows_for_source(SourceLocation("snapshot", offset + 3)))
                matches = list(model.iter_pattern_matches("regex_1"))
                expected = []
                for first, second in row_pairs:
                    expected.extend([(first, 3, 6), (first, 7, 10), (second, 2, 5)])
                self.assertEqual(matches, expected)

    def test_long_unicode_projection_yields_and_converts_the_prefix_only_once(self):
        prefix = "😀" + "a" * (SEARCH_CHUNK_CHARACTERS * 3)
        text = prefix + "r😀" * 200
        config = LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("r",),
                                 regex_patterns=("r😀",), combined_view=False)
        model = self.model((text,), config)
        lengths = []

        def measure(part):
            lengths.append(len(part))
            return utf16_length(part)

        with patch("logreader.ui.results.results_model.utf16_length", side_effect=measure):
            work = model.iter_pattern_match_steps("regex_1")
            while not lengths:
                self.assertIsNone(next(work))
            self.assertLess(sum(lengths), len(prefix))
            work.close()
            self.assertEqual(list(work), [])

            lengths.clear()
            matches = list(model.iter_pattern_matches("regex_1"))
        start = utf16_length(prefix)
        self.assertEqual(matches, [(row, start + 3 * i, start + 3 * i + 3)
                                   for row in (0, 1) for i in range(200)])
        self.assertLessEqual(max(lengths), SEARCH_CHUNK_CHARACTERS)
        self.assertLessEqual(sum(lengths), len(text))

    def test_projection_can_pause_in_context_before_the_first_match(self):
        context = 4096
        model = self.model(("context",) * context + ("needle",),
                           LogreaderConfig(context=context, enabled_patterns=(),
                                           custom_patterns=("needle",), combined_view=False))
        work = model.iter_pattern_match_steps("custom_1")
        self.assertIsNone(next(work))
        self.assertEqual([hit for hit in work if hit is not None], [(context, 0, 6)])

    def test_unavailable_lines_and_replaced_snapshots_never_resolve_to_nearby_text(self):
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        model = self.model(("ERROR: first", "omitted", "ERROR: last"), config)
        self.assertEqual(model.rows_for_source(SourceLocation("snapshot", 10002)), ())
        self.assertIsNone(model.resolve(SourceLocation("different", 10001)))
        self.assertIsNone(model.resolve(SourceLocation("snapshot", 10000)))
        self.assertIsNone(model.resolve(SourceLocation("snapshot", 10004)))
        empty = self.model(("ordinary",), config)
        self.assertEqual(empty.row_count, 0)
        self.assertIsNone(empty.resolve(SourceLocation("snapshot", 10001)))
        with self.assertRaises(IndexError):
            empty.line(0)

    def test_indexing_yields_for_sparse_results_and_stores_no_per_line_index(self):
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        analysis = analyze_lines(("ERROR: line", "gap") * 5000,
                                 config.search_patterns(), combined=True)
        model = ResultsModel(analysis, "snapshot")
        work = model.prepare()
        next(work)
        self.assertFalse(model.ready)
        self.assertEqual(model.row_count, 1)
        for _ in work:
            pass
        self.assertTrue(model.ready)
        self.assertEqual(model.row_count, 5000)
        self.assertEqual(model.sections[0].row_starts.itemsize, 8)
        self.assertEqual(model.line(4999).number, 9999)

    def test_snapshot_identity_changes_only_when_loaded_contents_are_replaced(self):
        session = DocumentSession()
        loaded = LoadedLog(("ERROR: sample",), "UTF-8")
        session.stage_loaded_log("one.log", loaded)
        snapshot = session.snapshot_id
        config = LogreaderConfig(enabled_patterns=("error_colon",))
        request = session.begin_analysis(config, 1)
        session.cancel_request()
        session.begin_analysis(config, 1)
        self.assertGreater(session.request_generation, request.request_id)
        self.assertEqual(session.snapshot_id, snapshot)
        session.stage_loaded_log("one.log", loaded)
        self.assertNotEqual(session.snapshot_id, snapshot)
        session.clear()
        self.assertIsNone(session.snapshot_id)
