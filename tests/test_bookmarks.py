import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QFont, QFontDatabase, QTextCursor, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QInputDialog, QLineEdit, QMenu, QStyle, QStyleOptionSlider, QTabBar, QToolTip

from qt_helpers import wait_for_search
from logreader.bookmarks import BookmarkDeletionDialog, BookmarkNotesDialog
from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.document_page import DocumentPage
from logreader.file_loader import LoadedLog
from logreader.input_menus import InputContextMenu
from logreader.results_model import SourceLocation
from logreader.results_view import ResultsView
from logreader.theme import THEME_COLORS


class BookmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists("C:/Windows/Fonts/consola.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    def setUp(self):
        self.view = ResultsView()
        self.view.resize(900, 550)
        for editor in (self.view.editor, self.view.source_view.editor):
            editor.setFont(QFont("Consolas", 11))
        self.view.show()
        self.addCleanup(QToolTip.hideText)
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)
        self.bookmarks = self.view.bookmarks

    def render(self, lines, config=None, *, load=True):
        config = config or LogreaderConfig(context=1, enabled_patterns=("error_colon",))
        if load:
            self.view.set_source(tuple(lines), 1000 + len(lines), snapshot_id="snapshot")
        analysis = analyze_lines(lines, config.search_patterns(),
                                 combined=config.combined_view, line_offset=1000)
        self.view.start_rendering(1, "sample.log", analysis, config)
        self.wait_render()

    def wait_render(self):
        for _ in range(2000):
            if not self.view.is_rendering:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.is_rendering)
        self.app.processEvents()

    def add(self, row=0, name="Important"):
        location = self.view.model.location(row)
        self.assertTrue(self.bookmarks.add(location, name))
        self.app.processEvents()
        return location

    def selected_row(self):
        return self.view._source_map.row(self.view.editor.textCursor().blockNumber())

    def test_menu_groups_bookmark_and_note_actions_for_both_bookmark_types(self):
        self.render(("ERROR: first", "plain source"),
                    LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        result = self.add()
        source = SourceLocation("snapshot", 1002)
        self.bookmarks.add(source, "Source")
        for location in (result, source):
            key = location if isinstance(location, SourceLocation) else location.source
            for note in ("", "Investigation note"):
                with self.subTest(source_only=isinstance(location, SourceLocation), note=note):
                    self.bookmarks.items[key].note = note
                    menu = QMenu(self.bookmarks.strip)
                    self.addCleanup(menu.deleteLater)
                    self.bookmarks.add_menu_actions(menu, location)
                    expected = ["Open note", "Delete note"] if note else ["Add note..."]
                    expected += [None, "Remove bookmark", "Rename bookmark"]
                    if isinstance(location, SourceLocation):
                        expected += [None, "Convert when shown in results"]
                        self.assertTrue(menu.actions()[-1].isCheckable())
                    self.assertEqual(
                        [None if action.isSeparator() else action.text() for action in menu.actions()],
                        expected,
                    )

    def test_notes_menu_adds_edits_cancels_and_clears_one_plain_text_note(self):
        self.render(("ERROR: first",))
        source = self.add().source
        expected = ""
        for label, text, accepted in (
                ("Add note...", "First line\n  <b>Plain text</b> & café 😀\n", True),
                ("Open note", "Replacement note", True),
                ("Open note", "Discard this", False),
                ("Open note", " \n  ", True)):
            with self.subTest(label=label, accepted=accepted):
                initial = []
                class TestDialog(BookmarkNotesDialog):
                    def exec(self):
                        initial.append(self.editor.toPlainText())
                        self.editor.setPlainText(text)
                        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
                menu = QMenu()
                self.bookmarks.add_menu_actions(menu, source)
                with patch("logreader.bookmarks.BookmarkNotesDialog", TestDialog), patch(
                        "logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=QDialog.DialogCode.Accepted):
                    next(a for a in menu.actions() if a.text() == label).trigger()
                self.assertEqual(initial, [expected])
                if accepted:
                    expected = text if text.strip() else ""
                self.assertEqual(self.bookmarks.items[source].note, expected)
                self.assertEqual(len(self.bookmarks.items), 1)
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        self.assertIn("Add note...", [a.text() for a in menu.actions()])

    def test_notes_dialog_accepts_newlines_and_has_save_and_cancel(self):
        self.render(("ERROR: first",))
        source = self.add().source
        for save in (True, False):
            with self.subTest(save=save):
                dialog = BookmarkNotesDialog(self.bookmarks.items[source], source, self.view)
                self.addCleanup(dialog.deleteLater)
                self.addCleanup(dialog.close)
                dialog.show()
                self.app.processEvents()
                QTest.keyClicks(dialog.editor, "First")
                QTest.keyClick(dialog.editor, Qt.Key.Key_Return)
                QTest.keyClicks(dialog.editor, "Second")
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.editor.toPlainText(), "First\nSecond")
                button = QDialogButtonBox.StandardButton.Save if save else QDialogButtonBox.StandardButton.Cancel
                QTest.mouseClick(dialog.buttons.button(button), Qt.MouseButton.LeftButton)
                self.assertFalse(dialog.isVisible())
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted if save else QDialog.DialogCode.Rejected)

    def test_notes_survive_reorder_rename_conversion_and_reanalysis(self):
        lines = ("context", "ERROR: first")
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        self.add(0, "Other")
        source = SourceLocation("snapshot", 1001)
        self.bookmarks.add(source, "Source")
        bookmark = self.bookmarks.items[source]
        class TestDialog(BookmarkNotesDialog):
            def exec(self):
                self.editor.setPlainText("Keep this note\nThrough re-analysis")
                return QDialog.DialogCode.Accepted
        class TestMenu(QMenu):
            def exec(self, *args):
                next(a for a in self.actions() if a.text() == "Add note...").trigger()
        strip = self.bookmarks.strip
        with patch("logreader.bookmarks.QMenu", TestMenu), patch("logreader.bookmarks.BookmarkNotesDialog", TestDialog):
            strip.customContextMenuRequested.emit(strip.tabRect(1).center())
        self.bookmarks.reorder()
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=("Renamed", True)):
            self.bookmarks.rename(source)
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        next(a for a in menu.actions() if a.isCheckable()).trigger()
        self.render(lines, replace(config, context=1), load=False)
        self.assertFalse(bookmark.source_only)
        self.render(lines, config, load=False)
        self.assertTrue(bookmark.converted)
        self.assertEqual(bookmark.note, "Keep this note\nThrough re-analysis")
        self.assertEqual(bookmark.name, "Renamed")
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        self.assertIn("Open note", [a.text() for a in menu.actions()])

    def test_notes_dialog_cannot_save_to_a_replaced_bookmark(self):
        self.render(("ERROR: first",))
        source = self.add().source
        bookmarks = self.bookmarks
        class TestDialog(BookmarkNotesDialog):
            def exec(self):
                self.editor.setPlainText("Stale note")
                bookmarks.remove(source)
                bookmarks.add(source, "Replacement bookmark")
                return QDialog.DialogCode.Accepted
        with patch("logreader.bookmarks.BookmarkNotesDialog", TestDialog):
            bookmarks.edit_notes(source)
        self.assertEqual(bookmarks.items[source].note, "")

    def test_note_preview_collapses_whitespace_and_truncates_without_shortening_saved_note(self):
        self.render(("ERROR: first",))
        source = self.add().source
        bookmark = self.bookmarks.items[source]
        for note, expected in (
                ("First line\n\n  Second\tline ", "First line Second line"),
                ("x" * 160, "x" * 160),
                ("x" * 161, "x" * 159 + "…"),
                ("word " * 50, " ".join(["word"] * 32) + "…")):
            with self.subTest(note=note):
                bookmark.note = note
                self.bookmarks.refresh()
                self.assertEqual(bookmark.note_preview, expected)
                self.assertLessEqual(len(bookmark.note_preview), 160)
                self.assertNotIn("\n", bookmark.note_preview)
                self.assertTrue(self.bookmarks.strip.tabToolTip(0).endswith("\n\nNote: " + expected))
                self.assertEqual(bookmark.note, note)
        original = "Full note, including all lines:\n" + "Long note content. " * 100
        bookmark.note = original
        self.bookmarks.refresh()
        shown = []
        class TestDialog(BookmarkNotesDialog):
            def exec(self):
                shown.append(self.editor.toPlainText())
                return QDialog.DialogCode.Accepted
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        with patch("logreader.bookmarks.BookmarkNotesDialog", TestDialog):
            next(a for a in menu.actions() if a.text() == "Open note").trigger()
        self.assertEqual(shown, [original])
        self.assertEqual(bookmark.note, original)

    def test_delete_note_removes_preview_and_icon_but_keeps_bookmark(self):
        self.render(("ERROR: first",))
        source = self.add().source
        bookmark = self.bookmarks.items[source]
        bookmark.note = "A note to delete"
        self.bookmarks.refresh()
        strip = self.bookmarks.strip
        self.assertIsNotNone(strip.tabButton(0, QTabBar.ButtonPosition.RightSide))
        menu = QMenu(strip)
        self.addCleanup(menu.deleteLater)
        self.addCleanup(menu.close)
        self.bookmarks.add_menu_actions(menu, source)
        self.assertEqual([a.text() for a in menu.actions()],
                         ["Open note", "Delete note", "", "Remove bookmark", "Rename bookmark"])
        delete = next(a for a in menu.actions() if a.text() == "Delete note")
        menu.popup(strip.mapToGlobal(strip.rect().bottomLeft()))
        self.app.processEvents()
        with patch("logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=QDialog.DialogCode.Accepted):
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(delete).center())
        self.assertFalse(menu.isVisible())
        self.assertIs(self.bookmarks.items[source], bookmark)
        self.assertEqual(bookmark.note, "")
        self.assertNotIn("Note:", strip.tabToolTip(0))
        self.assertIsNone(strip.tabButton(0, QTabBar.ButtonPosition.RightSide))
        reopened = QMenu()
        self.bookmarks.add_menu_actions(reopened, source)
        self.assertEqual([a.text() for a in reopened.actions()],
                         ["Add note...", "", "Remove bookmark", "Rename bookmark"])

    def test_deletion_confirmation_requires_yes_and_describes_what_will_be_deleted(self):
        self.render(("ERROR: first",))
        for note_only, note, warning in (
                (True, "Keep my note", "This will delete the note."),
                (False, "", "This will remove the bookmark."),
                (False, "Keep my note", "This will remove the bookmark and delete its note.")):
            for response in ("no", "escape", "close", "enter", "yes"):
                with self.subTest(note_only=note_only, note=note, response=response):
                    self.bookmarks.clear()
                    source = self.add(name="A < B").source
                    bookmark = self.bookmarks.items[source]
                    bookmark.note = note
                    self.bookmarks.refresh()
                    observed = []

                    class TestDeletionDialog(BookmarkDeletionDialog):
                        def exec(dialog):
                            observed.append((dialog.windowTitle(), dialog.message.text(), dialog.target.text(),
                                             dialog.buttons.button(QDialogButtonBox.StandardButton.No).isDefault(),
                                             dialog.message.textFormat()))

                            def respond():
                                if response == "close":
                                    dialog.close()
                                elif response in ("enter", "escape"):
                                    QTest.keyClick(dialog, Qt.Key.Key_Return if response == "enter"
                                                   else Qt.Key.Key_Escape)
                                else:
                                    button = QDialogButtonBox.StandardButton.Yes if response == "yes" else QDialogButtonBox.StandardButton.No
                                    QTest.mouseClick(dialog.buttons.button(button), Qt.MouseButton.LeftButton)

                            QTimer.singleShot(0, respond)
                            return super().exec()

                    with patch("logreader.bookmarks.BookmarkDeletionDialog", TestDeletionDialog):
                        if note_only:
                            self.bookmarks.delete_note(source)
                        else:
                            self.bookmarks.request_remove(source)
                    self.assertEqual(len(observed), 1)
                    title, message, details, default, text_format = observed[0]
                    self.assertEqual(title, "Delete note" if note_only else "Remove bookmark")
                    self.assertEqual(message, warning)
                    self.assertEqual(details, "A < B (Line 1,001)")
                    self.assertTrue(default)
                    self.assertEqual(text_format, Qt.TextFormat.PlainText)
                    if response == "yes" and not note_only:
                        self.assertNotIn(source, self.bookmarks.items)
                    else:
                        self.assertIs(self.bookmarks.items[source], bookmark)
                        self.assertEqual(bookmark.note, "" if response == "yes" else note)

    def test_saving_an_empty_note_also_requires_confirmation(self):
        self.render(("ERROR: first",))
        source = self.add().source

        class EmptyNoteDialog(BookmarkNotesDialog):
            def exec(dialog):
                dialog.editor.setPlainText(" \n ")
                return QDialog.DialogCode.Accepted

        for answer in (QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted):
            self.bookmarks.items[source].note = "Keep this note"
            with patch("logreader.bookmarks.BookmarkNotesDialog", EmptyNoteDialog), patch(
                    "logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=answer) as confirmation:
                self.bookmarks.edit_notes(source)
            confirmation.assert_called_once()
            self.assertEqual(self.bookmarks.items[source].note,
                             "" if answer == QDialog.DialogCode.Accepted else "Keep this note")

    def test_confirmation_cannot_delete_a_replacement_bookmark_or_its_note(self):
        self.render(("ERROR: first",))
        for note_only in (False, True):
            with self.subTest(note_only=note_only):
                self.bookmarks.clear()
                source = self.add().source
                self.bookmarks.items[source].note = "Original"
                bookmarks = self.bookmarks

                class TestDeletionDialog(BookmarkDeletionDialog):
                    def exec(dialog):
                        bookmarks.remove(source)
                        bookmarks.add(source, "Replacement")
                        bookmarks.items[source].note = "Replacement note"
                        return QDialog.DialogCode.Accepted

                with patch("logreader.bookmarks.BookmarkDeletionDialog", TestDeletionDialog):
                    if note_only:
                        bookmarks.delete_note(source)
                    else:
                        bookmarks.request_remove(source)
                self.assertEqual(bookmarks.items[source].name, "Replacement")
                self.assertEqual(bookmarks.items[source].note, "Replacement note")

    def test_note_icons_stay_on_the_right_and_follow_bookmark_type_and_reordering(self):
        lines = ("ERROR: first", "ERROR: second", "source")
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        converted = self.add(1, "Converted").source
        full = self.add(0, "Result").source
        source = SourceLocation("snapshot", 1003)
        self.bookmarks.add(source, "Source")
        for bookmark in self.bookmarks.items.values():
            bookmark.note = "First line\nSecond line"
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("first",)), load=False)
        self.bookmarks.reorder()
        self.app.processEvents()
        strip = self.bookmarks.strip
        for index, location in enumerate((full, converted, source)):
            icon = strip.tabButton(index, QTabBar.ButtonPosition.RightSide)
            self.assertIsNotNone(icon)
            self.assertTrue(icon.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertGreater(icon.geometry().center().x(), strip.tabRect(index).center().x())
            self.assertLess(icon.geometry().right(), strip.tabRect(index).right())
            self.assertEqual(icon.color.name(), THEME_COLORS["bookmark_note"])
            self.assertTrue(strip.tabToolTip(index).endswith("Note: First line Second line"))
        self.assertEqual(strip.tabText(1), "(c) Converted")
        self.assertLessEqual(self.bookmarks.bar.height(), 30)

    def test_bookmark_scrollbar_pips_take_precedence_over_search_in_both_views(self):
        lines = tuple(f"ERROR: {i}" + (" needle" if i in (100, 300) else "") for i in range(400))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        self.add(0)
        self.add(100)
        self.add(200)
        self.bookmarks.add(SourceLocation("snapshot", 1351), "Source only")
        for source_active in (False, True):
            with self.subTest(source_active=source_active):
                self.view.set_source_active(source_active)
                editor = self.view.source_view.editor if source_active else self.view.editor
                scrollbar = editor.verticalScrollBar()
                self.view._search_input.setText("needle")
                self.view.search_results()
                for _ in range(1000):
                    if (not self.view.is_searching and not self.view.source_view.is_searching
                            and self.view.source_view._page_work is None):
                        break
                    QTest.qWait(5)
                self.assertFalse(self.view.is_searching)
                self.assertFalse(self.view.source_view.is_searching)
                scrollbar.setValue(0)
                self.app.processEvents()
                self.assertEqual(scrollbar._bookmark_blocks.tolist(), sorted(editor._bookmark_blocks))
                self.assertEqual(len(scrollbar._bookmark_blocks), 4 if source_active else 3)
                option = QStyleOptionSlider()
                scrollbar.initStyleOption(option)
                groove = scrollbar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                                         QStyle.SubControl.SC_ScrollBarGroove, scrollbar)
                slider = scrollbar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                                         QStyle.SubControl.SC_ScrollBarSlider, scrollbar)
                bookmarks = scrollbar._marker_rows_for_groove(groove, bookmarks=True)
                search = scrollbar._marker_rows_for_groove(groove)
                overlap = set(bookmarks) & set(search)
                self.assertTrue(overlap)
                self.assertTrue(any(slider.top() <= row <= slider.bottom() for row in bookmarks))
                image = scrollbar.grab().toImage()
                for row in overlap:
                    self.assertFalse(slider.top() <= row <= slider.bottom())
                    self.assertEqual(image.pixelColor(groove.left() + 2, row).name(), THEME_COLORS["bookmark_marker"])
                    self.assertEqual(image.pixelColor(groove.right() - 2, row).name(), THEME_COLORS["bookmark_marker"])
                for row in set(bookmarks) - set(search):
                    if slider.top() <= row <= slider.bottom():
                        self.assertNotEqual(image.pixelColor(groove.center().x(), row).name(), THEME_COLORS["bookmark_marker"])
                    else:
                        self.assertEqual(image.pixelColor(groove.center().x(), row).name(), THEME_COLORS["bookmark_marker"])
                self.view._search_input.clear()
                self.assertFalse(scrollbar._match_blocks)
                self.assertEqual(scrollbar._marker_rows_for_groove(groove, bookmarks=True), bookmarks)
                image = scrollbar.grab().toImage()
                for row in bookmarks:
                    if not slider.top() <= row <= slider.bottom():
                        self.assertEqual(image.pixelColor(groove.center().x(), row).name(), THEME_COLORS["bookmark_marker"])
        self.bookmarks.clear()
        for editor in (self.view.editor, self.view.source_view.editor):
            self.assertFalse(editor.verticalScrollBar()._bookmark_blocks)

    def test_bookmark_scrollbar_pips_follow_wrapping_and_resize(self):
        lines = tuple("ERROR: " + ("long line " * 400 if i == 100 else str(i)) for i in range(201))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        for row in (20, 100, 180):
            self.add(row)
        for source_active in (False, True):
            self.view.set_source_active(source_active)
            self.view.set_line_wrapping(True)
            self.bookmarks.activate(SourceLocation("snapshot", 1101))
            editor = self.view.source_view.editor if source_active else self.view.editor
            for width in (900, 700):
                with self.subTest(source_active=source_active, width=width):
                    self.view.resize(width, 400)
                    self.app.processEvents()
                    editor.ensureCursorVisible()
                    self.app.processEvents()
                    scrollbar = editor.verticalScrollBar()
                    option = QStyleOptionSlider()
                    scrollbar.initStyleOption(option)
                    groove = scrollbar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                                             QStyle.SubControl.SC_ScrollBarGroove, scrollbar)
                    extent = scrollbar.maximum() + scrollbar.pageStep()
                    self.assertGreater(extent, editor.blockCount())
                    expected = tuple(sorted({groove.top() + editor.document().findBlockByNumber(block).firstLineNumber()
                                             * (groove.height() - 1) // (extent - 1)
                                             for block in editor._bookmark_blocks}))
                    self.assertEqual(scrollbar._marker_rows_for_groove(groove, bookmarks=True), expected)

    def test_bookmark_scrollbar_pips_update_on_reanalysis_removal_and_source_replacement(self):
        lines = tuple(f"ERROR: {i}" for i in range(100))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        location = self.add(50)
        scrollbar = self.view.editor.verticalScrollBar()
        before = scrollbar._bookmark_blocks[0]
        self.view.prepend_performance_timings(.1, .2)
        self.assertGreater(scrollbar._bookmark_blocks[0], before)
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("absent",)), load=False)
        self.assertFalse(scrollbar._bookmark_blocks)
        self.view.set_source_active(True)
        self.assertEqual(self.view.source_view.marker._bookmark_blocks.tolist(), [50])
        self.bookmarks.remove(location.source)
        self.assertFalse(self.view.source_view.marker._bookmark_blocks)
        self.bookmarks.add(location.source, "Source only")
        self.view.set_source(("replacement",), 1, snapshot_id="replacement")
        self.assertFalse(scrollbar._bookmark_blocks)
        self.assertFalse(self.view.source_view.marker._bookmark_blocks)

    def test_reorder_sorts_all_bookmark_types_without_changing_selection_or_metadata(self):
        lines = tuple(f"ERROR: {i}" for i in range(80))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        full = self.add(50, "Later result").source
        native = SourceLocation("snapshot", 1001)
        self.bookmarks.add(native, "Earlier source")
        converted = self.add(20, "Middle converted").source
        analysis = analyze_lines(lines[-40:], config.search_patterns(), line_offset=1040)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.wait_render()
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, native)
        next(a for a in menu.actions() if a.isCheckable()).trigger()
        strip = self.bookmarks.strip
        button = self.bookmarks.reorder_button
        self.assertEqual(button.text(), "Reorder")
        self.assertEqual(button.toolTip(), "Sort bookmarks by the order they appear in source.")
        self.assertEqual(list(self.bookmarks.items), [full, native, converted])
        for source_active in (False, True):
            self.view.set_source_active(source_active)
            self.bookmarks.activate(full)
            editor = self.view.source_view.editor if source_active else self.view.editor
            position = editor.textCursor().position()
            scroll = editor.verticalScrollBar().value()
            before = {source: (bookmark.location, bookmark.name, bookmark.converted,
                               bookmark.convert_when_shown, strip.tabText(index), strip.tabToolTip(index),
                               strip.tabTextColor(index))
                      for index, (source, bookmark) in enumerate(self.bookmarks.items.items())}
            activated = QSignalSpy(strip.activated)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.assertEqual(list(self.bookmarks.items), [native, converted, full])
            self.assertEqual([strip.tabData(i) for i in range(strip.count())], [native, converted, full])
            self.assertEqual(strip.tabData(strip.currentIndex()), full)
            self.assertEqual(activated.count(), 0)
            self.assertEqual(editor.textCursor().position(), position)
            self.assertEqual(editor.verticalScrollBar().value(), scroll)
            for index, (source, bookmark) in enumerate(self.bookmarks.items.items()):
                self.assertEqual((bookmark.location, bookmark.name, bookmark.converted,
                                  bookmark.convert_when_shown, strip.tabText(index), strip.tabToolTip(index),
                                  strip.tabTextColor(index)),
                                 before[source])
        added = SourceLocation("snapshot", 1002)
        self.bookmarks.add(added, "Added later")
        self.assertEqual([strip.tabData(i) for i in range(strip.count())], [native, converted, full, added])
        self.bookmarks.refresh()
        self.assertEqual(list(self.bookmarks.items), [native, converted, full, added])

    def test_reorder_button_visibility_and_position_with_overflow(self):
        self.assertTrue(self.bookmarks.bar.isHidden())
        self.render(tuple(f"ERROR: {i}" for i in range(40)))
        self.add(39, "Last bookmark")
        self.assertTrue(self.bookmarks.bar.isVisible())
        self.assertFalse(self.bookmarks.reorder_button.isEnabled())
        for row in reversed(range(30)):
            self.add(row, f"Bookmark {row}: a long name")
        self.view.resize(700, 500)
        self.app.processEvents()
        strip = self.bookmarks.strip
        button = self.bookmarks.reorder_button
        self.assertTrue(button.isEnabled())
        self.assertTrue(button.isVisible())
        self.assertEqual(button.geometry().right(), self.bookmarks.bar.rect().right())
        self.assertLess(strip.geometry().right(), button.geometry().left())
        self.assertLessEqual(self.bookmarks.bar.height(), 30)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual([strip.tabData(i).line for i in range(strip.count())],
                         list(range(1001, 1031)) + [1040])
        self.bookmarks.clear()
        self.assertTrue(self.bookmarks.bar.isHidden())

    def test_source_menu_adds_renames_and_removes_without_analysis(self):
        self.view.set_source(("before", "", "after"), 1003, snapshot_id="source")
        self.view.set_source_active(True)
        self.app.processEvents()
        editor = self.view.source_view.editor
        block = editor.document().findBlockByNumber(1)
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        point = QPoint(10, round(rect.top()) + 4)
        source = SourceLocation("source", 1002)
        self.assertEqual(self.view.source_location_at(point), source)
        self.assertIsNone(self.view.source_location_at(QPoint(10, editor.viewport().height() - 5)))

        for action, name in (("Add bookmark", "Blank line"),
                             ("Rename bookmark", "Renamed"), ("Remove bookmark", None)):
            class TestMenu(QMenu):
                def exec(self, *args):
                    next(a for a in self.actions() if a.text() == action).trigger()
            with patch.object(editor, "createStandardContextMenu", side_effect=TestMenu), patch(
                    "logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=(name, True)), patch(
                    "logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=QDialog.DialogCode.Accepted):
                # Exercise both the text and line-number context menus.
                if action == "Rename bookmark":
                    editor.gutter.customContextMenuRequested.emit(QPoint(2, point.y()))
                else:
                    editor.customContextMenuRequested.emit(point)
            if name is not None:
                self.assertEqual(self.bookmarks.items[source].name, name)
                self.assertEqual(self.bookmarks.items[source].location, source)
                self.assertEqual(self.bookmarks.strip.tabText(0), name)
                self.assertEqual(editor._bookmark_blocks, {1: True})
        self.assertFalse(self.bookmarks.items)
        self.assertFalse(editor._bookmark_blocks)

    def test_source_only_bookmark_stays_in_source_after_reanalysis(self):
        lines = ("ERROR: first", "ERROR: second")
        self.render(lines)
        location = self.view.model.location(1)
        self.assertTrue(self.bookmarks.add(location.source, "Source only"))
        self.assertFalse(self.bookmarks.add(location, "Duplicate"))
        for _ in range(2):
            self.assertFalse(self.view.editor._bookmark_blocks)
            self.bookmarks.activate(location.source)
            self.assertFalse(self.view.source_active)
            self.view.set_source_active(True)
            self.bookmarks.activate(location.source)
            self.assertTrue(self.view.source_active)
            self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 1)
            self.assertEqual(self.bookmarks.strip.tabText(0), "Source only")
            self.assertNotIn("Converted", self.bookmarks.strip.tabToolTip(0))
            self.view.set_source_active(False)
            self.render(lines, load=False)
        self.assertEqual(self.bookmarks.items[location.source].location, location.source)

    def test_source_only_bookmark_can_be_added_and_opened_during_rendering(self):
        lines = tuple(f"ERROR: {i}" for i in range(50))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        analysis = analyze_lines(lines, config.search_patterns(), line_offset=1000)
        self.view.start_rendering(2, "sample.log", analysis, config)
        source = SourceLocation("snapshot", 1010)
        self.assertTrue(self.bookmarks.add(source, "During analysis"))
        self.assertTrue(self.bookmarks.strip.isTabEnabled(0))
        self.bookmarks.activate(source)
        self.assertFalse(self.view.source_active)
        self.view.set_source_active(True)
        self.bookmarks.activate(source)
        self.assertTrue(self.view.source_active)
        self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 9)
        self.wait_render()
        self.assertTrue(self.bookmarks.items[source].source_only)
        self.assertFalse(self.bookmarks.items[source].converted)

    def test_source_only_bookmark_rejects_stale_dialog_and_unretained_lines(self):
        self.view.set_source(("old",), 1001, snapshot_id="old")
        source = SourceLocation("old", 1001)
        self.assertFalse(self.bookmarks.add(SourceLocation("old", 1000), "Not retained"))
        self.assertFalse(self.bookmarks.add(SourceLocation("old", 1002), "Past end"))
        def changed_source(*args):
            self.view.set_source(("new",), 1001, snapshot_id="new")
            return "Stale", True
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", side_effect=changed_source):
            self.bookmarks.prompt(source)
        self.assertFalse(self.bookmarks.items)

    @patch("logreader.source_view.SOURCE_PAGE_LINES", 10_000)
    def test_source_only_bookmark_tracks_line_numbers_across_pages(self):
        self.view.set_source(tuple(str(i) for i in range(12000)), 13000, snapshot_id="source")
        self.view.set_source_active(True)
        source = SourceLocation("source", 12001)
        self.assertTrue(self.bookmarks.add(source, "Later page"))
        self.bookmarks.activate(source)
        editor = self.view.source_view.editor
        self.assertEqual(editor.source_number(editor.textCursor().blockNumber()), source.line)
        self.assertEqual(self.view.source_location_at(editor.cursorRect().center()), source)
        self.view.source_view.first_page()
        self.assertFalse(editor._bookmark_blocks)
        self.assertFalse(self.view.source_view.marker._bookmark_blocks)
        self.bookmarks.activate(source)
        self.assertEqual(editor._bookmark_blocks, {editor.textCursor().blockNumber(): True})
        self.assertEqual(self.view.source_view.marker._bookmark_blocks.tolist(), [editor.textCursor().blockNumber()])

    def test_bookmark_types_render_distinct_text_with_shared_background_and_borders(self):
        from logreader.qt_app import INTERFACE_STYLE_SHEET
        self.view.setStyleSheet(INTERFACE_STYLE_SHEET)
        self.render(("ERROR: first", "ERROR: second", "plain source"),
                    LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        self.add(0, "Results bookmark")
        self.add(1, "Converted bookmark")
        self.bookmarks.add(SourceLocation("snapshot", 1003), "Source bookmark")
        self.render(("ERROR: first", "ERROR: second", "plain source"),
                    LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("first",)),
                    load=False)
        strip = self.bookmarks.strip
        self.app.processEvents()
        image = strip.grab().toImage()
        for index, role in enumerate(("bookmark_text", "bookmark_source_text", "bookmark_source_text")):
            rect = strip.tabRect(index)
            colors = {image.pixelColor(x, y).name()
                      for x in range(rect.left() + 2, rect.right() - 2)
                      for y in range(rect.top() + 2, rect.bottom() - 2)}
            self.assertIn(THEME_COLORS[role], colors)
            self.assertEqual(image.pixelColor(rect.left() + 2, rect.top() + 2).name(), "#0d1117")
            self.assertEqual(image.pixelColor(rect.right(), rect.center().y()).name(), "#2b2513")
            self.assertEqual(image.pixelColor(rect.center().x(), rect.bottom()).name(), "#473d21")
        self.assertEqual(strip.tabText(1), "(c) Converted bookmark")
        self.assertEqual(strip.tabText(2), "Source bookmark")

    def test_source_bookmark_click_shows_tooltip_without_leaving_results(self):
        self.render(("ERROR: first", "ERROR: second", "plain source"),
                    LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        self.add(1, "Converted")
        self.bookmarks.add(SourceLocation("snapshot", 1003), "Source")
        self.render(("ERROR: first", "ERROR: second", "plain source"),
                    LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("first",)),
                    load=False)
        strip = self.bookmarks.strip
        editor = self.view.editor
        position = editor.textCursor().position()
        scroll = editor.verticalScrollBar().value()
        for index in range(strip.count()):
            with self.subTest(index=index):
                QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.tabRect(index).center())
                QTest.qWait(400)
                self.assertFalse(self.view.source_active)
                self.assertEqual(editor.textCursor().position(), position)
                self.assertEqual(editor.verticalScrollBar().value(), scroll)
                self.assertTrue(QToolTip.isVisible())
                self.assertEqual(QToolTip.text(), strip.tabToolTip(index))
                self.assertTrue(QToolTip.text().startswith("Source-only bookmark\nLine "))

    def test_default_bookmark_tooltips_show_the_line_number_once(self):
        lines = ("ERROR: first", "ERROR: second", "plain source")
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        self.add(0, "")
        self.add(1, "")
        self.bookmarks.add(SourceLocation("snapshot", 1003), "")
        self.assertEqual(self.bookmarks.strip.tabToolTip(0), "Line 1,001\nOpen this line in results.")
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("first",)),
                    load=False)
        for index, number in enumerate(("1,001", "1,002", "1,003")):
            self.assertEqual(self.bookmarks.strip.tabToolTip(index).count(number), 1)
        self.assertEqual(self.bookmarks.strip.tabToolTip(2), "Source-only bookmark\nLine 1,003")
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=("Connection", True)):
            self.bookmarks.rename(SourceLocation("snapshot", 1001))
        self.assertEqual(self.bookmarks.strip.tabToolTip(0),
                         "Connection\nLine 1,001\nOpen this line in results.")

    def test_source_conversion_waits_for_completed_results_and_prefers_a_match(self):
        lines = ("context needle", "ERROR: failure", "after")
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        source = SourceLocation("snapshot", 1001)
        self.bookmarks.add(source, "Keep this name")
        strip = self.bookmarks.strip
        checked = []

        class TestMenu(QMenu):
            def exec(self, *args):
                action = next(a for a in self.actions() if a.text() == "Convert when shown in results")
                checked.append(action.isChecked())
                action.trigger()

        with patch("logreader.bookmarks.QMenu", TestMenu):
            strip.customContextMenuRequested.emit(strip.tabRect(0).center())
        self.assertEqual(checked, [False])
        self.assertTrue(self.bookmarks.items[source].convert_when_shown)
        self.assertTrue(self.bookmarks.items[source].source_only)
        self.assertFalse(self.view.editor._bookmark_blocks)

        config = LogreaderConfig(context=1, combined_view=False, enabled_patterns=("error_colon",),
                                 custom_patterns=("needle",))
        analysis = analyze_lines(lines, config.search_patterns(), combined=False, line_offset=1000)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.assertTrue(self.bookmarks.items[source].source_only)
        self.wait_render()
        bookmark = self.bookmarks.items[source]
        self.assertFalse(bookmark.source_only)
        self.assertFalse(bookmark.converted)
        self.assertEqual(strip.tabText(0), "Keep this name")
        self.assertEqual(strip.tabTextColor(0).name(), THEME_COLORS["bookmark_text"])
        rows = self.view.model.rows_for_source(source)
        self.assertFalse(self.view.model.line(rows[0]).is_match)
        self.assertTrue(self.view.model.line(self.view.model.resolve(bookmark.location)).is_match)
        self.bookmarks.activate(source)
        self.assertFalse(self.view.source_active)
        self.assertEqual(self.selected_row(), self.view.model.resolve(bookmark.location))

    def test_conversion_toggle_can_be_disabled_and_only_appears_for_native_source_bookmarks(self):
        lines = ("context needle", "ERROR: failure", "after")
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        source = SourceLocation("snapshot", 1001)
        full = self.add(0).source
        self.bookmarks.add(source, "Source")
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        toggle = next(a for a in menu.actions() if a.text() == "Convert when shown in results")
        self.assertTrue(toggle.isCheckable())
        self.assertFalse(toggle.isChecked())
        toggle.trigger()
        reopened = QMenu()
        self.bookmarks.add_menu_actions(reopened, source)
        saved_toggle = next(a for a in reopened.actions() if a.isCheckable())
        self.assertTrue(saved_toggle.isChecked())
        saved_toggle.trigger()
        self.assertFalse(self.bookmarks.items[source].convert_when_shown)
        full_menu = QMenu()
        self.bookmarks.add_menu_actions(full_menu, full)
        self.assertFalse(any(a.isCheckable() for a in full_menu.actions()))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("needle",)),
                    load=False)
        self.assertTrue(self.bookmarks.items[source].source_only)
        self.assertTrue(self.bookmarks.items[full].converted)
        converted_menu = QMenu()
        self.bookmarks.add_menu_actions(converted_menu, full)
        self.assertFalse(any(a.isCheckable() for a in converted_menu.actions()))

    def test_enabling_conversion_for_an_existing_result_converts_immediately(self):
        self.render(("context", "ERROR: first"))
        for row in (0, 1):
            with self.subTest(row=row):
                source = self.view.model.location(row).source
                self.bookmarks.add(source, "Source")
                menu = QMenu()
                self.bookmarks.add_menu_actions(menu, source)
                next(a for a in menu.actions() if a.isCheckable()).trigger()
                self.assertFalse(self.bookmarks.items[source].source_only)
                self.assertEqual(self.bookmarks.items[source].location, self.view.model.location(row))

    def test_conversion_toggle_keeps_menu_open_but_other_actions_close_it(self):
        self.view.set_source(("plain source",), 1, snapshot_id="source")
        source = SourceLocation("source", 1)
        self.bookmarks.add(source, "Source")
        menu = QMenu(self.bookmarks.strip)
        self.addCleanup(menu.deleteLater)
        self.addCleanup(menu.close)
        self.bookmarks.add_menu_actions(menu, source)
        toggle = next(a for a in menu.actions() if a.isCheckable())
        menu.popup(self.bookmarks.strip.mapToGlobal(self.bookmarks.strip.rect().bottomLeft()))
        self.app.processEvents()
        for checked in (True, False):
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(toggle).center())
            self.assertTrue(menu.isVisible())
            self.assertEqual(toggle.isChecked(), checked)
            self.assertEqual(self.bookmarks.items[source].convert_when_shown, checked)
        menu.setActiveAction(toggle)
        for key, checked in ((Qt.Key.Key_Space, True), (Qt.Key.Key_Return, False)):
            QTest.keyClick(menu, key)
            self.assertTrue(menu.isVisible())
            self.assertEqual(toggle.isChecked(), checked)
            self.assertEqual(self.bookmarks.items[source].convert_when_shown, checked)

        rename = next(a for a in menu.actions() if a.text() == "Rename bookmark")
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=("Renamed", True)):
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(rename).center())
        self.assertFalse(menu.isVisible())
        self.assertEqual(self.bookmarks.items[source].name, "Renamed")
        menu.popup(self.bookmarks.strip.mapToGlobal(self.bookmarks.strip.rect().bottomLeft()))
        self.app.processEvents()
        remove = next(a for a in menu.actions() if a.text() == "Remove bookmark")
        with patch("logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=QDialog.DialogCode.Accepted):
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(remove).center())
        self.assertFalse(menu.isVisible())
        self.assertFalse(self.bookmarks.items)

    def test_context_conversion_chooses_first_occurrence_and_follows_full_bookmark_lifecycle(self):
        lines = ("context", "ERROR: failure", "after")
        config = LogreaderConfig(context=0, combined_view=False, enabled_patterns=("error_colon",),
                                 custom_patterns=("failure",))
        self.render(lines, config)
        source = SourceLocation("snapshot", 1001)
        self.bookmarks.add(source, "Context bookmark")
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, source)
        next(a for a in menu.actions() if a.isCheckable()).trigger()
        bookmark = self.bookmarks.items[source]
        self.assertTrue(bookmark.source_only)
        with_context = replace(config, context=1)
        analysis = analyze_lines(lines, with_context.search_patterns(), combined=False, line_offset=1000)
        self.view.start_rendering(2, "sample.log", analysis, with_context)
        self.assertTrue(bookmark.source_only)
        self.wait_render()
        rows = self.view.model.rows_for_source(source)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not self.view.model.line(row).is_match for row in rows))
        self.assertEqual(bookmark.location, self.view.model.location(rows[0]))
        self.assertFalse(bookmark.source_only)
        self.bookmarks.activate(source)
        self.assertEqual(self.selected_row(), rows[0])
        location = bookmark.location
        self.render(lines, config, load=False)
        self.assertTrue(bookmark.source_only)
        self.assertTrue(bookmark.converted)
        self.assertEqual(self.bookmarks.strip.tabText(0), "(c) Context bookmark")
        self.render(lines, with_context, load=False)
        self.assertFalse(bookmark.source_only)
        self.assertEqual(bookmark.location, location)
        self.assertEqual(self.bookmarks.strip.tabText(0), "Context bookmark")

    def test_name_dialog_menus_preserve_editing_accept_and_cancel_for_both_types(self):
        self.render(("ERROR: needle",))
        result_location = self.view.model.location(0)
        for location in (result_location, result_location.source):
            self.bookmarks.clear()
            for title, initial, name, accept in (
                ("Add bookmark", "Line 1,001", "First", True),
                ("Rename bookmark", "First", "Discarded", False),
                ("Rename bookmark", "First", "Renamed", True),
            ):
                failures = []
                visited = []

                def edit_dialog():
                    dialog = self.app.activeModalWidget()
                    try:
                        self.assertIsInstance(dialog, QInputDialog)
                        visited.append(dialog.windowTitle())
                        self.assertEqual(dialog.windowTitle(), title)
                        editor = dialog.findChild(QLineEdit)
                        self.assertEqual(editor.selectedText(), initial)
                        controller = editor.findChild(InputContextMenu)
                        self.assertIsNotNone(controller)
                        menu = controller.create_menu()
                        try:
                            self.assertEqual(
                                [None if a.isSeparator() else a.text().split("\t")[0]
                                 for a in menu.actions()],
                                ["Undo", None, "Copy", "Paste", "Select all"],
                            )
                        finally:
                            menu.deleteLater()
                        QTest.keyClicks(editor, name)
                        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                        self.assertEqual(editor.text(), initial)
                        QTest.keyClick(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
                        self.assertEqual(editor.text(), name)
                    except Exception as error:
                        failures.append(error)
                    finally:
                        if dialog is not None:
                            dialog.accept() if accept else dialog.reject()

                QTimer.singleShot(0, edit_dialog)
                if title == "Add bookmark":
                    self.bookmarks.prompt(location)
                else:
                    self.bookmarks.rename(result_location.source)
                if failures:
                    raise failures[0]
                self.assertEqual(visited, [title])
                bookmark = self.bookmarks.items[result_location.source]
                self.assertEqual(bookmark.name, name if accept else initial)
                self.assertEqual(bookmark.location, location)

    def test_dialog_cancel_default_name_and_duplicate_menu(self):
        self.render(("ERROR: needle",), LogreaderConfig(
            context=0, combined_view=False, enabled_patterns=("error_colon",),
            custom_patterns=("needle",)))
        location = self.view.model.location(0)
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=("No", False)):
            self.bookmarks.prompt(location)
        self.assertFalse(self.bookmarks.items)
        self.assertTrue(self.bookmarks.strip.isHidden())
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=(" ", True)):
            self.bookmarks.prompt(location)
        self.assertEqual(self.bookmarks.items[location.source].name, "Line 1,001")
        duplicate = self.view.model.location(1)
        self.assertFalse(self.bookmarks.add(duplicate, "duplicate"))
        menu = QMenu()
        self.bookmarks.add_menu_actions(menu, duplicate)
        self.assertEqual([a.text() for a in menu.actions()], ["Add note...", "", "Remove bookmark", "Rename bookmark"])
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", return_value=("A & B 😀", True)):
            next(a for a in menu.actions() if a.text() == "Rename bookmark").trigger()
        self.assertEqual(self.bookmarks.items[location.source].name, "A & B 😀")
        self.assertEqual(self.bookmarks.items[location.source].location, location)
        with patch("logreader.bookmarks.BookmarkDeletionDialog.exec", return_value=QDialog.DialogCode.Accepted):
            next(a for a in menu.actions() if a.text() == "Remove bookmark").trigger()
        self.assertFalse(self.view.editor.extraSelections())
        self.assertTrue(self.bookmarks.strip.isHidden())

    def test_original_category_restored_after_fallback_and_combined_view(self):
        lines = ("before", "ERROR: needle", "after")
        config = LogreaderConfig(context=1, combined_view=False,
                                 enabled_patterns=("error_colon",), custom_patterns=("needle",))
        self.render(lines, config)
        rows = self.view.model.rows_for_source(SourceLocation("snapshot", 1002))
        location = self.add(rows[-1])
        blocks = self.view.editor._bookmark_blocks
        self.assertEqual(list(blocks.values()), [False, True])
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), rows[-1])
        for changed in (replace(config, custom_patterns=(), custom_pattern_match_case=(),
                                custom_pattern_exclude=()), replace(config, combined_view=True)):
            self.render(lines, changed, load=False)
            self.bookmarks.activate(location.source)
            self.assertEqual(self.selected_row(), self.view.model.resolve(location))
            self.assertEqual(self.bookmarks.items[location.source].location, location)
        self.render(lines, config, load=False)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), rows[-1])

    def test_identical_custom_categories_keep_distinct_preferred_occurrence(self):
        config = LogreaderConfig(context=0, combined_view=False, enabled_patterns=(),
                                 custom_patterns=("needle", "needle"))
        self.render(("needle",), config)
        location = self.add(1)
        self.assertNotEqual(self.view.model.location(0), location)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 1)
        self.render(("needle",), replace(config, custom_patterns=("unrelated", "needle", "needle"),
                                         custom_pattern_match_case=(), custom_pattern_exclude=()), load=False)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 1)

    def test_context_line_can_disappear_and_return_as_match(self):
        lines = ("context needle", "ERROR: failure", "after")
        self.render(lines)
        location = self.add(0)
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)), load=False)
        self.assertEqual(self.bookmarks.strip.tabText(0), "(c) Important")
        self.assertEqual(self.bookmarks.strip.tabToolTip(0),
                         "Source-only bookmark\nLine 1,001\n"
                         "Converted to source bookmark. Match no longer appears on results. "
                         "Re-analysis needed.")
        self.assertTrue(self.bookmarks.items[location.source].source_only)
        self.bookmarks.activate(location.source)
        self.assertFalse(self.view.source_active)
        self.view.set_source_active(True)
        self.bookmarks.activate(location.source)
        self.assertTrue(self.view.source_active)
        source = self.view.source_view
        self.assertEqual(source.editor.first_source_line + source.editor.textCursor().blockNumber(), 1001)
        self.view.set_source_active(False)
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=(), custom_patterns=("needle",)), load=False)
        self.assertEqual(self.bookmarks.strip.tabText(0), "Important")
        self.assertFalse(self.bookmarks.items[location.source].source_only)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.selected_row(), 0)
        self.assertEqual(self.bookmarks.items[location.source].location, location)

    def test_repeated_tab_clicks_center_result_and_source_after_scrolling(self):
        self.render(tuple(f"ERROR: {i}" for i in range(300)),
                    LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        location = self.add(150)
        strip = self.bookmarks.strip
        for source_active in (False, True):
            self.view.set_source_active(source_active)
            editor = self.view.source_view.editor if source_active else self.view.editor
            for _ in range(2):
                editor.moveCursor(QTextCursor.MoveOperation.Start)
                editor.verticalScrollBar().setValue(0)
                QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.tabRect(0).center())
                self.assertEqual(editor.source_number(editor.textCursor().blockNumber()), location.source.line)
                self.assertLess(abs(editor.cursorRect().center().y() - editor.viewport().height() / 2),
                                editor.fontMetrics().height() * 2)

    def test_bookmark_hover_clears_after_dismissing_context_menu_outside_strip(self):
        self.render(("ERROR: first",))
        self.add()
        strip = self.bookmarks.strip
        point = strip.tabRect(0).center()
        for source_active in (False, True):
            with self.subTest(source_active=source_active):
                self.view.set_source_active(source_active)
                editor = self.view.source_view.editor if source_active else self.view.editor
                QTest.mouseMove(editor.viewport(), QPoint(200, 100))
                QTest.mouseMove(strip, point)
                self.app.processEvents()
                self.assertEqual(strip.grab().toImage().pixelColor(3, 3).name(),
                                 THEME_COLORS["bookmark_hover"])

                def dismiss_menu():
                    menu = QApplication.activePopupWidget()
                    outside = editor.viewport().mapToGlobal(QPoint(200, 100))
                    QTest.mouseMove(editor.viewport(), QPoint(200, 100))
                    QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                                     pos=menu.mapFromGlobal(outside))

                QTimer.singleShot(50, dismiss_menu)
                strip.customContextMenuRequested.emit(point)
                self.app.processEvents()
                self.assertEqual(strip.grab().toImage().pixelColor(3, 3).name(),
                                 THEME_COLORS["background"])
                QTest.mouseMove(strip, point)
                self.app.processEvents()
                self.assertEqual(strip.grab().toImage().pixelColor(3, 3).name(),
                                 THEME_COLORS["bookmark_hover"])

                QTest.mouseMove(editor.viewport(), QPoint(200, 100))
                self.app.processEvents()

    def test_right_click_opens_actions_without_navigating(self):
        self.render(tuple(f"ERROR: {i}" for i in range(300)))
        self.add(0, "First")
        location = self.add(150, "Later")
        strip = self.bookmarks.strip
        point = strip.tabRect(1).center()
        activated = QSignalSpy(strip.activated)
        strip.rename_requested.disconnect(self.bookmarks.rename)
        strip.remove_requested.disconnect(self.bookmarks.request_remove)
        renamed = QSignalSpy(strip.rename_requested)
        removed = QSignalSpy(strip.remove_requested)

        def inspect_menu(menu, *args):
            self.assertEqual([action.text() for action in menu.actions()],
                             ["Add note...", "", "Remove bookmark", "Rename bookmark"])
            next(a for a in menu.actions() if a.text() == "Rename bookmark").trigger()
            next(a for a in menu.actions() if a.text() == "Remove bookmark").trigger()

        class TestMenu(QMenu):
            def exec(self, *args):
                inspect_menu(self, *args)

        for source_active in (False, True):
            with self.subTest(source_active=source_active):
                self.view.set_source_active(source_active)
                editor = self.view.source_view.editor if source_active else self.view.editor
                editor.moveCursor(QTextCursor.MoveOperation.Start)
                editor.verticalScrollBar().setValue(0)
                strip.setCurrentIndex(0)
                position = editor.textCursor().position()
                with patch("logreader.bookmarks.QMenu", TestMenu):
                    QTest.mouseClick(strip, Qt.MouseButton.RightButton, pos=point)
                    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                              strip.mapToGlobal(point))
                    QApplication.sendEvent(strip, event)
                self.assertEqual(activated.count(), 0)
                self.assertEqual(strip.currentIndex(), 0)
                self.assertEqual(editor.textCursor().position(), position)
                self.assertEqual(editor.verticalScrollBar().value(), 0)
                self.assertEqual(renamed.at(renamed.count() - 1)[0], location.source)
                self.assertEqual(removed.at(removed.count() - 1)[0], location.source)

    @patch("logreader.source_view.SOURCE_PAGE_LINES", 10_000)
    def test_source_page_edge_reload_and_markers_follow_original_numbers(self):
        lines = tuple(f"ERROR: {i}" for i in range(15000))
        self.render(lines, LogreaderConfig(context=0, enabled_patterns=("error_colon",)))
        location = self.add(9999)
        self.view.set_source_active(True)
        source = self.view.source_view
        source.first_page()
        old_start = source.page_start
        self.assertEqual(source.page_end, 10000)
        self.bookmarks.activate(location.source)
        self.assertGreater(source.page_start, old_start)
        row = location.source.line - source.first_line - source.page_start
        self.assertEqual(source.editor._bookmark_blocks, {row: True})
        self.assertLess(abs(source.editor.cursorRect().center().y() - source.editor.viewport().height() / 2), 40)
        source.first_page()
        self.assertEqual(source.editor._bookmark_blocks, {9999: True})

    def test_search_and_copy_preserve_bookmarks_and_native_text_colors(self):
        self.render(("before", "prefix ERROR: needle 😀", "after"))
        location = self.add(1)
        self.view._search_input.setText("needle")
        self.view.search_results()
        wait_for_search(self.view)
        self.view._navigate_search(forward=True)
        self.assertEqual(len(self.view.editor.extraSelections()), 3)
        self.view._search_input.clear()
        self.assertEqual(len(self.view.editor.extraSelections()), 2)
        for text, role in (("prefix", "matched_text"), ("ERROR:", "match")):
            cursor = self.view.editor.document().find(text)
            self.assertEqual(cursor.charFormat().foreground().color().name(), THEME_COLORS[role])
        self.view.editor.selectAll()
        self.assertEqual(self.view.editor.createMimeDataFromSelection().text(),
                         "before\nprefix ERROR: needle 😀\nafter\n")
        self.view.show_source_line(location.source.line)
        self.view._search_input.setText("needle")
        self.view.search_results()
        for _ in range(1000):
            if not self.view.source_view.is_searching:
                break
            QTest.qWait(5)
        self.assertFalse(self.view.source_view.is_searching)
        self.view.source_view.navigate(True)
        self.assertEqual(len(self.view.source_view.editor.extraSelections()), 3)
        self.view._search_input.clear()
        self.assertEqual(len(self.view.source_view.editor.extraSelections()), 2)
        self.assertEqual(self.view.source_view.editor._bookmark_blocks, {1: True})

    def test_full_width_wrapped_background_and_gutter_keep_original_width(self):
        self.render(("before", "ERROR: " + "long line " * 40, "after"))
        editor = self.view.editor
        width = editor.gutter.width()
        self.view.set_line_wrapping(True)
        self.add(1)
        self.app.processEvents()
        block = editor.document().findBlockByNumber(self.view._source_map.block(1))
        self.assertGreater(block.layout().lineCount(), 1)
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        image = editor.viewport().grab().toImage()
        gutter = editor.gutter.grab().toImage()
        for visual_line in range(block.layout().lineCount()):
            y = int(rect.top() + block.layout().lineAt(visual_line).y() + 2)
            self.assertEqual(image.pixelColor(image.width() - 10, y).name(), THEME_COLORS["bookmark"])
            self.assertEqual(gutter.pixelColor(gutter.width() - 2, y).name(), THEME_COLORS["bookmark"])
        self.assertEqual(editor.gutter.width(), width)
        self.assertFalse(editor.textCursor().hasSelection())

    def test_headers_and_space_below_document_are_not_bookmarkable(self):
        self.render(("ERROR: one",))
        editor = self.view.editor
        self.assertIsNone(self.view.result_location_at(QPoint(10, editor.viewport().height() - 5)))
        header = editor.document().firstBlock()
        rect = editor.blockBoundingGeometry(header).translated(editor.contentOffset())
        self.assertIsNone(self.view.result_location_at(QPoint(10, round(rect.center().y()))))
        block = editor.document().findBlockByNumber(self.view._source_map.block(0))
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        for x in (-editor.gutter.width() // 2, editor.viewport().width() - 10):
            self.assertEqual(self.view.result_location_at(QPoint(x, round(rect.top()) + 4)),
                             self.view.model.location(0))

    def test_timing_headers_reproject_bookmark_and_navigation(self):
        self.render(("ERROR: one",))
        location = self.add()
        before = next(iter(self.view.editor._bookmark_blocks))
        self.view.prepend_performance_timings(.1, .2)
        after = next(iter(self.view.editor._bookmark_blocks))
        self.assertGreater(after, before)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.editor.textCursor().blockNumber(), after)

    def test_smaller_analysis_range_preserves_bookmark_in_retained_source(self):
        lines = tuple(f"ERROR: {i}" for i in range(50))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        location = self.add(5)
        analysis = analyze_lines(lines[-10:], config.search_patterns(), line_offset=1040)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.wait_render()
        self.assertEqual(self.bookmarks.strip.tabText(0), "(c) Important")
        self.view.set_source_active(True)
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 5)
        self.assertEqual(len(self.view.source_view.lines), 50)

    def test_many_bookmarks_scroll_in_one_strip_and_support_keyboard_activation(self):
        self.render(tuple(f"ERROR: {i}" for i in range(80)))
        for row in range(30):
            self.add(row, f"Bookmark {row}: a long descriptive name")
        strip = self.bookmarks.strip
        self.assertLessEqual(strip.width(), self.view.width())
        self.assertLess(strip.height(), 40)
        self.view.editor.moveCursor(QTextCursor.MoveOperation.End)
        strip.setFocus()
        QTest.keyClick(strip, Qt.Key.Key_Return)
        self.assertEqual(self.selected_row(), 29)
        self.bookmarks.remove(self.view.model.location(10).source)
        self.assertEqual(strip.count(), 29)
        self.assertEqual(strip.tabData(strip.currentIndex()), self.view.model.location(29).source)

    def test_pending_and_cancelled_render_keep_bookmarks_source_accessible(self):
        lines = tuple(f"ERROR: {i}" for i in range(50))
        config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
        self.render(lines, config)
        location = self.add(20)
        analysis = analyze_lines(lines, config.search_patterns(), line_offset=1000)
        self.view.start_rendering(2, "sample.log", analysis, config)
        self.assertFalse(self.bookmarks.strip.isTabEnabled(0))
        self.view.set_source_active(True)
        self.assertTrue(self.bookmarks.strip.isTabEnabled(0))
        self.bookmarks.activate(location.source)
        self.assertEqual(self.view.source_view.editor.textCursor().blockNumber(), 20)
        self.view.cancel_rendering()
        self.assertEqual(len(self.bookmarks.items), 1)
        self.assertEqual(self.bookmarks.strip.tabText(0), "(c) Important")
        self.view.set_source_active(False)
        self.bookmarks.activate(location.source)
        self.assertFalse(self.view.source_active)

    def test_source_replacement_clears_bookmarks_even_without_result_model(self):
        self.render(("ERROR: one",))
        location = self.add()
        self.view.editor.set_model(None)
        notices = []
        self.view.bookmarks_cleared.connect(lambda: notices.append(True))
        self.view.set_source(("ERROR: new",), 1001, snapshot_id="replacement")
        self.assertFalse(self.bookmarks.items)
        self.assertEqual(notices, [True])
        self.assertFalse(self.bookmarks.add(location, "stale"))
        self.assertFalse(self.view.source_view.bookmarked_lines)

    def test_source_replaced_while_naming_does_not_bookmark_wrong_document(self):
        self.render(("ERROR: old",))
        location = self.view.model.location(0)
        def changed_source(*args):
            self.view.set_source(("ERROR: new",), 1001, snapshot_id="new")
            return "stale", True
        with patch("logreader.bookmarks.ResultsBookmarks._prompt_name", side_effect=changed_source):
            self.bookmarks.prompt(location)
        self.assertFalse(self.bookmarks.items)

    def test_control_wheel_zoom_retains_bookmark_in_both_editors(self):
        self.render(("ERROR: one",))
        self.add()
        for active in (False, True):
            self.view.set_source_active(active)
            editor = self.view.source_view.editor if active else self.view.editor
            before = editor.font().pointSizeF()
            point = QPointF(editor.viewport().rect().center())
            wheel = QWheelEvent(point, point, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
            self.app.sendEvent(editor.viewport(), wheel)
            self.assertGreater(editor.font().pointSizeF(), before)
            self.assertEqual(len(editor._bookmark_blocks), 1)

    def test_documents_keep_separate_bookmarks_and_replacement_notice(self):
        pages = [DocumentPage(), DocumentPage()]
        for page in pages:
            self.addCleanup(page.deleteLater)
            self.addCleanup(page.dispose)
            page.stage_loaded_log(Path("sample.log"), LoadedLog(("ERROR: one",), "utf-8", 1))
            config = LogreaderConfig(context=0, enabled_patterns=("error_colon",))
            view = page.results_view
            view.start_rendering(1, "sample.log", analyze_lines(("ERROR: one",), config.search_patterns()), config)
            for _ in range(100):
                if not view.is_rendering:
                    break
                QTest.qWait(5)
            self.assertTrue(view.bookmarks.add(view.model.location(0), "Important"))
        pages[0].stage_loaded_log(Path("sample.log"), LoadedLog(("ERROR: changed",), "utf-8", 1))
        self.assertFalse(pages[0].results_view.bookmarks.items)
        self.assertIn("Bookmarks cleared", pages[0].status_message)
        self.assertEqual(len(pages[1].results_view.bookmarks.items), 1)


if __name__ == "__main__":
    unittest.main()
