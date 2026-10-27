import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QContextMenuEvent, QIcon, QMouseEvent, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from qt_helpers import qt_application, retire_window
from logreader.ui.bookmarks import Bookmark, BookmarkNotesDialog
from logreader.ui.dialogs import CompactDialog
from logreader.ui.filter_panel import PatternEditDialog, SearchPatternMenu
from logreader.ui.qt_app import LogreaderWindow
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.theme import THEME_COLORS
from logreader.ui.widgets.menu_style import CONTEXT_MENU_STYLE_SHEET, style_checkbox_menu, style_menu


class MenuStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def test_qt_generated_dialog_menus_receive_the_theme(self):
        source = SourceLocation("sample", 1)
        dialogs = [PatternEditDialog("sample", is_regex=regex, parent=None)
                   for regex in (False, True)]
        dialogs.append(BookmarkNotesDialog(Bookmark(source, "Sample"), source))
        observed = []
        for dialog in dialogs:
            self.addCleanup(retire_window, dialog)
            label = QLabel("Invalid filters", dialog)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            for target in (dialog.editor.viewport(), dialog.editor.verticalScrollBar(),
                           dialog.editor.horizontalScrollBar(), label):
                def capture():
                    menu = self.app.activePopupWidget()
                    if isinstance(menu, QMenu):
                        observed.append(menu.styleSheet())
                        menu.close()

                QTimer.singleShot(0, capture)
                point = QPoint(5, 5)
                QApplication.sendEvent(target, QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse, point, target.mapToGlobal(point)))
                self.app.processEvents()
        self.assertEqual(observed, [CONTEXT_MENU_STYLE_SHEET] * 12)

    def test_theme_preserves_reference_menus_and_does_not_escape_the_app(self):
        window = LogreaderWindow()
        self.addCleanup(retire_window, window)
        pattern = SearchPatternMenu(window)
        references = (window._view_menu, window._zoom_menu, pattern)
        original = [menu.styleSheet() for menu in references]
        unrelated = QMenu()
        self.addCleanup(unrelated.deleteLater)
        for menu in (*references, unrelated):
            menu.ensurePolished()
            self.assertFalse(menu.property("contextMenuStyled"))
        self.assertEqual([menu.styleSheet() for menu in references], original)
        self.assertEqual(unrelated.styleSheet(), "")

        preset = QMenu(window)
        preset.setObjectName("regexPresetMenu")
        preset.ensurePolished()
        self.assertTrue(preset.styleSheet().startswith(CONTEXT_MENU_STYLE_SHEET))
        self.assertIn("menu-scrollable: 1", preset.styleSheet())

    def test_text_action_icons_are_white_when_enabled_and_gray_when_disabled(self):
        dialog = PatternEditDialog("sample", is_regex=False, parent=None)
        self.addCleanup(retire_window, dialog)
        menu = dialog.editor.createStandardContextMenu()
        self.addCleanup(menu.close)
        actions = [action for action in menu.actions() if not action.isSeparator()]
        # The offscreen platform omits native icons. Supply the same dark input
        # so the menu's normal show path is exercised on every platform.
        for action in actions:
            if action.icon().isNull():
                pixmap = QPixmap(16, 16)
                pixmap.fill(Qt.GlobalColor.black)
                action.setIcon(QIcon(pixmap))
        menu.popup(QPoint(100, 100))
        self.app.processEvents()
        for action in actions:
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected,
                         QIcon.Mode.Disabled):
                with self.subTest(action=action.objectName(), mode=mode):
                    image = action.icon().pixmap(16, 16, mode).toImage()
                    colors = [image.pixelColor(x, y)
                              for y in range(image.height()) for x in range(image.width())
                              if image.pixelColor(x, y).alpha() >= 128]
                    expected = QColor(THEME_COLORS["ui_muted"] if mode == QIcon.Mode.Disabled else "#ffffff")
                    self.assertTrue(colors)
                    for color in colors:
                        # Fractional display scaling rounds premultiplied alpha.
                        self.assertLessEqual(max(abs(actual - target) for actual, target in
                                                 zip(color.getRgb()[:3], expected.getRgb()[:3])), 3)

    def test_short_menu_rows_highlight_and_activate_at_the_right_edge(self):
        dialog = CompactDialog("Example")
        self.addCleanup(retire_window, dialog)
        dialog.show()
        self.app.processEvents()
        menu = QMenu(dialog)
        self.addCleanup(menu.close)
        action = menu.addAction("Top")
        menu.addAction("Bottom")
        triggered = QSignalSpy(action.triggered)
        menu.popup(QPoint(100, 100))
        self.app.processEvents()
        point = QPoint(menu.width() - 3, menu.actionGeometry(action).center().y())
        QApplication.sendEvent(menu, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(point), QPointF(menu.mapToGlobal(point)),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()
        image = menu.grab().toImage()
        scale = image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(point.x() * scale), round(point.y() * scale)).name(),
                         THEME_COLORS["ui_button_hover"])
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(triggered.count(), 1)

    def test_checkbox_menu_labels_align_with_plain_menu_labels(self):
        rows = []
        for checkbox in (False, True):
            menu = QMenu()
            self.addCleanup(menu.deleteLater)
            self.addCleanup(menu.close)
            menu.addAction("Rename bookmark")
            action = menu.addAction("Convert when shown in results")
            if checkbox:
                action.setCheckable(True)
                action.setChecked(True)
                style_checkbox_menu(menu, action)
            else:
                style_menu(menu)
            menu.popup(QPoint(100, 100))
            self.app.processEvents()
            menu.setActiveAction(None)
            image = menu.grab().toImage()
            scale = image.devicePixelRatio()
            rows.append([image.copy(0, round(menu.actionGeometry(item).top() * scale),
                                    round(100 * scale), round(menu.actionGeometry(item).height() * scale))
                         for item in menu.actions()])
            menu.close()
        self.assertEqual(rows[0], rows[1])
