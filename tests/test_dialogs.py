import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel

from qt_helpers import qt_application, retire_window
from logreader.ui.bookmarks import Bookmark, BookmarkNameDialog, BookmarkNotesDialog
from logreader.ui.dialogs import show_warning
from logreader.ui.filter_panel import PatternEditDialog
from logreader.ui.results.results_model import SourceLocation


class CompactDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def show(self, dialog):
        self.addCleanup(retire_window, dialog)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_custom_close_discards_each_editor_and_name_enter_accepts(self):
        source = SourceLocation("sample", 10)
        bookmark = Bookmark(source, "Original", note="Original note")
        for dialog in (
            BookmarkNameDialog("Rename bookmark", "Original"),
            BookmarkNotesDialog(bookmark, source),
            PatternEditDialog("original", is_regex=False, parent=None),
        ):
            with self.subTest(title=dialog.windowTitle()):
                self.show(dialog)
                dialog.editor.selectAll()
                QTest.keyClicks(dialog.editor, "Discarded")
                QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
                self.assertFalse(dialog.isVisible())
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertEqual(bookmark.note, "Original note")
        dialog = self.show(BookmarkNameDialog("Add bookmark", "Line 10"))
        QTest.keyClicks(dialog.editor, "New name")
        QTest.keyClick(dialog.editor, Qt.Key.Key_Return)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.editor.text(), "New name")

    def test_caption_and_edges_use_system_move_and_resize(self):
        dialog = self.show(PatternEditDialog("original", is_regex=False, parent=None))
        with patch.object(QWindow, "startSystemMove", return_value=True) as move, patch.object(
            QWindow, "startSystemResize", return_value=True,
        ) as resize:
            QTest.mouseClick(dialog.caption, Qt.MouseButton.LeftButton, pos=QPoint(100, 18))
            move.assert_called_once()
            QTest.mouseClick(dialog.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
            resize.assert_called_once_with(Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
        fixed = self.show(BookmarkNameDialog("Add bookmark", "Line 10"))
        with patch.object(QWindow, "startSystemResize", return_value=True) as resize:
            QTest.mouseClick(fixed.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
            resize.assert_not_called()

    def test_resize_cursors_stay_on_the_border(self):
        dialog = self.show(PatternEditDialog("original", is_regex=True, parent=None))
        dialog.resize(dialog.width() + 60, dialog.height() + 40)
        self.app.processEvents()
        width, height = dialog.width(), dialog.height()
        shape = Qt.CursorShape
        body = dialog.body_layout.parentWidget()
        blank = body.mapTo(dialog, QPoint(8, 8))
        viewport = dialog.editor.viewport()
        text = viewport.mapTo(dialog, viewport.rect().center())
        cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        button = cancel.mapTo(dialog, cancel.rect().center())

        def check_cursor(point, expected):
            QTest.mouseMove(dialog.windowHandle(), point)
            self.assertEqual(dialog.childAt(point).cursor().shape(), expected)

        for x, y, expected in (
            (0, height // 2, shape.SizeHorCursor), (width - 1, height // 2, shape.SizeHorCursor),
            (width // 2, 0, shape.SizeVerCursor), (width // 2, height - 1, shape.SizeVerCursor),
            (1, 1, shape.SizeFDiagCursor), (width - 2, 1, shape.SizeBDiagCursor),
            (1, height - 2, shape.SizeBDiagCursor), (width - 2, height - 2, shape.SizeFDiagCursor),
        ):
            with self.subTest(edge=(x, y)):
                check_cursor(QPoint(x, y), expected)
                check_cursor(blank, shape.ArrowCursor)
                check_cursor(text, shape.IBeamCursor)
                check_cursor(button, shape.ArrowCursor)

    def test_long_note_scrolls_without_moving_caption_or_actions(self):
        source = SourceLocation("sample", 12480)
        bookmark = Bookmark(source, "Long bookmark " * 12, note="A line of notes\n" * 50)
        dialog = self.show(BookmarkNotesDialog(bookmark, source))
        dialog.resize(dialog.minimumSize())
        self.app.processEvents()
        scrollbar = dialog.editor.verticalScrollBar()
        self.assertTrue(scrollbar.isVisible())
        self.assertGreater(scrollbar.maximum(), 0)
        caption = dialog.caption.geometry()
        actions = dialog.buttons.geometry()
        QTest.keyClick(dialog.editor, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(scrollbar.value(), 0)
        self.assertEqual(dialog.caption.geometry(), caption)
        self.assertEqual(dialog.buttons.geometry(), actions)
        self.assertLessEqual(dialog.editor.geometry().bottom(), dialog.body_layout.parentWidget().height())
        self.assertLess(dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).x(),
                        dialog.buttons.button(QDialogButtonBox.StandardButton.Save).x())

    def test_warning_is_plain_text_and_close_rejects(self):
        observed = []
        failures = []

        def dismiss():
            dialog = self.app.activeModalWidget()
            try:
                self.assertIsNotNone(dialog)
                observed.append(dialog.windowTitle())
                label = next(label for label in dialog.findChildren(QLabel) if label.text() == "Invalid <regex> & input")
                self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
                QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            except Exception as error:
                failures.append(error)
            finally:
                if dialog is not None:
                    dialog.close()

        QTimer.singleShot(0, dismiss)
        show_warning(None, "Invalid filters", "Invalid <regex> & input")
        if failures:
            raise failures[0]
        self.assertEqual(observed, ["Invalid filters"])
