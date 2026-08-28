import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QLineEdit,
        QPlainTextEdit,
        QSpinBox,
    )

    from logreader.qt_app import COLORS, LogreaderWindow
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
        self.assertEqual(config.generic_context, 0)
        self.assertIsNone(config.limit)
        self.assertEqual(config.enabled_patterns, ("failed", "fatal"))
        self.assertEqual(config.custom_patterns, ())

    def test_controls_update_context_patterns_and_limit(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(5)
        self.window.findChild(QSpinBox, "genericContextSpin").setValue(2)
        self.window.findChild(QSpinBox, "limitSpin").setValue(10)
        self.window.findChild(QCheckBox, "pattern_warning").setChecked(True)
        self.window.findChild(QLineEdit, "customPattern").setText(" timeout ")

        config = self.window.build_config()

        self.assertEqual(config.context, 5)
        self.assertEqual(config.generic_context, 2)
        self.assertEqual(config.limit, 10)
        self.assertEqual(config.enabled_patterns, ("failed", "fatal", "warning"))
        self.assertEqual(config.custom_patterns, ("timeout",))

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


if __name__ == "__main__":
    unittest.main()
