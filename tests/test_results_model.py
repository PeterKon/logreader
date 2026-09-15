import unittest
from dataclasses import replace

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.document_session import DocumentSession
from logreader.file_loader import LoadedLog
from logreader.results_model import ResultsModel, SourceLocation


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
                          custom_pattern_match_case=(False,), custom_pattern_exclude=(False,))
        model = self.model(lines, changed)
        row = model.resolve(location)
        self.assertEqual(model.location(row).category, location.category)
        self.assertEqual(model.line(row).number, 10003)
        combined = self.model(lines, replace(changed, combined_view=True))
        self.assertEqual(combined.line(combined.resolve(location)).number, 10003)

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
