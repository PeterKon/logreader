import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QStyleOptionSpinBox

from logreader.filter_panel import FilterPanel
from logreader.input_menus import InputContextMenu
from logreader.results_view import ResultsView


class InputMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = FilterPanel()
        self.view = ResultsView()
        self.panel.show()
        self.view.show()
        self.app.processEvents()
        self.app.clipboard().clear()
        for widget in (self.panel, self.view):
            self.addCleanup(widget.deleteLater)
            self.addCleanup(widget.close)

    def menu(self, editor):
        controller = editor.findChild(InputContextMenu)
        self.assertIsNotNone(controller)
        menu = controller.create_menu()
        self.addCleanup(menu.deleteLater)
        return menu

    @staticmethod
    def labels(menu):
        return [None if action.isSeparator() else action.text().split("\t")[0]
                for action in menu.actions()]

    def action(self, editor, name):
        return next(action for action in self.menu(editor).actions() if action.objectName() == name)

    def test_each_input_group_has_its_own_actions_in_stable_order(self):
        for editor in (self.panel._context_spin.lineEdit(), self.panel._limit_spin.lineEdit()):
            self.assertEqual(self.labels(self.menu(editor)), ["Copy", "Paste", "Select all"])
        for editor in (self.panel._custom_pattern, self.panel._regex_pattern):
            self.assertEqual(self.labels(self.menu(editor)),
                             ["Undo", "Redo", None, "Cut", "Copy", "Paste", "Select all"])
        self.view.set_source(("source",), 1)
        for source_active in (False, True):
            self.view.set_source_active(source_active)
            self.assertEqual(self.labels(self.menu(self.view._search_input)),
                             ["Undo", None, "Copy", "Paste", "Select all"])

    def test_unavailable_actions_stay_visible_and_follow_editor_state(self):
        editor = self.panel._regex_pattern
        empty = self.menu(editor)
        self.assertTrue(all(not action.isEnabled() for action in empty.actions()
                            if not action.isSeparator()))
        editor.setText("error")
        editor.insert(".*")
        editor.selectAll()
        self.app.clipboard().setText("replacement")
        edited = self.menu(editor)
        self.assertEqual(self.labels(empty), self.labels(edited))
        enabled = {action.objectName(): action.isEnabled() for action in edited.actions()
                   if not action.isSeparator()}
        self.assertEqual(enabled, {"undo": True, "redo": False, "cut": True,
                                   "copy": True, "paste": True, "selectAll": False})
        self.action(editor, "undo").trigger()
        self.assertEqual(editor.text(), "error")
        self.assertTrue(self.action(editor, "redo").isEnabled())
        self.action(editor, "redo").trigger()
        self.assertEqual(editor.text(), "error.*")

    def test_go_to_line_menu_pastes_and_navigates_without_losing_shortcuts(self):
        self.view.set_source(("first", "second", "third"), 103)
        self.view.set_source_active(True)
        editor = self.view.source_view.goto_input
        self.assertEqual(self.send_context_menu(editor, editor.rect().center()),
                         [["Copy", "Paste", "Select all"]])
        editor.setText("101")
        self.app.clipboard().setText("103")
        self.action(editor, "selectAll").trigger()
        self.action(editor, "paste").trigger()
        self.assertEqual(editor.text(), "103")
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.text(), "101")
        QTest.keyClick(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.text(), "103")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(self.view.source_view.target_line, 103)

    def test_copy_cut_paste_and_select_all_act_on_the_correct_input(self):
        editor = self.panel._custom_pattern
        editor.setText("needle")
        self.action(editor, "selectAll").trigger()
        self.action(editor, "copy").trigger()
        self.assertEqual(self.app.clipboard().text(), "needle")
        self.action(editor, "cut").trigger()
        self.assertEqual(editor.text(), "")
        self.action(editor, "paste").trigger()
        self.assertEqual(editor.text(), "needle")
        self.assertEqual(self.panel._regex_pattern.text(), "")

        spin = self.panel._limit_spin
        self.app.clipboard().setText("750 000")
        self.action(spin.lineEdit(), "selectAll").trigger()
        self.action(spin.lineEdit(), "paste").trigger()
        spin.interpretText()
        self.assertEqual(spin.value(), 750_000)

    def test_removed_search_menu_commands_keep_their_keyboard_shortcuts(self):
        editor = self.view._search_input
        editor.setFocus()
        QTest.keyClicks(editor, "needle")
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.selectedText(), "needle")
        QTest.keyClick(editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.text(), "")
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.text(), "needle")
        QTest.keyClick(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.text(), "")

    def send_context_menu(self, widget, point, reason=QContextMenuEvent.Reason.Mouse):
        captured = []

        def capture_popup():
            popup = self.app.activePopupWidget()
            if popup is not None:
                self.assertIsInstance(popup, QMenu)
                captured.append(self.labels(popup))
                popup.close()

        QTimer.singleShot(0, capture_popup)
        event = QContextMenuEvent(reason, point, widget.mapToGlobal(point))
        self.app.sendEvent(widget, event)
        self.app.processEvents()
        return captured

    def test_numeric_text_mouse_and_keyboard_context_menus_use_the_short_menu(self):
        expected = [["Copy", "Paste", "Select all"]]
        for spin in (self.panel._context_spin, self.panel._limit_spin):
            editor = spin.lineEdit()
            self.assertEqual(self.send_context_menu(editor, editor.rect().center()), expected)
            self.assertEqual(self.send_context_menu(spin, editor.geometry().center()), expected)
            self.assertEqual(self.send_context_menu(
                spin, QPoint(), QContextMenuEvent.Reason.Keyboard), expected)

    def test_right_clicking_arrows_never_opens_a_menu_or_changes_the_value(self):
        for spin in (self.panel._context_spin, self.panel._limit_spin, self.view._search_navigation):
            option = QStyleOptionSpinBox()
            spin.initStyleOption(option)
            value = spin.value()
            for subcontrol in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
                rect = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,
                                                  option, subcontrol, spin)
                self.assertEqual(self.send_context_menu(spin, rect.center()), [])
                self.assertEqual(spin.value(), value)
        self.assertEqual(self.send_context_menu(
            self.view._search_navigation, QPoint(), QContextMenuEvent.Reason.Keyboard), [])


if __name__ == "__main__":
    unittest.main()
