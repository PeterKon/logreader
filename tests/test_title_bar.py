import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from logreader.ui.title_bar import create_title_menus


class TitleMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.menus = create_title_menus(self.window)
        self.window.setMenuBar(self.menus)
        self.window.resize(600, 200)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        for action in self.menus.actions():
            action.menu().close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_placeholder_menu_order_and_contents(self):
        self.assertEqual(
            [action.text().replace("&", "") for action in self.menus.actions()],
            ["File", "View", "Settings", "Profiles", "Help"],
        )
        for action in self.menus.actions():
            items = action.menu().actions()
            self.assertEqual([item.text() for item in items], ["Coming soon..."])
            self.assertFalse(items[0].isEnabled())

    def test_label_brightens_only_while_dropdown_is_open(self):
        self.window.statusBar().showMessage("Ready")
        action = self.menus.actions()[0]
        rect = self.menus.actionGeometry(action)

        def brightest_text():
            self.app.processEvents()
            image = self.menus.grab(rect).toImage()
            return max(
                image.pixelColor(x, y).red()
                for y in range(image.height()) for x in range(image.width())
            )

        QTest.mouseMove(self.window, QPoint(500, 100))
        self.assertLess(brightest_text(), 210)
        self.assertEqual(self.window.statusBar().currentMessage(), "Ready")
        QTest.mouseMove(self.menus, rect.center())
        self.assertFalse(action.menu().isVisible())
        self.assertLess(brightest_text(), 210)
        QTest.mouseClick(self.menus, Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertTrue(action.menu().isVisible())
        self.assertGreater(brightest_text(), 210)
        QTest.keyClick(action.menu(), Qt.Key.Key_Escape)
        self.assertFalse(action.menu().isVisible())
        self.assertLess(brightest_text(), 210)
        self.assertEqual(self.window.statusBar().currentMessage(), "Ready")
