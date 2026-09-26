import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QStyle, QStyleOptionSpinBox

from logreader.ui.qt_app import LogreaderWindow
from logreader.ui.theme import THEME_COLORS
from qt_helpers import wait_for_load


class ControlFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.window = LogreaderWindow()
        self.window.resize(1080, 800)
        self.window.move(30, 30)
        self.window.show()
        self.window.activateWindow()
        QTest.qWait(20)

    def tearDown(self):
        self.window.close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def open_document(self, name):
        path = Path(self.directory.name) / name
        path.write_text("ERROR: sample\n", encoding="utf-8")
        self.window.load_file(path)
        page = self.window._document
        wait_for_load(page)
        self.app.processEvents()
        return page

    def test_startup_and_new_tab_do_not_focus_controls(self):
        self.assertFalse(self.window._open_button.hasFocus())
        first = self.open_document("first.log")
        first.analyze()
        for _ in range(1000):
            if not first.session.is_busy:
                break
            QTest.qWait(5)
        self.assertFalse(first.session.is_busy)
        second = self.open_document("second.log")
        self.assertFalse(second.filter_panel._context_spin.hasFocus())
        self.assertFalse(second.filter_panel._context_spin.lineEdit().hasFocus())
        self.assertFalse(second.filter_panel._limit_spin.hasFocus())

    def move_pointer(self, widget, position=None):
        position = position if position is not None else widget.rect().center()
        QTest.mouseMove(widget, position + QPoint(1, 0))
        QTest.qWait(50)
        QTest.mouseMove(widget, position)
        QTest.qWait(100)  # Allow native Windows hover events to arrive.

    def test_revisiting_tabs_keeps_neutral_or_explicit_editing_focus(self):
        pages = [self.open_document(name) for name in ("first.log", "second.log")]
        for page in pages * 3:
            self.window._select_document(page)
            self.app.processEvents()
            self.assertIs(self.app.focusWidget(), page)
        editor = pages[1].filter_panel._custom_pattern
        pages[1].filter_panel._tabs.setCurrentIndex(2)
        editor.setFocus()
        self.window._select_document(pages[0])
        self.window._select_document(pages[1])
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), editor)

    def assert_button_state(self, button, hovered):
        self.assertEqual(button.underMouse(), hovered)
        self.assertFalse(button.hasFocus())
        image = button.grab().toImage()
        if button.objectName() in ("toggleAllButton", "togglePairedButton", "toggleTextButton"):
            expected = QColor(THEME_COLORS["ui_button_hover"]) if hovered else QColor(Qt.GlobalColor.transparent)
            self.assertEqual(image.pixelColor(3, image.height() // 2), expected)
        normal_border = "ui_border" if button.objectName() == "openButton" else "ui_border_strong"
        expected = QColor(THEME_COLORS["ui_accent" if hovered else normal_border])
        self.assertEqual(image.pixelColor(0, image.height() // 2), expected)

    def test_buttons_keep_hover_after_click_and_clear_it_on_leave(self):
        page = self.open_document("sample.log")
        names = ("openButton", "toggleAllButton", "togglePairedButton", "toggleTextButton",
                 "customPatternAddButton", "regexPatternAddButton", "maximizeResultsButton")
        with patch("logreader.ui.qt_app.QFileDialog.getOpenFileNames", return_value=([], "")):
            for name in names:
                with self.subTest(button=name):
                    button = self.window.findChild(QPushButton, name)
                    page.filter_panel._tabs.setCurrentIndex(2 if name in (
                        "customPatternAddButton", "regexPatternAddButton",
                    ) else 0)
                    self.app.processEvents()
                    self.move_pointer(button)
                    self.assert_button_state(button, True)
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    # The expansion button moves with the changed layout.
                    self.move_pointer(button)
                    self.assert_button_state(button, True)
                    self.move_pointer(self.window, QPoint(1, self.window.height() - 1))
                    self.assert_button_state(button, False)
                    page.results_view.set_maximized(False)

    def test_open_button_uses_normal_hover_after_modal_return(self):
        button = self.window._open_button
        self.move_pointer(button)

        def show_dialog(*args):
            dialog = QDialog(self.window)
            QTimer.singleShot(50, dialog.accept)
            dialog.exec()
            return [], ""

        with patch("logreader.ui.qt_app.QFileDialog.getOpenFileNames", side_effect=show_dialog):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertFalse(button.hasFocus())
        self.move_pointer(self.window, QPoint(1, self.window.height() - 1))
        self.assert_button_state(button, False)
        self.move_pointer(button)
        self.assert_button_state(button, True)

    def test_arrow_clicks_do_not_leave_focus_or_selection_but_text_clicks_do(self):
        page = self.open_document("sample.log")
        for spin in (page.filter_panel._context_spin, page.filter_panel._limit_spin):
            for control in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
                with self.subTest(spin=spin.objectName(), control=control):
                    editor = spin.lineEdit()
                    QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
                    self.assertTrue(spin.hasFocus())
                    editor.selectAll()
                    option = QStyleOptionSpinBox()
                    spin.initStyleOption(option)
                    arrow = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, spin)
                    previous = spin.value()
                    QTest.mousePress(spin, Qt.MouseButton.LeftButton, pos=arrow.center())
                    QTest.qWait(600)
                    self.assertFalse(spin.hasFocus())
                    self.assertFalse(editor.hasFocus())
                    self.assertFalse(editor.hasSelectedText())
                    QTest.mouseRelease(spin, Qt.MouseButton.LeftButton, pos=arrow.center())
                    self.assertNotEqual(spin.value(), previous)
                    self.assertFalse(spin.hasFocus())
                    self.assertFalse(editor.hasSelectedText())
                    QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
                    self.assertTrue(spin.hasFocus())
                    editor.selectAll()
                    QTest.keyClicks(editor, "4")
                    spin.interpretText()
                    self.assertEqual(spin.value(), 4)
