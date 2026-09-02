import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QLineEdit,
        QListWidget,
        QPushButton,
        QSpinBox,
    )

    from logreader.config import (
        DEFAULT_ENABLED_PATTERNS,
        PAIRED_PATTERN_KEYS,
        PATTERN_KEYS,
        TEXT_PATTERN_KEYS,
    )
    from logreader.filter_panel import FilterPanel
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
        self.panel.findChild(
            QCheckBox,
            "separateEntriesCheck",
        ).setChecked(True)

        config = self.panel.build_config()

        self.assertEqual(config.context, 7)
        self.assertEqual(config.limit, 25)
        self.assertEqual(
            config.enabled_patterns,
            ("error", "warning", "failed", "fatal"),
        )
        self.assertTrue(config.separate_entries)

    def test_global_and_category_toggles_are_scoped(self):
        paired_toggle = self.panel.findChild(QPushButton, "togglePairedButton")
        text_toggle = self.panel.findChild(QPushButton, "toggleTextButton")
        global_toggle = self.panel.findChild(QPushButton, "toggleAllButton")

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
        self.assertEqual(self.panel.build_config().enabled_patterns, PATTERN_KEYS)
        global_toggle.click()
        self.assertEqual(self.panel.build_config().enabled_patterns, ())

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
