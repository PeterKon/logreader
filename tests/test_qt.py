import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFrame,
        QGridLayout,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
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
    from logreader.core import analyze_lines
    from logreader.qt_app import COLORS, ENTRY_SEPARATOR, RULE, LogreaderWindow
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
        self.assertEqual(config.regex_patterns, ())
        self.assertFalse(config.separate_entries)
        self.assertEqual(
            self.window.findChild(QLabel, "limitLabel").text(),
            "Total errors limit",
        )
        self.assertEqual(
            self.window.findChild(QLabel, "contextLabel").text(),
            "Context around errors",
        )
        self.assertEqual(
            self.window.findChild(QCheckBox, "separateEntriesCheck").text(),
            "Separation of lines",
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
        self.assertEqual(button.toolTip(), "Expand results window")
        self.assertIn("QToolTip { font-weight: 400; }", button.styleSheet())
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
        self.assertEqual(button.toolTip(), "Show menu and filters")

        button.click()

        self.assertFalse(file_controls.isHidden())
        self.assertFalse(filter_group.isHidden())
        self.assertEqual(button.text(), "▲")
        self.assertEqual(button.accessibleName(), "Maximize results")
        self.assertEqual(button.toolTip(), "Expand results window")

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
        self.window.findChild(QPushButton, "customPatternAddButton").click()

        config = self.window.build_config()

        self.assertEqual(config.context, 5)
        self.assertEqual(config.limit, 10)
        self.assertEqual(
            config.enabled_patterns,
            ("error_colon", "error", "warning", "failed", "fatal"),
        )
        self.assertEqual(config.custom_patterns, ("timeout",))
        self.assertEqual(config.regex_patterns, ())
        self.assertTrue(config.separate_entries)

    def test_error_patterns_and_plain_variants_are_available_as_toggles(self):
        expected_labels = {
            "pattern_error_colon": "Error:",
            "pattern_error": "Error",
            "pattern_warning": "Warning:",
            "pattern_warning_generic": "Warning",
            "pattern_exception": "Exception:",
            "pattern_exception_generic": "Exception",
            "pattern_failed": "Failed",
            "pattern_fatal": "Fatal",
            "pattern_failure": "Failure",
            "pattern_critical": "Critical",
            "pattern_illegal": "Illegal",
            "pattern_invalid": "Invalid",
            "pattern_aborted": "Aborted",
            "pattern_terminated": "Terminated",
            "pattern_timeout": "Timeout",
            "pattern_uninitialized": "Uninitialized",
            "pattern_not_found": "Not found",
            "pattern_http_4xx": "4xx",
            "pattern_http_5xx": "5xx",
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

    def test_patterns_are_split_into_five_named_groups(self):
        expected_groups = {
            "pairedPatternGroup": "Colon / plain error pairs",
            "textPatternGroup": "Other errors",
            "httpStatusGroup": "HTTP codes",
            "customPatternGroup": "Plain text search",
            "regexPatternGroup": "Regex search",
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

    def test_custom_patterns_are_added_to_the_list_before_configuration(self):
        input_box = self.window.findChild(QLineEdit, "customPattern")
        add_button = self.window.findChild(
            QPushButton,
            "customPatternAddButton",
        )
        pattern_list = self.window.findChild(QListWidget, "customPatternList")

        self.assertEqual(add_button.text(), "+add")
        self.assertEqual(input_box.placeholderText(), "Enter item")
        self.assertEqual(
            input_box.palette()
            .color(QPalette.ColorRole.PlaceholderText)
            .alpha(),
            90,
        )
        input_box.setText(" timeout ")
        self.assertEqual(self.window.build_config().custom_patterns, ())

        add_button.click()
        self.assertEqual(input_box.text(), "")
        self.assertEqual(pattern_list.count(), 1)
        self.assertEqual(pattern_list.item(0).text(), "")
        self.assertEqual(
            pattern_list.item(0).data(Qt.ItemDataRole.UserRole),
            "timeout",
        )
        item_label = pattern_list.itemWidget(pattern_list.item(0)).findChild(QLabel)
        self.assertEqual(item_label.text(), "timeout")
        self.assertFalse(item_label.font().bold())

        input_box.setText("connection refused")
        input_box.returnPressed.emit()
        self.assertEqual(pattern_list.count(), 2)
        self.assertEqual(pattern_list.spacing(), 0)
        self.assertTrue(pattern_list.uniformItemSizes())
        self.assertEqual(
            [
                pattern_list.item(index).sizeHint().height()
                for index in range(pattern_list.count())
            ],
            [18, 18],
        )
        self.assertEqual(
            self.window.build_config().custom_patterns,
            ("timeout", "connection refused"),
        )

        remove_buttons = pattern_list.findChildren(
            QPushButton,
            "customPatternRemoveButton",
        )
        self.assertEqual([button.text() for button in remove_buttons], ["-", "-"])
        self.assertEqual(remove_buttons[0].accessibleName(), "Remove timeout")
        remove_buttons[0].click()
        self.assertEqual(pattern_list.count(), 1)
        self.assertEqual(
            pattern_list.item(0).data(Qt.ItemDataRole.UserRole),
            "connection refused",
        )
        self.assertEqual(
            self.window.build_config().custom_patterns,
            ("connection refused",),
        )

        input_box.setText("   ")
        add_button.click()
        self.assertEqual(pattern_list.count(), 1)

    def test_regex_patterns_use_the_same_managed_list_ui(self):
        input_box = self.window.findChild(QLineEdit, "regexPattern")
        add_button = self.window.findChild(
            QPushButton,
            "regexPatternAddButton",
        )
        pattern_list = self.window.findChild(QListWidget, "regexPatternList")

        self.assertEqual(input_box.placeholderText(), "Enter item")
        self.assertEqual(
            input_box.palette()
            .color(QPalette.ColorRole.PlaceholderText)
            .alpha(),
            90,
        )
        self.assertEqual(add_button.text(), "+add")
        self.assertEqual(pattern_list.spacing(), 0)
        self.assertTrue(pattern_list.uniformItemSizes())

        input_box.setText(r"^ERROR:\s+[0-9]+$")
        self.assertEqual(self.window.build_config().regex_patterns, ())
        add_button.click()

        config = self.window.build_config()
        self.assertEqual(config.regex_patterns, (r"^ERROR:\s+[0-9]+$",))
        self.assertEqual(pattern_list.item(0).sizeHint().height(), 18)
        item_label = pattern_list.itemWidget(pattern_list.item(0)).findChild(QLabel)
        self.assertFalse(item_label.font().bold())

        analysis = analyze_lines(
            ["ERROR: 42", "error: 42"],
            config.search_patterns(),
        )
        self.assertEqual(analysis.category("regex_1").match_count, 1)
        self.assertEqual(
            [
                line.number
                for excerpt in analysis.category("regex_1").excerpts
                for line in excerpt.lines
                if line.is_match
            ],
            [1],
        )

        remove_button = pattern_list.findChild(
            QPushButton,
            "regexPatternRemoveButton",
        )
        self.assertEqual(remove_button.text(), "-")
        remove_button.click()
        self.assertEqual(pattern_list.count(), 0)
        self.assertEqual(self.window.build_config().regex_patterns, ())

    def test_pattern_groups_are_compact_aligned_and_evenly_spaced(self):
        text_groups = self.window.findChild(QWidget, "textPatternGroupsRow")
        paired_group = self.window.findChild(QGroupBox, "pairedPatternGroup")
        text_group = self.window.findChild(QGroupBox, "textPatternGroup")
        http_group = self.window.findChild(QGroupBox, "httpStatusGroup")
        custom_group = self.window.findChild(QGroupBox, "customPatternGroup")
        regex_group = self.window.findChild(QGroupBox, "regexPatternGroup")
        http_row = self.window.findChild(QWidget, "httpStatusRow")

        self.assertIs(paired_group.parentWidget(), text_groups)
        self.assertIs(text_group.parentWidget(), text_groups)
        self.assertIs(http_group.parentWidget(), http_row)
        self.assertIs(custom_group.parentWidget(), http_row)
        self.assertIs(regex_group.parentWidget(), http_row)
        self.assertIs(http_row.layout().itemAt(0).widget(), custom_group)
        self.assertIs(http_row.layout().itemAt(1).widget(), regex_group)
        self.assertIs(http_row.layout().itemAt(2).widget(), http_group)
        self.assertTrue(
            http_row.layout().itemAt(0).alignment()
            & Qt.AlignmentFlag.AlignTop
        )
        self.assertTrue(
            http_row.layout().itemAt(1).alignment()
            & Qt.AlignmentFlag.AlignTop
        )
        self.assertTrue(
            http_row.layout().itemAt(2).alignment()
            & Qt.AlignmentFlag.AlignTop
        )
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
        self.assertGreater(http_layout.columnMinimumWidth(0), 0)

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
        self.assertEqual(http_positions, [(0, 0), (1, 0)])

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

    def test_entry_separation_is_optional_and_uses_a_short_arrow(self):
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
            f"{ENTRY_SEPARATOR}\n"
            "6      -> ERROR: second"
        )
        self.assertIn(adjacent_results, without_separator)
        self.assertNotIn(separated_results, without_separator)
        self.assertIn(separated_results, with_separator)


if __name__ == "__main__":
    unittest.main()
