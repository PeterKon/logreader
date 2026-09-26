import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QLineEdit,
        QListWidget,
        QPushButton,
        QSpinBox,
        QTabBar,
    )

    from logreader.config import (
        DEFAULT_ENABLED_PATTERNS,
        PAIRED_PATTERN_KEYS,
        TEXT_PATTERN_KEYS,
    )
    from logreader.ui.filter_panel import FilterPanel
    from logreader.ui.qt_app import INTERFACE_STYLE_SHEET
    from logreader.core import analyze_lines
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class FilterPanelTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = FilterPanel()

    def tearDown(self):
        self.panel.close()
        self.app.processEvents()

    def test_build_config_reflects_all_filter_controls(self):
        self.panel.findChild(QSpinBox, "contextSpin").setValue(7)
        self.panel.findChild(QSpinBox, "limitSpin").setValue(25)
        self.panel.findChild(
            QCheckBox,
            "pattern_error_colon",
        ).setChecked(False)
        self.panel.findChild(QCheckBox, "pattern_warning").setChecked(True)
        self.panel.findChild(QCheckBox, "pattern_unavailable").setChecked(True)
        self.panel.findChild(
            QCheckBox,
            "separateEntriesCheck",
        ).setChecked(True)
        self.panel.findChild(QCheckBox, "combinedViewCheck").setChecked(True)

        config = self.panel.build_config()

        self.assertEqual(config.context, 7)
        self.assertEqual(config.max_lines_scanned, 25)
        self.assertEqual(
            config.enabled_patterns,
            (
                "error",
                "exception",
                "exception_generic",
                "warning",
                "failed",
                "failure",
                "fatal",
                "critical",
                "refused",
                "unavailable",
            ),
        )
        self.assertTrue(config.separate_entries)
        self.assertTrue(config.combined_view)

    def test_global_and_category_toggles_are_scoped(self):
        paired_toggle = self.panel.findChild(QPushButton, "togglePairedButton")
        text_toggle = self.panel.findChild(QPushButton, "toggleTextButton")
        global_toggle = self.panel.findChild(QPushButton, "toggleAllButton")
        self.panel.findChild(QCheckBox, "pattern_http_4xx").setChecked(True)
        self.panel._custom_pattern.setText("keep")
        self.panel.add_custom_pattern()

        paired_toggle.click()
        self.assertTrue(
            all(
                self.panel.findChild(
                    QCheckBox,
                    f"pattern_{key}",
                ).isChecked()
                for key in PAIRED_PATTERN_KEYS
            )
        )
        self.assertEqual(
            tuple(
                key
                for key in TEXT_PATTERN_KEYS
                if self.panel.findChild(
                    QCheckBox,
                    f"pattern_{key}",
                ).isChecked()
            ),
            tuple(key for key in TEXT_PATTERN_KEYS if key in DEFAULT_ENABLED_PATTERNS),
        )

        text_toggle.click()
        self.assertTrue(
            all(
                self.panel.findChild(
                    QCheckBox,
                    f"pattern_{key}",
                ).isChecked()
                for key in TEXT_PATTERN_KEYS
            )
        )

        global_toggle.click()
        self.assertEqual(self.panel.build_config().enabled_patterns, ("http_4xx",))
        self.assertEqual(global_toggle.text(), "Select all text patterns")
        global_toggle.click()
        self.assertEqual(
            self.panel.build_config().enabled_patterns,
            PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS + ("http_4xx",),
        )
        self.assertEqual(global_toggle.text(), "Clear all text patterns")
        self.assertEqual(self.panel.build_config().custom_patterns, ("keep",))

    def test_switching_editors_preserves_filters_options_and_drafts(self):
        tabs = self.panel.findChild(QTabBar, "filterTabs")
        # Documents inherit the window theme after the counts are first sized.
        self.panel.setStyleSheet(INTERFACE_STYLE_SHEET)
        self.panel.resize(1400, 500)
        self.panel.show()
        self.app.processEvents()
        for count in self.panel._tab_counts:
            self.assertGreaterEqual(count.width(), count.sizeHint().width(), count.text())
        self.assertEqual([tabs.tabText(index) for index in range(tabs.count())],
                         ["Common patterns", "Advanced patterns", "Text and Regex"])
        self.assertEqual(self.panel._tab_counts[0].text(), "(9/22)")
        self.assertEqual(self.panel._tab_counts[1].text(), "(0/2)")
        self.panel._pattern_checkboxes["unavailable"].setChecked(True)
        self.panel._pattern_checkboxes["http_5xx"].setChecked(True)
        tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.panel._custom_pattern.setText("CaseSensitive")
        QTest.keyClick(self.panel._custom_pattern, Qt.Key.Key_Return)
        self.panel.findChild(QPushButton, "customPatternMatchCaseButton").click()
        self.panel.findChild(QPushButton, "customPatternExcludeButton").click()
        self.panel._regex_pattern.setText(r"^ERROR\b")
        self.panel.add_regex_pattern()
        self.panel._custom_pattern.setText("unfinished text")
        self.panel._regex_pattern.setText("unfinished [")
        before = self.panel.build_config()
        self.app.processEvents()

        for index in (0, 1, 2, 1, 0, 2):
            count = tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            self.assertGreaterEqual(count.width(), count.sizeHint().width(), count.text())
            self.assertTrue(tabs.rect().contains(tabs.tabRect(index)),
                            f"Tab {index}: {tabs.tabRect(index)} outside {tabs.rect()}")
            self.assertTrue(tabs.tabRect(index).contains(count.geometry()))
            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton,
                             pos=count.mapTo(tabs, count.rect().center()))
            self.app.processEvents()
            self.assertEqual(tabs.currentIndex(), index)
            self.assertEqual(self.panel.build_config(), before)
            self.assertEqual(self.panel._custom_pattern.text(), "unfinished text")
            self.assertEqual(self.panel._regex_pattern.text(), "unfinished [")
            self.assertEqual(self.panel._custom_pattern.isVisible(), index == 2)
            self.assertEqual(self.panel._pattern_checkboxes["error_colon"].isVisible(), index == 0)
            self.assertEqual(self.panel._pattern_checkboxes["http_5xx"].isVisible(), index == 1)
            self.assertEqual(self.panel._toggle_all_button.isVisible(), index == 0)
            self.assertTrue(self.panel._context_spin.isVisible())
            self.assertTrue(self.panel._limit_spin.isVisible())
            self.assertTrue(self.panel._separate_entries.isVisible())
            self.assertTrue(self.panel._combined_view.isVisible())

        self.assertEqual(before.custom_pattern_match_case, (True,))
        self.assertEqual(before.custom_pattern_exclude, (True,))
        self.assertEqual(self.panel._tab_counts[0].text(), "(10/22)")
        self.assertEqual(self.panel._tab_counts[1].text(), "(1/2)")
        self.assertEqual(self.panel._tab_counts[2].text(), "(2)")
        analysis = analyze_lines(["service UNAVAILABLE", "HTTP 503", "service available"],
                                 before.search_patterns())
        self.assertEqual(analysis.category_match_counts["unavailable"], 1)
        self.assertEqual(analysis.category_match_counts["http_5xx"], 1)
        self.assertEqual(self.panel._exclusions_label.text(), "1 exclusion")
        self.assertTrue(self.panel._exclusions_label.isVisible())
        self.panel.findChild(QPushButton, "customPatternRemoveButton").click()
        self.assertEqual(self.panel._tab_counts[2].text(), "(1)")
        self.assertFalse(self.panel._exclusions_label.isVisible())

    def test_each_colon_and_regular_pattern_remains_independent(self):
        for colon, regular in zip(PAIRED_PATTERN_KEYS[::2], PAIRED_PATTERN_KEYS[1::2]):
            with self.subTest(colon=colon, regular=regular):
                colon_box = self.panel._pattern_checkboxes[colon]
                regular_box = self.panel._pattern_checkboxes[regular]
                self.assertEqual(colon_box.text(), regular_box.text() + ":")
                colon_box.setChecked(True)
                regular_box.setChecked(False)
                self.assertIn(colon, self.panel.build_config().enabled_patterns)
                self.assertNotIn(regular, self.panel.build_config().enabled_patterns)
                colon_box.setChecked(False)
                regular_box.setChecked(True)
                self.assertNotIn(colon, self.panel.build_config().enabled_patterns)
                self.assertIn(regular, self.panel.build_config().enabled_patterns)

    def test_plain_text_list_adds_trims_orders_and_removes_items(self):
        input_box = self.panel.findChild(QLineEdit, "customPattern")
        add_button = self.panel.findChild(
            QPushButton,
            "customPatternAddButton",
        )
        pattern_list = self.panel.findChild(QListWidget, "customPatternList")

        add_button.click()
        self.assertEqual(pattern_list.count(), 0)

        input_box.setText(" timeout ")
        add_button.click()
        input_box.setText("connection lost")
        input_box.returnPressed.emit()

        self.assertEqual(
            self.panel.build_config().custom_patterns,
            ("timeout", "connection lost"),
        )
        self.assertEqual(input_box.text(), "")
        first_item = pattern_list.item(0)
        self.assertEqual(
            first_item.data(Qt.ItemDataRole.AccessibleTextRole),
            "timeout",
        )

        first_row = pattern_list.itemWidget(first_item)
        first_row.findChild(
            QPushButton,
            "customPatternRemoveButton",
        ).click()
        self.assertEqual(
            self.panel.build_config().custom_patterns,
            ("connection lost",),
        )

    def test_regex_list_preserves_expression_and_removes_items(self):
        input_box = self.panel.findChild(QLineEdit, "regexPattern")
        add_button = self.panel.findChild(
            QPushButton,
            "regexPatternAddButton",
        )
        pattern_list = self.panel.findChild(QListWidget, "regexPatternList")

        input_box.setText("(?i)error")
        add_button.click()
        input_box.setText(r"^WARN\b")
        add_button.click()

        config = self.panel.build_config()
        self.assertEqual(config.regex_patterns, ("(?i)error", r"^WARN\b"))
        self.assertTrue(
            all(pattern.is_regex for pattern in config.search_patterns()[-2:])
        )

        first_item = pattern_list.item(0)
        first_row = pattern_list.itemWidget(first_item)
        first_row.findChild(
            QPushButton,
            "regexPatternRemoveButton",
        ).click()
        self.assertEqual(
            self.panel.build_config().regex_patterns,
            (r"^WARN\b",),
        )


if __name__ == "__main__":
    unittest.main()
