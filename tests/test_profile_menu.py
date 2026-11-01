import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from qt_helpers import capture_analysis, qt_application, retire_window, trigger_pattern_action, wait_for_load, wait_until
from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot
from logreader.profiles import Profile, ProfileError
from logreader.ui.profile_menu import ProfileDeletionDialog, ProfileNameDialog
from logreader.ui.qt_app import LogreaderWindow


class ProfileMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"LOGREADER_PROFILE_DIR": str(self.root / "profiles")})
        environment.start()
        self.addCleanup(environment.stop)
        warnings = patch("logreader.ui.profile_menu.show_warning")
        self.warning = warnings.start()
        self.addCleanup(warnings.stop)
        self.window = LogreaderWindow()
        self.addCleanup(retire_window, self.window)
        self.controller = self.window._profiles_menu

    def open_log(self, name):
        path = self.root / name
        path.write_text("ERROR: first\nWARNING: second\nINFO: other\n", encoding="utf-8")
        self.window.load_file(path)
        page = self.window._document
        wait_for_load(page)
        return page

    def analyze(self, page):
        page.analyze()
        wait_until(lambda: not page.session.is_busy)
        self.assertIsNotNone(page.session.analysis)

    def menu_action(self, text):
        return next(action for action in self.controller.menu.actions() if action.text() == text)

    def profile_action(self, profile):
        return next(action for action in self.controller.menu.actions()
                    if action.data() == profile.profile_id)

    def test_menu_empty_state_tab_selection_and_reopening_discover_saved_profiles(self):
        self.controller.menu.aboutToShow.emit()
        self.assertEqual([action.text() for action in self.controller.menu.actions()],
                         ["Save as new profile…", "Update profile", "", "No saved profiles", "",
                          "Rename", "Delete", "", "Open profiles folder"])
        for name in ("Update profile", "Rename", "Delete"):
            self.assertFalse(self.menu_action(name).isEnabled())
        self.assertFalse(self.menu_action("Save as new profile…").isEnabled())
        self.assertFalse(self.menu_action("No saved profiles").isEnabled())
        self.assertTrue(self.menu_action("Open profiles folder").isEnabled())
        self.assertFalse(self.controller.store.directory.exists())
        alpha = Profile("Alpha & beta", FilterSnapshot(context=9))
        zulu = Profile("Zulu", FilterSnapshot(context=12))
        self.controller.store.save(zulu)
        self.controller.store.save(alpha)
        self.controller.menu.aboutToShow.emit()
        self.assertEqual([action.text() for action in self.controller._profile_actions], ["Alpha && beta", "Zulu"])
        self.assertFalse(self.profile_action(alpha).isEnabled())
        self.assertTrue(self.menu_action("Rename").isEnabled())
        self.assertTrue(self.menu_action("Delete").isEnabled())
        first = self.open_log("first.log")
        self.assertTrue(self.profile_action(alpha).isEnabled())
        self.profile_action(alpha).trigger()
        self.assertEqual(first.applied_profile, alpha)
        self.assertTrue(self.profile_action(alpha).isChecked())
        self.assertEqual(first.status_message, "Profile applied: Alpha & beta")
        second = self.open_log("second.log")
        self.assertIsNone(second.applied_profile)
        self.assertFalse(self.profile_action(alpha).isChecked())
        self.profile_action(zulu).trigger()
        self.window._select_document(first)
        self.assertTrue(self.profile_action(alpha).isChecked())
        self.assertFalse(self.profile_action(zulu).isChecked())
        self.assertEqual(second.applied_profile, zulu)
        self.window.close_tab(0)
        self.window.close_tab(0)
        self.assertFalse(self.menu_action("Save as new profile…").isEnabled())
        self.assertFalse(self.profile_action(alpha).isEnabled())
        reopened = LogreaderWindow()
        try:
            reopened._profiles_menu.refresh()
            self.assertEqual(reopened._profiles_menu._profiles, (alpha, zulu))
        finally:
            retire_window(reopened)

    def test_save_uses_current_controls_and_rejects_duplicate_names_without_replacing_files(self):
        other = self.open_log("other.log")
        other_snapshot = other.filter_panel.capture_snapshot()
        page = self.open_log("active.log")
        self.analyze(page)
        analyzed = page.session.analysis_config
        original = Profile("Database", FilterSnapshot())
        original_path = self.controller.store.save(original)
        original_bytes = original_path.read_bytes()
        page.filter_panel._context_spin.setValue(23)
        page.filter_panel._custom_pattern.setText("tenant")
        page.filter_panel.add_custom_pattern()
        page.filter_panel._custom_pattern.setText("unfinished text")
        page.filter_panel._regex_pattern.setText("[")
        expected = page.filter_panel.capture_snapshot()

        def name_profile(dialog):
            dialog.accept()
            self.assertEqual(dialog.error_label.text(), "Enter a profile name.")
            dialog.name_input.setText(" database ")
            dialog.accept()
            self.assertIn("already exists", dialog.error_label.text())
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertEqual(original_path.read_bytes(), original_bytes)
            dialog.name_input.setText(" Investigation ")
            dialog.accept()
            return dialog.result()

        with patch.object(ProfileNameDialog, "exec", name_profile):
            self.controller.save_new()
        saved = next(profile for profile in self.controller.store.load_all().profiles
                     if profile.name == "Investigation")
        self.assertEqual(saved.filters, expected)
        self.assertEqual(page.applied_profile, saved)
        self.assertEqual(page.session.analysis_config, analyzed)
        self.assertTrue(self.profile_action(saved).isChecked())
        self.assertEqual(page.filter_panel._regex_pattern.text(), "[")
        self.assertEqual(page.filter_panel._custom_pattern.text(), "unfinished text")
        self.assertEqual(other.filter_panel.capture_snapshot(), other_snapshot)
        self.assertIsNone(other.applied_profile)
        self.assertEqual(original_path.read_bytes(), original_bytes)
        self.warning.assert_not_called()

    def test_apply_replaces_only_active_tab_and_keeps_results_until_analyze(self):
        other = self.open_log("other.log")
        other_snapshot = other.filter_panel.capture_snapshot()
        page = self.open_log("active.log")
        self.analyze(page)
        analyzed = page.session.analysis_config
        old_results = page.results_view.editor.toPlainText()
        profile = Profile("Warnings", FilterSnapshot(
            enabled_patterns=("warning",), context=1, max_lines_scanned=20,
            combined_view=False, separate_entries=False,
            custom_patterns=(PatternSnapshot("Skip", exclude=True),),
            regex_patterns=(PatternSnapshot("[", enabled=False, exclusive=True, match_case=True),),
        ))
        self.controller.store.save(profile)
        self.controller.refresh()
        page.filter_panel._custom_pattern.setText("keep draft")
        page.filter_panel._regex_pattern.setText("incomplete(")
        with patch.object(page, "analyze") as analyze:
            self.profile_action(profile).trigger()
            analyze.assert_not_called()
        self.assertEqual(page.filter_panel.capture_snapshot(), profile.filters)
        self.assertEqual(page.applied_profile, profile)
        self.assertEqual(page.session.analysis_config, analyzed)
        self.assertEqual(page.results_view.editor.toPlainText(), old_results)
        self.assertEqual(page.filter_panel._tab_counts[2].text(), "(1/2)")
        self.assertEqual(page.filter_panel._exclusions_label.text(), "1 exclusion")
        self.assertEqual(page.filter_panel._custom_pattern.text(), "keep draft")
        self.assertEqual(page.filter_panel._regex_pattern.text(), "incomplete(")
        self.assertEqual(other.filter_panel.capture_snapshot(), other_snapshot)
        self.analyze(page)
        self.assertEqual(page.session.analysis_config, page.build_config())

    def test_busy_tab_blocks_actions_but_other_idle_tabs_remain_usable(self):
        profile = Profile("Saved", FilterSnapshot(context=8))
        self.controller.store.save(profile)
        self.controller.refresh()
        path = self.root / "loading.log"
        path.write_text("ERROR: first\n")
        self.window.load_file(path)
        page = self.window._document
        self.assertFalse(self.menu_action("Save as new profile…").isEnabled())
        self.assertFalse(self.profile_action(profile).isEnabled())
        wait_for_load(page)
        before = page.filter_panel.capture_snapshot()
        workers = []
        with capture_analysis(workers):
            page.analyze()
        self.assertFalse(self.menu_action("Save as new profile…").isEnabled())
        self.assertFalse(self.profile_action(profile).isEnabled())
        with patch.object(ProfileNameDialog, "exec") as dialog:
            self.controller.save_new()
            dialog.assert_not_called()
        self.controller.apply(profile)
        self.assertEqual(page.filter_panel.capture_snapshot(), before)
        self.assertIsNone(page.applied_profile)
        other = self.open_log("idle.log")
        self.assertTrue(self.profile_action(profile).isEnabled())
        self.profile_action(profile).trigger()
        self.assertEqual(other.applied_profile, profile)
        self.window._select_document(page)
        workers[0].run()
        wait_until(lambda: not page.session.is_busy)
        self.assertTrue(self.profile_action(profile).isEnabled())

    def test_cancel_invalid_filters_and_failed_save_preserve_tab_association(self):
        page = self.open_log("active.log")
        with patch.object(ProfileNameDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.controller.save_new()
        self.assertFalse(self.controller.store.directory.exists())
        self.assertIsNone(page.applied_profile)

        def failed_save(dialog):
            dialog.name_input.setText("Retain name")
            with patch.object(self.controller.store, "save", side_effect=ProfileError("Disk full")):
                dialog.accept()
            self.assertEqual(dialog.name_input.text(), "Retain name")
            self.assertEqual(dialog.error_label.text(), "Disk full")
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertIsNone(page.applied_profile)
            return QDialog.DialogCode.Rejected

        with patch.object(ProfileNameDialog, "exec", failed_save):
            self.controller.save_new()
        self.assertFalse(self.controller.store.directory.exists())
        page.filter_panel._regex_pattern.setText("[")
        page.filter_panel.add_regex_pattern()
        with patch.object(ProfileNameDialog, "exec") as dialog:
            self.controller.save_new()
            dialog.assert_not_called()
        self.assertIn("Invalid regex", self.warning.call_args.args[2])

    def test_menu_reports_bad_files_and_apply_rereads_changed_or_deleted_files(self):
        page = self.open_log("active.log")
        profile = Profile("Saved", FilterSnapshot(context=8))
        path = self.controller.store.save(profile)
        bad = self.controller.store.directory / "damaged.lrprof"
        bad.write_text("{")
        self.controller.refresh()
        self.warning.assert_not_called()
        self.menu_action("Show load errors…").trigger()
        self.assertIn(bad.name, self.warning.call_args.args[2])
        action = self.profile_action(profile)
        updated = replace(profile, filters=FilterSnapshot(context=34))
        self.controller.store.save(updated)
        action.trigger()
        self.assertEqual(page.applied_profile, updated)
        before = page.filter_panel.capture_snapshot()
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                if deleted:
                    path.unlink()
                else:
                    path.write_text("{}")
                action.trigger()
                self.assertIn("no longer available", self.warning.call_args.args[2])
                self.assertEqual(page.filter_panel.capture_snapshot(), before)
                self.assertEqual(page.applied_profile, updated)

    def test_open_folder_and_storage_errors_are_handled_without_a_log_tab(self):
        with patch("logreader.ui.profile_menu.QDesktopServices.openUrl", return_value=True) as opened:
            self.controller.open_folder()
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.root / "profiles")
        self.assertTrue((self.root / "profiles").is_dir())
        with patch("logreader.ui.profile_menu.QDesktopServices.openUrl", return_value=False):
            self.controller.open_folder()
        self.assertIn("Could not open profiles folder", self.warning.call_args.args[2])
        self.controller._store = None
        with patch.dict(os.environ, {"LOGREADER_PROFILE_DIR": " "}):
            self.controller.refresh()
            self.assertFalse(self.menu_action("Profiles unavailable").isEnabled())
            self.menu_action("Show load errors…").trigger()
            self.assertIn("LOGREADER_PROFILE_DIR", self.warning.call_args.args[2])
            self.controller.open_folder()
            self.assertIn("LOGREADER_PROFILE_DIR", self.warning.call_args.args[2])
        self.controller.refresh()
        self.assertIsNotNone(self.menu_action("No saved profiles"))

    def test_update_marks_other_tabs_modified_without_changing_their_controls_or_results(self):
        profile = Profile("Shared", FilterSnapshot())
        self.controller.store.save(profile)
        first = self.open_log("first.log")
        self.controller.apply(profile)
        self.analyze(first)
        first_results = first.results_view.editor.toPlainText()
        second = self.open_log("second.log")
        self.controller.apply(profile)
        second_snapshot = second.filter_panel.capture_snapshot()
        third = self.open_log("third.log")
        third_snapshot = third.filter_panel.capture_snapshot()
        self.window._select_document(first)
        self.controller.refresh()
        first.filter_panel._context_spin.setValue(42)
        self.assertTrue(first.profile_modified)
        self.assertEqual(self.profile_action(profile).text(), "Shared (modified)")
        self.assertTrue(self.menu_action("Update profile").isEnabled())
        self.menu_action("Update profile").trigger()
        updated = self.controller.store.get(profile.profile_id)
        self.assertEqual(updated.filters.context, 42)
        self.assertFalse(first.profile_modified)
        self.assertFalse(self.menu_action("Update profile").isEnabled())
        self.assertEqual(first.results_view.editor.toPlainText(), first_results)
        self.assertEqual(second.filter_panel.capture_snapshot(), second_snapshot)
        self.assertTrue(second.profile_modified)
        self.assertEqual(second.applied_profile, updated)
        self.window._select_document(second)
        self.assertEqual(self.profile_action(profile).text(), "Shared (modified)")
        self.assertEqual(third.filter_panel.capture_snapshot(), third_snapshot)
        self.assertIsNone(third.applied_profile)
        self.profile_action(profile).trigger()
        self.assertFalse(second.profile_modified)
        self.assertEqual(second.filter_panel.capture_snapshot(), updated.filters)

    def test_modified_indicator_includes_disabled_options_but_not_unfinished_drafts(self):
        profile = Profile("Retained", FilterSnapshot(
            custom_patterns=(PatternSnapshot("inactive", enabled=False, exclude=True, match_case=True),),
        ))
        self.controller.store.save(profile)
        page = self.open_log("active.log")
        self.controller.apply(profile)
        self.controller.refresh()
        page.filter_panel._custom_pattern.setText("draft")
        page.filter_panel._regex_pattern.setText("[")
        self.assertFalse(page.profile_modified)
        patterns = page.filter_panel._custom_pattern_list
        before_config = page.build_config()
        trigger_pattern_action(patterns, 0, "Enable")
        trigger_pattern_action(patterns, 0, "Exclusive")
        trigger_pattern_action(patterns, 0, "Disable")
        self.assertEqual(page.build_config(), before_config)
        self.assertTrue(page.profile_modified)
        self.assertTrue(self.menu_action("Update profile").isEnabled())
        page.filter_panel.restore_snapshot(profile.filters)
        self.assertFalse(page.profile_modified)
        self.assertFalse(self.menu_action("Update profile").isEnabled())

    def test_rename_preserves_identity_and_saved_filters_while_retaining_tab_edits(self):
        profile = Profile("Original", FilterSnapshot(context=12))
        path = self.controller.store.save(profile)
        self.controller.store.save(Profile("Taken", FilterSnapshot()))
        first = self.open_log("first.log")
        self.controller.apply(profile)
        second = self.open_log("second.log")
        self.controller.apply(profile)
        second.filter_panel._context_spin.setValue(99)
        unsaved = second.filter_panel.capture_snapshot()
        self.controller.refresh()

        def rename(dialog):
            self.assertEqual(dialog.name_input.text(), "Original")
            self.assertEqual(dialog.windowTitle(), "Rename profile")
            dialog.name_input.setText(" TAKEN ")
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertIn("already exists", dialog.error_label.text())
            dialog.name_input.setText("New <name> & label")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            return dialog.result()

        with patch.object(ProfileNameDialog, "exec", rename):
            action = next(action for action in self.menu_action("Rename").menu().actions()
                          if action.data() == profile.profile_id)
            action.trigger()
        renamed = self.controller.store.load(path)
        self.assertEqual(renamed.profile_id, profile.profile_id)
        self.assertEqual(renamed.filters, profile.filters)
        self.assertEqual(renamed.name, "New <name> & label")
        self.assertEqual(first.applied_profile, renamed)
        self.assertFalse(first.profile_modified)
        self.assertEqual(second.filter_panel.capture_snapshot(), unsaved)
        self.assertTrue(second.profile_modified)
        self.assertEqual(self.profile_action(renamed).text(), "New <name> && label (modified)")

    def test_delete_requires_explicit_confirmation_and_keeps_open_tabs_intact(self):
        profile = Profile("Saved <name>", FilterSnapshot())
        path = self.controller.store.save(profile)
        first = self.open_log("first.log")
        self.controller.apply(profile)
        self.analyze(first)
        results = first.results_view.editor.toPlainText()
        second = self.open_log("second.log")
        self.controller.apply(profile)
        second.filter_panel._context_spin.setValue(77)
        snapshots = [page.filter_panel.capture_snapshot() for page in (first, second)]
        for response in ("enter", "escape", "cancel", "delete"):
            class RespondingDialog(ProfileDeletionDialog):
                def exec(dialog):
                    self.assertEqual(dialog.target.text(), profile.name)
                    self.assertEqual(dialog.target.textFormat(), Qt.TextFormat.PlainText)
                    self.assertIn("open tabs will be kept", dialog.message.text())
                    self.assertTrue(dialog.buttons.button(QDialogButtonBox.StandardButton.No).isDefault())

                    def respond():
                        if response in ("enter", "escape"):
                            QTest.keyClick(dialog, Qt.Key.Key_Return if response == "enter" else Qt.Key.Key_Escape)
                        else:
                            button = QDialogButtonBox.StandardButton.Yes if response == "delete" else QDialogButtonBox.StandardButton.No
                            dialog.buttons.button(button).click()

                    QTimer.singleShot(0, respond)
                    return super().exec()

            with self.subTest(response=response), patch("logreader.ui.profile_menu.ProfileDeletionDialog", RespondingDialog):
                self.controller.delete(profile)
                self.assertEqual(path.exists(), response != "delete")
                self.assertEqual([page.filter_panel.capture_snapshot() for page in (first, second)], snapshots)
                self.assertEqual(first.results_view.editor.toPlainText(), results)
        self.assertIsNone(first.applied_profile)
        self.assertIsNone(second.applied_profile)
        self.assertFalse(self.menu_action("Update profile").isEnabled())
        self.assertEqual(self.controller.store.load_all().profiles, ())

    def test_update_and_delete_failures_do_not_change_saved_or_tab_state(self):
        profile = Profile("Saved", FilterSnapshot())
        path = self.controller.store.save(profile)
        page = self.open_log("active.log")
        self.controller.apply(profile)
        page.filter_panel._context_spin.setValue(77)
        before = page.filter_panel.capture_snapshot()
        with patch.object(self.controller.store, "_write", side_effect=ProfileError("Disk full")):
            self.controller.update_profile()
        self.assertIn("Disk full", self.warning.call_args.args[2])
        self.assertEqual(self.controller.store.load(path), profile)
        self.assertEqual(page.applied_profile, profile)
        self.assertTrue(page.profile_modified)
        with patch.object(ProfileDeletionDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                patch.object(Path, "unlink", side_effect=PermissionError("Access denied")):
            self.controller.delete(profile)
        self.assertIn("Access denied", self.warning.call_args.args[2])
        self.assertEqual(self.controller.store.load(path), profile)
        self.assertEqual(page.filter_panel.capture_snapshot(), before)
        self.assertEqual(page.applied_profile, profile)
        external = replace(profile, filters=FilterSnapshot(context=2))
        self.controller.store.save(external)
        self.controller.update_profile()
        self.assertIn("has changed", self.warning.call_args.args[2])
        self.assertEqual(self.controller.store.load(path), external)
        path.unlink()
        self.controller.update_profile()
        self.assertIn("no longer available", self.warning.call_args.args[2])
        self.assertFalse(path.exists())
        self.controller.refresh()
        self.assertFalse(page.profile_available)
        self.assertFalse(self.menu_action("Update profile").isEnabled())

    def test_profile_changed_during_rename_or_delete_is_not_overwritten(self):
        profile = Profile("Saved", FilterSnapshot())
        path = self.controller.store.save(profile)
        external = replace(profile, filters=FilterSnapshot(context=23))

        def rename(dialog):
            self.controller.store.save(external)
            dialog.name_input.setText("Attempted rename")
            dialog.accept()
            self.assertIn("has changed", dialog.error_label.text())
            return dialog.result()

        with patch.object(ProfileNameDialog, "exec", rename):
            self.controller.rename(profile)
        self.assertEqual(self.controller.store.load(path), external)

        def delete(dialog):
            self.controller.store.save(profile)
            return QDialog.DialogCode.Accepted

        with patch.object(ProfileDeletionDialog, "exec", delete):
            self.controller.delete(external)
        self.assertIn("has changed", self.warning.call_args.args[2])
        self.assertEqual(self.controller.store.load(path), profile)

    def test_complete_workflow_survives_window_restart_and_allows_management_without_tabs(self):
        page = self.open_log("restart.log")
        page.filter_panel._context_spin.setValue(24)

        def save(dialog):
            dialog.name_input.setText("Restart test")
            dialog.accept()
            return dialog.result()

        with patch.object(ProfileNameDialog, "exec", save):
            self.controller.save_new()
        saved = page.applied_profile
        self.window.close()
        restarted = LogreaderWindow()
        try:
            controller = restarted._profiles_menu
            controller.refresh()
            self.assertEqual(controller._profiles, (saved,))
            restarted.load_file(self.root / "restart.log")
            restored = restarted._document
            wait_for_load(restored)
            controller.apply(saved)
            self.assertEqual(restored.filter_panel.capture_snapshot(), saved.filters)
            restored.filter_panel._context_spin.setValue(61)
            controller.update_profile()
            updated = controller.store.get(saved.profile_id)
            self.assertEqual(updated.filters.context, 61)
            restarted.close_tab(0)

            def rename(dialog):
                dialog.name_input.setText("Renamed after restart")
                dialog.accept()
                return dialog.result()

            with patch.object(ProfileNameDialog, "exec", rename):
                controller.rename(updated)
            renamed = controller.store.get(saved.profile_id)
            self.assertEqual(renamed.name, "Renamed after restart")
            self.assertEqual(renamed.filters, updated.filters)
            with patch.object(ProfileDeletionDialog, "exec", return_value=QDialog.DialogCode.Accepted):
                controller.delete(renamed)
            self.assertEqual(controller.store.load_all().profiles, ())
        finally:
            retire_window(restarted)
