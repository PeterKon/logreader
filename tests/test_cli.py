import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from logreader.cli import main


class LogreaderCliTests(unittest.TestCase):

    def test_cli_analyzes_custom_and_enabled_patterns_without_output_file(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server.log"
            log_path.write_text(
                "start\nWARNING: timeout while connecting\nend\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        str(log_path),
                        "--context",
                        "5",
                        "--pattern",
                        "timeout",
                        "--enable",
                        "warning",
                        "exception",
                        "--no-output-file",
                        "--no-color",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn('Number of "WARNING:" in this file', stdout.getvalue())
        self.assertIn("Custom pattern: timeout", stdout.getvalue())
        self.assertNotIn("\033[", stdout.getvalue())
        custom_section = stdout.getvalue().split("Pattern searched: timeout", 1)[1]
        self.assertIn("1      -> start", custom_section)
        self.assertIn("3      -> end", custom_section)

    def test_cli_writes_the_requested_plain_text_report(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server.log"
            output_path = Path(directory) / "analysis.txt"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        str(log_path),
                        "--output-file",
                        str(output_path),
                        "--no-color",
                    ]
                )

            report = output_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("ERROR: boom", report)
        self.assertNotIn("\033[", report)

    def test_cli_reports_a_missing_input_file(self):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            exit_code = main(["missing.log", "--no-output-file"])

        self.assertEqual(exit_code, 2)
        self.assertIn("logreader:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
