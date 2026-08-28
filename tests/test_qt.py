import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFrame,
        QGridLayout,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QWidget,
    )

    from logreader.config import (
        HTTP_STATUS_PATTERN_KEYS,
        PAIRED_PATTERN_KEYS,
        PATTERN_KEYS,
        TEXT_PATTERN_KEYS,
    )
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
            "Total entries limit",
        )
        self.assertEqual(
            self.window.findChild(QLabel, "contextLabel").text(),
            "Context around entries",
        )
        self.assertEqual(
            self.window.findChild(QCheckBox, "separateEntriesCheck").text(),
            "Separation of entries",
        )
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Ready: Open a log file to begin",
        )

    def test_results_scrollbars_use_visible_theme_colors(self):
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        style_sheet = results.styleSheet()

        self.assertIn("QScrollBar::handle:vertical", style_sheet)
        self.assertIn("QScrollBar::handle:horizontal", style_sheet)
        self.assertIn("QScrollBar:horizontal", style_sheet)
        self.assertIn(COLORS["scrollbar_track"].name(), style_sheet)
        self.assertIn(COLORS["scrollbar_handle"].name(), style_sheet)
        self.assertIn(COLORS["scrollbar_handle_hover"].name(), style_sheet)

    def test_results_view_can_be_maximized_and_restored(self):
        file_controls = self.window.findChild(QWidget, "fileControlsRow")
        filter_group = self.window.findChild(QGroupBox, "filterGroup")
        results_header = self.window.findChild(QWidget, "resultsHeader")
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        button = self.window.findChild(QPushButton, "maximizeResultsButton")

        self.assertFalse(file_controls.isHidden())
        self.assertFalse(filter_group.isHidden())
        self.assertFalse(results_header.isHidden())
        self.assertFalse(results.isHidden())
        self.assertEqual(button.text(), "▲")
        self.assertEqual(button.accessibleName(), "Maximize results")
        self.assertEqual(button.width(), 38)
        self.assertEqual(button.height(), 26)
        header_layout = results_header.layout()
        self.assertIs(header_layout.itemAt(0).widget(), button)
        self.assertIsNone(header_layout.itemAt(1).widget())
        self.assertEqual(header_layout.stretch(1), 1)
        self.assertEqual(
            header_layout.itemAt(2).widget().objectName(),
            "lineWrapLabel",
        )
        self.assertEqual(
            header_layout.itemAt(3).widget().objectName(),
            "lineWrapCheck",
        )

        button.click()

        self.assertTrue(file_controls.isHidden())
        self.assertTrue(filter_group.isHidden())
        self.assertFalse(results_header.isHidden())
        self.assertFalse(results.isHidden())
        self.assertEqual(button.text(), "▼")
        self.assertEqual(button.accessibleName(), "Restore layout")

        button.click()

        self.assertFalse(file_controls.isHidden())
        self.assertFalse(filter_group.isHidden())
        self.assertEqual(button.text(), "▲")
        self.assertEqual(button.accessibleName(), "Maximize results")

    def test_line_wrapping_can_be_toggled_from_results_header(self):
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        label = self.window.findChild(QLabel, "lineWrapLabel")
        checkbox = self.window.findChild(QCheckBox, "lineWrapCheck")

        self.assertEqual(label.text(), "Line wrapping")
        self.assertFalse(checkbox.isChecked())
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.NoWrap,
        )

        checkbox.click()
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.WidgetWidth,
        )

        checkbox.click()
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.NoWrap,
        )

    def test_top_controls_share_one_compact_row_with_dividers(self):
        top_controls = self.window.findChild(QWidget, "topControlsRow")
        item_names = [
            top_controls.layout().itemAt(index).widget().objectName()
            for index in range(top_controls.layout().count() - 1)
        ]

        self.assertEqual(
            item_names,
            [
                "contextLabel",
                "contextSpin",
                "topSeparatorContext",
                "limitLabel",
                "limitSpin",
                "topSeparatorLimit",
                "toggleAllButton",
                "topSeparatorGlobalToggle",
                "separateEntriesCheck",
            ],
        )
        for object_name in (
            "topSeparatorContext",
            "topSeparatorLimit",
            "topSeparatorGlobalToggle",
        ):
            separator = self.window.findChild(QFrame, object_name)
            self.assertEqual(separator.frameShape(), QFrame.Shape.VLine)

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
            ("error_colon", "error", "warning", "failed", "fatal"),
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
            "pattern_http_4xx": "HTTP 4xx (400–499)",
            "pattern_http_5xx": "HTTP 5xx (500–599)",
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

    def test_patterns_are_split_into_three_named_groups(self):
        expected_groups = {
            "pairedPatternGroup": "Colon and plain counterparts",
            "textPatternGroup": "Other text errors",
            "httpStatusGroup": "HTTP status codes",
        }

        for object_name, title in expected_groups.items():
            group = self.window.findChild(QGroupBox, object_name)
            self.assertIsNotNone(group)
            self.assertEqual(group.title(), title)

        global_toggle = self.window.findChild(QPushButton, "toggleAllButton")
        self.assertEqual(global_toggle.text(), "Global toggle all")
        for key in HTTP_STATUS_PATTERN_KEYS:
            self.assertFalse(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
            )

    def test_pattern_groups_are_compact_aligned_and_evenly_spaced(self):
        text_groups = self.window.findChild(QWidget, "textPatternGroupsRow")
        paired_group = self.window.findChild(QGroupBox, "pairedPatternGroup")
        text_group = self.window.findChild(QGroupBox, "textPatternGroup")
        http_group = self.window.findChild(QGroupBox, "httpStatusGroup")

        self.assertIs(paired_group.parentWidget(), text_groups)
        self.assertIs(text_group.parentWidget(), text_groups)
        self.assertEqual(
            paired_group.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Maximum,
        )
        self.assertEqual(
            text_group.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Maximum,
        )

        paired_layout = paired_group.layout()
        text_layout = text_group.layout()
        http_layout = http_group.layout()
        self.assertIsInstance(paired_layout, QGridLayout)
        self.assertIsInstance(text_layout, QGridLayout)
        self.assertIsInstance(http_layout, QGridLayout)
        self.assertEqual(text_layout.horizontalSpacing(), 10)
        self.assertEqual(text_layout.verticalSpacing(), 4)
        self.assertEqual(http_layout.horizontalSpacing(), 10)
        self.assertEqual(
            {text_layout.columnMinimumWidth(column) for column in range(4)},
            {text_layout.columnMinimumWidth(0)},
        )
        self.assertEqual(
            http_layout.columnMinimumWidth(0),
            http_layout.columnMinimumWidth(1),
        )

        paired_rows = {
            paired_layout.getItemPosition(
                paired_layout.indexOf(
                    self.window.findChild(QCheckBox, f"pattern_{key}")
                )
            )[0]
            for key in PAIRED_PATTERN_KEYS
        }
        text_rows = {
            text_layout.getItemPosition(
                text_layout.indexOf(
                    self.window.findChild(QCheckBox, f"pattern_{key}")
                )
            )[0]
            for key in TEXT_PATTERN_KEYS
        }
        self.assertEqual(paired_rows, {0, 1, 2})
        self.assertEqual(text_rows, {0, 1, 2})

        http_positions = [
            http_layout.getItemPosition(
                http_layout.indexOf(
                    self.window.findChild(QCheckBox, f"pattern_{key}")
                )
            )[:2]
            for key in HTTP_STATUS_PATTERN_KEYS
        ]
        self.assertEqual(http_positions, [(0, 0), (0, 1)])

    def test_toggle_all_enables_every_pattern_then_disables_every_pattern(self):
        button = self.window.findChild(QPushButton, "toggleAllButton")

        button.click()
        self.assertEqual(self.window.build_config().enabled_patterns, PATTERN_KEYS)

        button.click()
        self.assertEqual(self.window.build_config().enabled_patterns, ())

    def test_category_toggle_buttons_only_change_their_own_group(self):
        paired_toggle = self.window.findChild(QPushButton, "togglePairedButton")
        text_toggle = self.window.findChild(QPushButton, "toggleTextButton")
        self.assertEqual(paired_toggle.maximumWidth(), 100)
        self.assertEqual(text_toggle.maximumWidth(), 100)

        paired_toggle.click()
        self.assertTrue(
            all(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
                for key in PAIRED_PATTERN_KEYS
            )
        )
        self.assertFalse(
            any(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
                for key in HTTP_STATUS_PATTERN_KEYS
            )
        )

        paired_toggle.click()
        self.assertFalse(
            any(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
                for key in PAIRED_PATTERN_KEYS
            )
        )

        text_toggle.click()
        self.assertTrue(
            all(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
                for key in TEXT_PATTERN_KEYS
            )
        )
        text_toggle.click()
        self.assertFalse(
            any(
                self.window.findChild(QCheckBox, f"pattern_{key}").isChecked()
                for key in TEXT_PATTERN_KEYS
            )
        )

    def test_loading_stages_file_until_analyze_button_is_pressed(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server.log"
            log_path.write_text(
                "before\nERROR: boom\nafter\n",
                encoding="utf-8",
            )

            loaded = self.window.load_file(log_path)
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            staged_output = results.toPlainText()
            staged_status = self.window.statusBar().currentMessage()

            self.window.findChild(QLineEdit, "customPattern").returnPressed.emit()
            output_after_return = results.toPlainText()

            self.window.findChild(QPushButton, "analyzeButton").click()
            output = results.toPlainText()
            html = results.document().toHtml()

        self.assertTrue(loaded)
        self.assertEqual(staged_output, "")
        self.assertEqual(output_after_return, "")
        self.assertIn("3 lines loaded as UTF-8", staged_status)
        self.assertIn("press Analyze to begin", staged_status)
        self.assertIn("ERROR: boom", output)
        self.assertNotIn("\033[", output)
        self.assertIn(COLORS["match"].name(), html)
        self.assertIn(COLORS["matched_text"].name(), html)
        self.assertIn(COLORS["line_number"].name(), html)
        self.assertIn("UTF-8", self.window.statusBar().currentMessage())

    def test_zero_match_patterns_stay_in_summary_without_blank_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "summary.log"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")

            self.window.load_file(log_path)
            self.window.findChild(QPushButton, "analyzeButton").click()
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
            self.window.findChild(QPushButton, "analyzeButton").click()
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
            self.window.findChild(QPushButton, "analyzeButton").click()
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
