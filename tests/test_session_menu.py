import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMenu

from qt_helpers import qt_application, retire_window, wait_for_load, wait_source, wait_until
from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot
from logreader.profiles import Profile, ProfileStore
from logreader.session_snapshot import SessionTab
from logreader.sessions import SessionError, SessionStore
from logreader.ui.dialogs import CompactDialog
from logreader.ui.qt_app import LogreaderWindow
from logreader.ui.results.results_model import SourceLocation
from logreader.ui.session_menu import OpenSessionDialog, ReplaceTabsDialog, SaveSessionDialog


Button = QDialogButtonBox.StandardButton


class SessionMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {"LOGREADER_SESSION_DIR": str(self.root / "sessions"),
                                      "LOGREADER_PROFILE_DIR": str(self.root / "profiles")})
        env.start()
        self.addCleanup(env.stop)
        self.store = SessionStore()
        self.original = self.root / "original.log"
        self.original.write_text("original\n", encoding="utf-8")
        self.incoming = SessionTab(self.root / "other.log", FilterSnapshot(context=17), regex_draft="[")
        warnings = patch("logreader.ui.session_menu.show_warning")
        self.warning = warnings.start()
        self.addCleanup(warnings.stop)
        self.new_window()

    def new_window(self):
        self.window = LogreaderWindow()
        self.addCleanup(retire_window, self.window)
        menu = self.window.title_menus.findChild(QMenu, "fileMenu")
        self.save, self.open = menu.actions()

    def test_save_restart_recover_and_reopen_through_file_menu(self):
        def use_dialog(action, dialog_class, respond):
            errors = []

            def interact():
                dialog = self.app.activeModalWidget()
                try:
                    self.assertIsInstance(dialog, dialog_class)
                    respond(dialog)
                except Exception as error:
                    errors.append(error)
                finally:
                    if dialog is not None and dialog.isVisible():
                        dialog.reject()

            QTimer.singleShot(0, interact)
            action.trigger()
            if errors:
                raise errors[0]

        def save_as(name):
            def save(dialog):
                dialog.name_input.setText(name)
                dialog.buttons.button(Button.Save).click()
            use_dialog(self.save, SaveSessionDialog, save)

        def reopen(name):
            self.new_window()
            self.window.show()

            def select(dialog):
                row = next(dialog.list.topLevelItem(i) for i in range(dialog.list.topLevelItemCount())
                           if dialog.list.topLevelItem(i).text(0) == name)
                dialog.list.setCurrentItem(row)
                dialog.buttons.button(Button.Open).click()

            use_dialog(self.open, OpenSessionDialog, select)
            pages = [self.window._pages.widget(i) for i in range(self.window._tabs.count())]
            for page in pages:
                wait_for_load(page)
                self.assertIsNone(page.session.analysis)
                self.assertFalse(page.results_view.results_ready)
            return pages

        changed = self.root / "rotating.log"
        changed.write_text("previous entry\nstable entry\n", encoding="utf-8")
        original_text = "header\nERROR: evidence-493\noriginal trailer\n"
        self.original.write_text(original_text, encoding="utf-8")
        third = self.root / "third.log"
        third.write_text("third log contents\n", encoding="utf-8")
        self.window.load_files((changed, self.original, third))
        pages = [self.window._pages.widget(i) for i in range(3)]
        for page in pages:
            wait_for_load(page)
        first, moved, _ = pages
        first.filter_panel.restore_snapshot(FilterSnapshot(context=9))
        profiles = ProfileStore()
        profile = Profile("Investigation", FilterSnapshot(
            context=0, max_lines_scanned=2, enabled_patterns=("error_colon",), combined_view=False,
            custom_patterns=(PatternSnapshot("disabled", enabled=False, match_case=True),),
        ))
        profiles.create(profile)
        self.window._select_document(moved)
        moved.apply_profile(profile)
        moved.filter_panel.set_pattern_drafts("unfinished text", "(?")
        moved.analyze()
        wait_until(lambda: moved.results_view.results_ready and not moved.session.is_busy)
        for page, line, name in ((first, 1, "Rotated"), (first, 2, "Stable"),
                                 (moved, 2, "Error"), (moved, 3, "Trailer")):
            source = SourceLocation(page.session.snapshot_id, line)
            view = page.results_view
            location = view.model.location(view.model.rows_for_source(source)[0]) if name == "Error" else source
            self.assertTrue(view.bookmarks.add(location, name))
            view.bookmarks.items[source].note = f"{name} note\nFollow up"
        self.window._select_document(moved)
        before, selected = self.window.capture_session()
        save_as("Investigation one")
        self.window.close()
        destination = self.original.rename(self.root / "relocated.log")
        destination.write_text(original_text.replace("original trailer", "different trailer"), encoding="utf-8")
        changed.write_text("unrelated entry\nstable entry\n", encoding="utf-8")
        profiles.delete(profile)

        first, moved, _ = reopen("Investigation one")
        self.assertIs(self.window._document, moved)
        self.assertEqual(self.window.capture_session(), (before, selected))
        self.assertTrue(moved.file_warning.isVisible())
        self.assertEqual(first.results_view.bookmarks.strip.tabText(0), "Unresolved - Rotated")
        self.window._select_document(first)
        first.results_view.set_source_active(True)
        stable = SourceLocation(first.session.snapshot_id, 2)
        first.results_view.bookmarks.activate(stable)
        wait_source(first.results_view)
        self.assertEqual(first.results_view.source_view.editor.caret.row, 1)
        self.window._select_document(moved)
        with patch("logreader.ui.qt_app.QFileDialog.getOpenFileName", return_value=(str(destination), "")):
            moved.file_warning.replace.click()
        wait_for_load(moved)
        expected = (before[0], replace(before[1], path=destination), before[2])
        self.assertEqual(self.window.capture_session(), (expected, selected))
        self.assertFalse(moved.file_warning.isVisible())
        self.assertEqual(self.window._tabs.tabToolTip(selected), str(destination))
        self.assertNotIn(os.path.normcase(str(self.original)), self.window._documents_by_path)
        self.assertEqual(moved.results_view.source_view.bookmarked_lines, {2})
        self.assertEqual(moved.results_view.bookmarks.strip.tabText(1), "Unresolved - Trailer")
        self.assertIsNone(moved.session.analysis)
        self.window.load_file(destination)
        self.assertIs(self.window._document, moved)
        self.assertEqual(self.window._tabs.count(), 3)
        self.window._analyze_button.click()
        wait_until(lambda: moved.results_view.results_ready and not moved.session.is_busy)
        record = moved.results_view.bookmarks.items[SourceLocation(moved.session.snapshot_id, 2)]
        self.assertEqual(moved.results_view.model.location(moved.results_view.model.resolve(record.location)),
                         record.location)
        save_as("Investigation two")
        raw = (self.store.directory / "Investigation two.lrsess").read_text(encoding="utf-8")
        for source_text in ("evidence-493", "stable entry", "different trailer", "third log contents"):
            self.assertNotIn(source_text, raw)
        self.window.close()
        first, moved, _ = reopen("Investigation two")
        self.assertEqual(self.window.capture_session(), (expected, selected))
        self.assertIs(self.window._document, moved)
        self.assertEqual(moved.session.lines, ("ERROR: evidence-493", "different trailer"))
        self.assertEqual(first.results_view.source_view.bookmarked_lines, {2})
        self.assertEqual(moved.results_view.source_view.bookmarked_lines, {2})
        self.warning.assert_not_called()

    @staticmethod
    def click(button):
        def respond(dialog):
            dialog.buttons.button(button).click()
            return dialog.result()
        return respond

    def open_original(self):
        self.window.load_file(self.original)
        wait_for_load(self.window._document)
        return self.window._document

    def test_file_actions_create_unique_snapshots_and_require_tabs_to_save(self):
        self.assertEqual((self.save.text(), self.open.text()), ("Save session…", "Open session…"))
        self.assertFalse(self.save.isEnabled())
        self.assertTrue(self.open.isEnabled())
        self.open_original()
        self.assertTrue(self.save.isEnabled())
        instant = datetime(2026, 11, 2, 10, 11, 12, tzinfo=timezone.utc)
        base = instant.astimezone().strftime("%Y-%m-%d %H-%M-%S")

        def save_default(dialog):
            self.assertEqual(dialog.name_input.text(), base)
            # Another writer takes the suggestion while the dialog is open.
            self.store.save((self.incoming,), 0, saved_at=instant)
            return self.click(Button.Save)(dialog)

        with patch("logreader.ui.session_menu.datetime", wraps=datetime) as clock, \
                patch.object(SaveSessionDialog, "exec", save_default):
            clock.now.return_value = instant
            self.save.trigger()
        self.assertEqual(self.store.load(self.store.directory / f"{base}.lrsess").tabs, (self.incoming,))
        snapshot = self.store.load(self.store.directory / f"{base} (2).lrsess")
        self.assertEqual((snapshot.tabs, snapshot.selected_tab), self.window.capture_session())
        self.window.close_tab(0)
        self.assertFalse(self.save.isEnabled())

    def test_custom_name_can_be_corrected_and_overwrite_requires_an_explicit_choice(self):
        self.open_original()
        path = self.store.save((self.incoming,), 0, name="Incident")
        before = path.read_bytes()

        def choose_name(dialog):
            dialog.name_input.setText("../invalid")
            dialog.accept()
            self.assertIn("filename", dialog.error_label.text())
            dialog.name_input.setText("Incident")
            with patch.object(CompactDialog, "exec", self.click(Button.Cancel)):
                dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertEqual(path.read_bytes(), before)
            with patch.object(CompactDialog, "exec", self.click(Button.Yes)):
                dialog.accept()
            return dialog.result()

        with patch.object(SaveSessionDialog, "exec", choose_name):
            self.save.trigger()
        self.assertEqual(self.store.load(path).tabs, self.window.capture_session()[0])
        self.assertEqual(list(self.store.directory.iterdir()), [path])

    def test_list_orders_sessions_reports_damage_and_rereads_changed_files(self):
        original = self.open_original()
        earlier = datetime.now(timezone.utc) - timedelta(days=1)
        stale = self.store.save((self.incoming,), 0, name="Earlier", saved_at=earlier)
        self.store.save((self.incoming,), 0, name="Latest")
        broken = self.store.directory / "broken.lrsess"
        broken.write_bytes(b"{")

        def choose(dialog):
            rows = [dialog.list.topLevelItem(i) for i in range(dialog.list.topLevelItemCount())]
            self.assertEqual([row.text(0) for row in rows], ["Latest", "Earlier", "broken.lrsess"])
            self.assertEqual(rows[2].text(1), "Could not load")
            stale.write_bytes(b"bad")
            for index, path in ((2, broken), (1, stale)):
                dialog.list.setCurrentItem(rows[index])
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertIn(path.name, self.warning.call_args.args[2])
                self.assertIs(self.window._document, original)
            dialog.list.setCurrentItem(rows[0])
            dialog.list.itemActivated.emit(rows[0], 0)
            return dialog.result()

        with patch.object(OpenSessionDialog, "exec", choose), \
                patch.object(ReplaceTabsDialog, "exec", self.click(Button.Discard)):
            self.open.trigger()
        self.assertEqual(self.window.capture_session(), ((self.incoming,), 0))

    def test_browse_opens_external_session_from_an_empty_workspace(self):
        outside = SessionStore(self.root / "external")
        path = outside.save((self.incoming,), 0, name="External")

        def browse(dialog):
            self.assertFalse(dialog.buttons.button(Button.Open).isEnabled())
            button = dialog.buttons.buttonRole
            browse_button = next(b for b in dialog.buttons.buttons()
                                 if button(b) == QDialogButtonBox.ButtonRole.ActionRole)
            with patch("logreader.ui.session_menu.QFileDialog.getOpenFileName",
                       side_effect=[("", ""), (str(path), "")]) as picker:
                browse_button.click()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                browse_button.click()
                self.assertIn("*.lrsess", picker.call_args.args[-1])
            return dialog.result()

        with patch.object(OpenSessionDialog, "exec", browse), \
                patch.object(ReplaceTabsDialog, "exec", side_effect=AssertionError("No tabs to replace")):
            self.open.trigger()
        self.assertEqual(self.window.capture_session(), ((self.incoming,), 0))
        self.assertFalse(self.store.directory.exists())

    def test_cancel_or_failed_save_keeps_current_workspace_and_success_saves_before_replacing(self):
        original = self.open_original()
        original.filter_panel.set_pattern_drafts("work in progress", "")
        before = self.window.capture_session()
        self.store.save((self.incoming,), 0, name="Incoming")

        def failed_save(dialog):
            with patch.object(SessionStore, "save", side_effect=SessionError("Disk full")):
                dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertIn("Disk full", dialog.error_label.text())
            return self.click(Button.Cancel)(dialog)

        with patch.object(OpenSessionDialog, "exec", self.click(Button.Open)):
            with patch.object(ReplaceTabsDialog, "exec", self.click(Button.Cancel)), \
                    patch.object(SaveSessionDialog, "exec", side_effect=AssertionError("Save after cancel")):
                self.open.trigger()
            self.assertIs(self.window._document, original)
            with patch.object(ReplaceTabsDialog, "exec", self.click(Button.Save)):
                for respond in (self.click(Button.Cancel), failed_save):
                    with patch.object(SaveSessionDialog, "exec", respond):
                        self.open.trigger()
                    self.assertIs(self.window._document, original)
                    self.assertEqual(self.window.capture_session(), before)
                    self.assertEqual(len(self.store.load_all().sessions), 1)

                def save_current(dialog):
                    dialog.name_input.setText("Before switching")
                    return self.click(Button.Save)(dialog)

                with patch.object(SaveSessionDialog, "exec", save_current):
                    self.open.trigger()
        preserved = self.store.load(self.store.directory / "Before switching.lrsess")
        self.assertEqual((preserved.tabs, preserved.selected_tab), before)
        self.assertEqual(self.window.capture_session(), ((self.incoming,), 0))
