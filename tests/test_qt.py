import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
    )

    from logreader.config import PATTERN_KEYS
    from logreader.qt_app import COLORS, RULE, LogreaderWindow
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class LogreaderQtTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = LogreaderWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_default_controls_build_the_shared_configuration(self):
        config = self.window.build_config()

        self.assertEqual(config.context, 3)
        self.assertIsNone(config.limit)
        self.assertEqual(
            config.enabled_patterns,
            ("error_colon", "error", "failed", "fatal"),
        )
        self.assertEqual(config.custom_patterns, ())
        self.assertFalse(config.separate_entries)
        self.assertEqual(
            self.window.findChild(QLabel, "limitLabel").text(),
            "Number of entries - limit",
        )
        self.assertEqual(
            self.window.findChild(QLabel, "contextLabel").text(),
            "Context around entries",
        )
        self.assertEqual(
            self.window.findChild(QCheckBox, "separateEntriesCheck").text(),
            "Separation of entries",
        )

    def test_controls_update_context_patterns_and_limit(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(5)
        self.window.findChild(QSpinBox, "limitSpin").setValue(10)
        self.window.findChild(QCheckBox, "pattern_warning").setChecked(True)
        self.window.findChild(QCheckBox, "separateEntriesCheck").setChecked(True)
        self.window.findChild(QLineEdit, "customPattern").setText(" timeout ")

        config = self.window.build_config()

        self.assertEqual(config.context, 5)
        self.assertEqual(config.limit, 10)
        self.assertEqual(
            config.enabled_patterns,
            ("error_colon", "error", "failed", "fatal", "warning"),
        )
        self.assertEqual(config.custom_patterns, ("timeout",))
        self.assertTrue(config.separate_entries)

    def test_error_patterns_and_plain_variants_are_available_as_toggles(self):
        expected_labels = {
            "pattern_error_colon": "ERROR:",
            "pattern_error": "ERROR",
            "pattern_warning": "WARNING:",
            "pattern_warning_generic": "WARNING",
            "pattern_exception": "EXCEPTION:",
            "pattern_exception_generic": "EXCEPTION",
            "pattern_aborted": "ABORTED",
            "pattern_terminated": "TERMINATED",
            "pattern_timeout": "TIMEOUT",
            "pattern_uninitialized": "UNINITIALIZED",
            "pattern_not_found": "NOT FOUND",
        }

        for object_name, label in expected_labels.items():
            checkbox = self.window.findChild(QCheckBox, object_name)
            self.assertIsNotNone(checkbox)
            self.assertEqual(checkbox.text(), label)

        self.window.findChild(QCheckBox, "pattern_error_colon").setChecked(False)
        self.window.findChild(QCheckBox, "pattern_error").setChecked(False)
        config = self.window.build_config()
        self.assertNotIn("error_colon", config.enabled_patterns)
        self.assertNotIn("error", config.enabled_patterns)

    def test_toggle_all_enables_every_pattern_then_disables_every_pattern(self):
        button = self.window.findChild(QPushButton, "toggleAllButton")

        button.click()
        self.assertEqual(self.window.build_config().enabled_patterns, PATTERN_KEYS)

        button.click()
        self.assertEqual(self.window.build_config().enabled_patterns, ())

    def test_loading_a_file_renders_colored_plain_text_and_updates_status(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server.log"
            log_path.write_text(
                "before\nERROR: boom\nafter\n",
                encoding="utf-8",
            )

            loaded = self.window.load_file(log_path)
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            output = results.toPlainText()
            html = results.document().toHtml()

        self.assertTrue(loaded)
        self.assertIn("ERROR: boom", output)
        self.assertNotIn("\033[", output)
        self.assertIn(COLORS["red"].name(), html)
        self.assertIn(COLORS["green"].name(), html)
        self.assertIn(COLORS["blue"].name(), html)
        self.assertIn("3 lines", self.window.statusBar().currentMessage())

    def test_zero_match_patterns_stay_in_summary_without_blank_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "summary.log"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")

            self.window.load_file(log_path)
            output = self.window.findChild(
                QPlainTextEdit,
                "resultsView",
            ).toPlainText()

        summary = output.split(f"\n{RULE}\n", 1)[0]
        self.assertRegex(summary, r"FAILED\s+0 matches")
        self.assertRegex(summary, r"FATAL\s+0 matches")
        self.assertNotIn("FAILED — 0 matches", output)
        self.assertNotIn("FATAL — 0 matches", output)
        self.assertNotIn("No matches.", output)

    def test_results_view_respects_the_per_pattern_limit(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(0)
        self.window.findChild(QSpinBox, "limitSpin").setValue(1)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "limited.log"
            log_path.write_text(
                "ERROR: first\nneutral\nERROR: second\n",
                encoding="utf-8",
            )

            self.window.load_file(log_path)
            output = self.window.findChild(
                QPlainTextEdit,
                "resultsView",
            ).toPlainText()

        self.assertIn("ERROR: first", output)
        self.assertNotIn("ERROR: second", output)
        self.assertIn("Showing 1 of 2 matches.", output)

    def test_entry_separation_is_optional_and_uses_the_section_rule(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(0)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "separated.log"
            log_path.write_text(
                "ERROR: first\nneutral\nneutral\nneutral\nneutral\nERROR: second\n",
                encoding="utf-8",
            )

            self.window.load_file(log_path)
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            without_separator = results.toPlainText()

            self.window.findChild(
                QCheckBox,
                "separateEntriesCheck",
            ).setChecked(True)
            self.window.analyze_current()
            with_separator = results.toPlainText()

        adjacent_results = (
            "1      -> ERROR: first\n"
            "6      -> ERROR: second"
        )
        separated_results = (
            "1      -> ERROR: first\n"
            f"{RULE}\n"
            "6      -> ERROR: second"
        )
        self.assertIn(adjacent_results, without_separator)
        self.assertNotIn(separated_results, without_separator)
        self.assertIn(separated_results, with_separator)


if __name__ == "__main__":
    unittest.main()
