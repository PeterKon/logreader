import unittest
from pathlib import Path

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.document_session import AnalysisPhase, DocumentSession
from logreader.file_loader import LoadedLog


class DocumentSessionTests(unittest.TestCase):

    def setUp(self):
        self.session = DocumentSession()
        self.loaded = LoadedLog(
            lines=("before", "ERROR: boom", "after"),
            encoding="UTF-8",
        )
        self.config = LogreaderConfig()

    def test_stages_a_loaded_document_and_starts_idle(self):
        self.session.stage_loaded_log("server.log", self.loaded)

        self.assertTrue(self.session.has_document)
        self.assertFalse(self.session.is_busy)
        self.assertEqual(self.session.path, Path("server.log"))
        self.assertEqual(self.session.lines, self.loaded.lines)
        self.assertEqual(self.session.encoding, "UTF-8")
        self.assertEqual(self.session.phase, AnalysisPhase.IDLE)
        self.assertIsNone(self.session.analysis)
        self.assertIsNone(self.session.active_request)

    def test_analysis_lifecycle_retains_result_config_and_timings(self):
        self.session.stage_loaded_log("server.log", self.loaded)
        request = self.session.begin_analysis(
            self.config,
            len(self.config.search_patterns()),
        )

        self.assertTrue(self.session.is_busy)
        self.assertEqual(self.session.phase, AnalysisPhase.ANALYZING)
        self.assertEqual(request.request_id, 1)
        self.assertEqual(request.source_path, Path("server.log"))
        self.assertIs(request.config, self.config)
        self.assertEqual(request.pattern_count, 4)

        analysis = analyze_lines(
            self.loaded.lines,
            self.config.search_patterns(),
        )
        self.assertTrue(
            self.session.begin_rendering(request.request_id, analysis, 1.25)
        )
        self.assertEqual(self.session.phase, AnalysisPhase.RENDERING)
        self.assertIs(self.session.analysis, analysis)
        self.assertIs(self.session.analysis_config, self.config)
        self.assertEqual(self.session.analysis_seconds, 1.25)

        self.assertTrue(self.session.complete_rendering(request.request_id, 0.5))
        self.assertFalse(self.session.is_busy)
        self.assertIsNone(self.session.active_request)
        self.assertIs(self.session.analysis, analysis)
        self.assertIs(self.session.analysis_config, self.config)
        self.assertEqual(self.session.analysis_seconds, 1.25)
        self.assertEqual(self.session.rendering_seconds, 0.5)

    def test_replacing_a_busy_document_invalidates_stale_results(self):
        self.session.stage_loaded_log("first.log", self.loaded)
        request = self.session.begin_analysis(self.config, 4)

        replacement = LoadedLog(lines=("new document",), encoding="UTF-16 LE")
        self.session.stage_loaded_log("second.log", replacement)

        self.assertEqual(self.session.request_generation, 2)
        self.assertEqual(self.session.path, Path("second.log"))
        self.assertEqual(self.session.lines, replacement.lines)
        self.assertEqual(self.session.encoding, "UTF-16 LE")
        self.assertFalse(self.session.is_busy)
        self.assertFalse(
            self.session.begin_rendering(
                request.request_id,
                analyze_lines(self.loaded.lines, self.config.search_patterns()),
                1.0,
            )
        )

    def test_rejects_invalid_lifecycle_transitions(self):
        with self.assertRaisesRegex(RuntimeError, "before a document"):
            self.session.begin_analysis(self.config, 4)

        self.session.stage_loaded_log("server.log", self.loaded)
        request = self.session.begin_analysis(self.config, 4)
        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.session.begin_analysis(self.config, 4)

        self.assertFalse(self.session.complete_rendering(request.request_id, 0.5))
        self.assertFalse(self.session.fail_request(request.request_id + 1))
        self.assertTrue(self.session.fail_request(request.request_id))
        self.assertEqual(self.session.phase, AnalysisPhase.IDLE)


if __name__ == "__main__":
    unittest.main()
