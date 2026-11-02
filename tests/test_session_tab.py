import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QDialog, QMenu

from qt_helpers import qt_application, retire_results, wait_for_load, wait_for_navigation, wait_source, wait_until
from logreader.core import CategoryIdentity
from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot
from logreader.profiles import Profile, ProfileStore
from logreader.session_snapshot import BookmarkSnapshot, SessionTab
from logreader.sessions import SessionStore
from logreader.ui.bookmarks import BookmarkNotesDialog
from logreader.ui.document_page import DocumentPage
from logreader.ui.results.results_model import SourceLocation


class SessionTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "app.log"
        self.page = DocumentPage()
        self.page.resize(960, 800)
        self.page.show()
        self.addCleanup(retire_results)
        self.addCleanup(self.page.dispose)
        self.view = self.page.results_view
        self.bookmarks = self.view.bookmarks

    def source(self, line):
        return SourceLocation(self.page.session.snapshot_id, line)

    def analyze(self):
        finished = QSignalSpy(self.page.analysis_finished)
        self.page.analyze()
        wait_until(lambda: finished.count() == 1)

    def restore(self, tab):
        self.page.restore_session_tab(tab)
        wait_for_load(self.page)

    def test_settings_and_drafts_survive_changes_to_the_named_profile(self):
        self.path.write_text("first\nsecond\nthird\n", encoding="utf-8")
        self.page.load_file(self.path)
        wait_for_load(self.page)
        profiles = ProfileStore(self.root / "profiles")
        profile = Profile("Review", FilterSnapshot(max_lines_scanned=3, custom_patterns=(
            PatternSnapshot("disable me", enabled=False, match_case=True),
        )))
        profiles.create(profile)
        self.page.apply_profile(profile)
        panel = self.page.filter_panel
        panel._limit_spin.setValue(2)
        panel._custom_pattern.setText("  draft  ")
        panel._regex_pattern.setText("(?")
        tab = self.page.capture_session_tab()
        self.assertEqual(tab.filters, replace(profile.filters, max_lines_scanned=2))
        self.assertEqual((tab.custom_draft, tab.regex_draft), ("  draft  ", "(?"))
        newer = profiles.update(profile, FilterSnapshot(context=60))
        for delete in (False, True):
            if delete:
                profiles.delete(newer)
            self.page.apply_profile(newer)
            panel.set_pattern_drafts("another", "")
            self.restore(tab)
            self.assertIsNone(self.page.applied_profile)
            self.assertIsNone(self.page.session.analysis)
            self.assertEqual(self.page.session.lines, ("second", "third"))
            self.assertEqual(self.page.capture_session_tab(), tab)

    def test_second_save_merges_edits_removals_and_unresolved_bookmarks_in_order(self):
        lines = ["header", "two", "three", "needle blå", "needle original", "remove", "ERROR: seven", "eight"]
        self.path.write_text("\n".join(lines), encoding="utf-8")
        self.page.load_file(self.path)
        wait_for_load(self.page)
        filters = FilterSnapshot(context=0, enabled_patterns=(), combined_view=False,
                                 custom_patterns=(PatternSnapshot("needle"), PatternSnapshot("needle")))
        self.page.filter_panel.restore_snapshot(filters)
        self.analyze()
        for line, name in ((4, "Preferred"), (1, "Header"), (5, "Changed"), (6, "Remove"), (7, "Convert")):
            source = self.source(line)
            rows = self.view.model.rows_for_source(source)
            location = self.view.model.location(rows[-1]) if rows else source
            self.assertTrue(self.bookmarks.add(location, name))
            self.bookmarks.items[source].note = f"{name}\nsecond line  "
        self.bookmarks._set_convert_when_shown(self.source(7), self.bookmarks.items[self.source(7)], True)
        self.page.filter_panel._limit_spin.setValue(5)
        self.page.filter_panel._pattern_checkboxes["error_colon"].setChecked(True)

        # Capture still sees the already loaded text, even though disk now differs.
        lines[4] = "needle changed"
        self.path.write_text("\n".join(lines), encoding="utf-8")
        store = SessionStore(self.root / "sessions")
        saved = store.load(store.save((self.page.capture_session_tab(),), 0)).tabs[0]
        self.assertEqual(saved.bookmarks[2].line_sha256, hashlib.sha256(b"needle original").hexdigest())
        self.restore(saved)
        self.assertEqual(self.page.capture_session_tab(), saved)
        self.assertFalse(self.view.results_ready)
        self.assertEqual(self.bookmarks.strip.tabText(1), "Unresolved - Header")
        self.assertIn("unavailable", self.bookmarks.strip.tabToolTip(1))
        self.assertEqual(self.bookmarks.strip.tabText(2), "Unresolved - Changed")
        self.assertIn("has changed", self.bookmarks.strip.tabToolTip(2))
        self.assertEqual(self.view.source_view.bookmarked_lines, {4, 6, 7})
        line_menu = QMenu()
        self.bookmarks.add_menu_actions(line_menu, self.source(5))
        self.assertFalse(any(action.isEnabled() for action in line_menu.actions()))

        self.view.set_source_active(True)
        self.assertTrue(self.bookmarks.strip.isTabEnabled(0))
        self.bookmarks.activate(self.source(6))
        wait_source(self.view)
        self.bookmarks.activate(self.source(4))
        wait_source(self.view)
        self.assertEqual(self.view.source_view.editor.caret.row, 0)
        self.bookmarks.activate(self.source(5))
        self.assertEqual(self.view.source_view.editor.caret.row, 0)
        self.view.set_source_active(False)
        self.analyze()
        preferred = self.bookmarks.items[self.source(4)].location
        self.assertEqual(preferred.category, CategoryIdentity("literal", "needle", occurrence=1))
        self.bookmarks.activate(self.source(4))
        wait_for_navigation(self.view)
        self.assertEqual(self.view.editor.caret.row, self.view.editor.presentation.display_row(
            self.view.model.resolve(preferred)))
        for row in self.view.model.rows_for_source(self.source(5)):
            self.assertNotIn(self.view.editor.presentation.display_row(row), self.view._bookmark_rows)
        self.assertEqual(self.bookmarks.items[self.source(7)].location.category, CategoryIdentity("preset", "error_colon"))

        with patch.object(self.bookmarks, "_prompt_name", return_value=("Renamed", True)):
            self.bookmarks.rename(self.source(4))

        def edit(dialog):
            dialog.editor.setPlainText("Updated note\nstill unresolved")
            return QDialog.DialogCode.Accepted

        with patch.object(BookmarkNotesDialog, "exec", edit):
            self.bookmarks.edit_notes(self.source(5))
        self.bookmarks.remove(self.source(6))
        self.assertTrue(self.bookmarks.add(self.source(8), "New"))
        again = store.load(store.save((self.page.capture_session_tab(),), 0)).tabs[0]
        self.assertEqual([record.line for record in again.bookmarks], [4, 1, 5, 7, 8])
        self.assertEqual(again.bookmarks[0], replace(saved.bookmarks[0], name="Renamed"))
        self.assertEqual(again.bookmarks[1], saved.bookmarks[1])
        self.assertEqual(again.bookmarks[2], replace(saved.bookmarks[2], note="Updated note\nstill unresolved"))
        self.restore(again)
        self.assertEqual(self.page.capture_session_tab(), again)
        # Increasing the scan limit rereads the source and can resolve the header.
        self.page.filter_panel._limit_spin.setValue(8)
        self.analyze()
        self.assertEqual(self.view.source_view.bookmarked_lines, {1, 4, 7, 8})
        self.assertEqual(self.page.capture_session_tab().bookmarks, again.bookmarks)

    def test_pending_and_failed_restore_can_be_saved_and_retried(self):
        bookmark = BookmarkSnapshot(3, hashlib.sha256(b"expected").hexdigest(), "Expected", "full\nnote")
        tab = SessionTab(self.path, FilterSnapshot(max_lines_scanned=2), bookmarks=(bookmark,))
        with patch.object(self.page._scheduler.loading, "submit") as submit:
            self.page.restore_session_tab(tab)
            self.assertEqual(self.page.capture_session_tab(), tab)
            submit.call_args.args[0].run()
        wait_for_load(self.page)
        self.assertEqual(self.page.capture_session_tab(), tab)
        self.assertEqual(self.bookmarks.strip.tabText(0), "Unresolved - Expected")
        warning = self.page.file_warning
        self.assertTrue(warning.isVisible())
        self.assertEqual(warning.message.toPlainText(), f"{self.path}\n{self.page.session.load_error}")
        self.path.write_text("first\nsecond\nexpected\n", encoding="utf-8")
        warning.retry.click()
        wait_for_load(self.page)
        self.assertFalse(warning.isVisible())
        self.assertIsNone(self.page.session.analysis)
        self.assertEqual(self.page.capture_session_tab(), tab)
        self.assertEqual(self.view.source_view.lines, ("second", "expected"))
        self.assertEqual(self.view.source_view.bookmarked_lines, {3})
        self.assertEqual(self.bookmarks.strip.tabText(0), "Expected")
