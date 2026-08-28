import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.terminal import print_report, render_report, write_report


class TerminalRendererTests(unittest.TestCase):

    def test_plain_report_contains_summary_sections_and_context(self):
        config = LogreaderConfig(
            context=1,
            enabled_patterns=("warning",),
            custom_patterns=("timeout",),
        )
        analysis = analyze_lines(
            ["before", "ERROR: timeout", "after", "WARNING: retry"],
            config.search_patterns(),
        )

        report = render_report("sample.log", analysis, config)

        self.assertNotIn("\033[", report)
        self.assertIn('Number of "ERROR:" in this file', report)
        self.assertIn('Number of "WARNING:" in this file', report)
        self.assertIn("Custom pattern: timeout", report)
        self.assertIn("1      -> before", report)
        self.assertIn("2      -> ERROR: timeout", report)
        self.assertIn('"ERROR:" contained:', report)

    def test_colored_terminal_report_uses_ansi_sequences(self):
        config = LogreaderConfig(enabled_patterns=())
        analysis = analyze_lines(["ERROR: boom"], config.search_patterns())
        stream = io.StringIO()

        print_report("sample.log", analysis, config, stream=stream, color=True)

        self.assertIn("\033[", stream.getvalue())
        self.assertIn("ERROR:", stream.getvalue())

    @patch("logreader.terminal._stream_supports_color", return_value=True)
    def test_automatic_color_uses_ansi_when_supported(self, supports_color):
        config = LogreaderConfig(enabled_patterns=())
        analysis = analyze_lines(["ERROR: boom"], config.search_patterns())
        stream = io.StringIO()

        print_report("sample.log", analysis, config, stream=stream)

        supports_color.assert_called_once_with(stream)
        self.assertIn("\033[", stream.getvalue())

    @patch("logreader.terminal._stream_supports_color", return_value=False)
    def test_automatic_color_falls_back_to_plain_text(self, supports_color):
        config = LogreaderConfig(enabled_patterns=())
        analysis = analyze_lines(["ERROR: boom"], config.search_patterns())
        stream = io.StringIO()

        print_report("sample.log", analysis, config, stream=stream)

        supports_color.assert_called_once_with(stream)
        self.assertNotIn("\033[", stream.getvalue())
        self.assertIn("ERROR: boom", stream.getvalue())

    def test_limit_stops_before_the_next_match_but_keeps_context(self):
        config = LogreaderConfig(context=1, limit=1, enabled_patterns=())
        analysis = analyze_lines(
            ["ERROR: first", "context", "ERROR: second"],
            config.search_patterns(),
        )

        report = render_report("sample.log", analysis, config)

        self.assertIn("ERROR: first", report)
        self.assertIn("2      -> context", report)
        self.assertNotIn("ERROR: second", report)
        self.assertIn("Limited, showing 1 out of 2 elements.", report)

    def test_text_report_is_written_without_color(self):
        config = LogreaderConfig(enabled_patterns=())
        analysis = analyze_lines(["FATAL but disabled", "ERROR: boom"], config.search_patterns())

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "report.txt"
            write_report(output_path, "sample.log", analysis, config)
            report = output_path.read_text(encoding="utf-8")

        self.assertIn("ERROR: boom", report)
        self.assertNotIn("\033[", report)


if __name__ == "__main__":
    unittest.main()
