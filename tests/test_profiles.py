import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSaveFile, QStandardPaths

from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot
from logreader.profiles import Profile, ProfileError, ProfileStore, profile_directory


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ProfileStore(self.root / "profiles")
        self.profile = Profile("Database blå", FilterSnapshot(
            enabled_patterns=("error", "database_connections"), context=17, max_lines_scanned=23456,
            combined_view=False, separate_entries=False,
            custom_patterns=(PatternSnapshot("tenant-ø", enabled=False, exclusive=True, match_case=True),),
            regex_patterns=(PatternSnapshot(r"timeout\d+", exclude=True),),
        ))

    def test_save_reload_and_update_use_one_versioned_file_with_stable_identity(self):
        self.assertFalse(self.store.directory.exists())
        self.assertEqual(self.store.load_all().profiles, ())
        self.assertFalse(self.store.directory.exists())
        path = self.store.save(self.profile)
        self.assertEqual(path.name, self.profile.profile_id + ".lrprof")
        raw = path.read_text(encoding="utf-8")
        self.assertIn("blå", raw)
        data = json.loads(raw)
        self.assertEqual(data["format"], "logreader-profile")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["filters"], self.profile.filters.to_dict())
        reopened = ProfileStore(self.store.directory)
        self.assertEqual(reopened.load(path), self.profile)
        updated = replace(self.profile, name="Renamed", filters=replace(self.profile.filters, context=99))
        self.assertEqual(reopened.save(updated), path)
        self.assertEqual(reopened.load(path), updated)
        self.assertEqual(list(self.store.directory.iterdir()), [path])

    def test_default_location_and_override_do_not_depend_on_the_checkout(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "logreader.profiles.QStandardPaths.writableLocation", return_value=str(self.root / "appdata"),
        ) as location:
            self.assertEqual(profile_directory(), self.root / "appdata" / "Logreader" / "profiles")
            location.assert_called_once_with(QStandardPaths.StandardLocation.GenericDataLocation)
        override = self.root / "isolated"
        with patch.dict(os.environ, {"LOGREADER_PROFILE_DIR": str(override)}), patch(
            "logreader.profiles.QStandardPaths.writableLocation", side_effect=AssertionError("used default"),
        ):
            store = ProfileStore()
            self.assertEqual(store.save(self.profile).parent, override)
        with patch.dict(os.environ, {"LOGREADER_PROFILE_DIR": " "}):
            with self.assertRaisesRegex(ProfileError, "cannot be empty"):
                ProfileStore()

    def test_damaged_files_do_not_hide_valid_profiles_and_errors_identify_each_file(self):
        self.store.save(self.profile)
        another = Profile("Alpha", FilterSnapshot())
        self.store.save(another)
        invalid_version = self.profile.to_dict()
        invalid_version["version"] = 999
        bad_files = {
            "broken.lrprof": b"{", "encoding.lrprof": b"\xff",
            "version.lrprof": json.dumps(invalid_version).encode(),
            "empty.LRPROF": b"{}",
        }
        for name, contents in bad_files.items():
            (self.store.directory / name).write_bytes(contents)
        (self.store.directory / "unrelated.json").write_text("{}")
        (self.store.directory / "folder.lrprof").mkdir()
        result = self.store.load_all()
        self.assertEqual(result.profiles, (another, self.profile))
        self.assertEqual({error.path.name for error in result.errors}, set(bad_files))
        for error in result.errors:
            self.assertIn(error.path.name, error.message)

    def test_rejects_invalid_metadata_and_duplicate_identity(self):
        for field, value, message in (
            ("format", "other", "not a Logreader profile"), ("version", True, "version"),
            ("id", "../escape", "Profile ID"), ("name", " ", "Profile name"),
            ("name", "two\nlines", "one line"), ("filters", [], "snapshot must be an object"),
        ):
            with self.subTest(field=field):
                data = self.profile.to_dict()
                data[field] = value
                with self.assertRaisesRegex(ProfileError, message):
                    Profile.from_dict(data)
        data = self.profile.to_dict()
        del data["filters"]
        with self.assertRaisesRegex(ProfileError, "missing: filters"):
            Profile.from_dict(data)
        path = self.store.save(self.profile)
        (self.store.directory / "copy.lrprof").write_bytes(path.read_bytes())
        result = self.store.load_all()
        self.assertEqual(result.profiles, (self.profile,))
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Duplicate profile ID", result.errors[0].message)

    def test_active_regex_is_validated_and_disabled_regex_is_preserved(self):
        filters = FilterSnapshot(regex_patterns=(PatternSnapshot("[", enabled=False, exclude=True),))
        profile = Profile("Disabled regex", filters)
        self.assertEqual(self.store.load(self.store.save(profile)), profile)
        data = profile.to_dict()
        data["filters"]["regex_patterns"][0]["enabled"] = True
        path = self.store.directory / "invalid.lrprof"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "Invalid regex in entry 1"):
            self.store.load(path)
        with self.assertRaisesRegex(ProfileError, "Invalid regex in entry 1"):
            Profile("Invalid", FilterSnapshot(regex_patterns=(PatternSnapshot("["),)))

    def test_failed_writes_keep_the_previous_profile_and_remove_temporary_output(self):
        path = self.store.save(self.profile)
        before = path.read_bytes()
        updated = replace(self.profile, name="New name")
        for failure in ("write", "commit"):
            class FailedSaveFile(QSaveFile):
                def write(self, data):
                    if failure == "write":
                        super().write(data[:len(data) // 2])
                        return -1
                    return super().write(data)

                def commit(self):
                    self.cancelWriting()
                    return super().commit()

                def errorString(self):
                    return "Simulated disk failure"

            with self.subTest(failure=failure), patch("logreader.profiles.QSaveFile", FailedSaveFile):
                with self.assertRaisesRegex(ProfileError, "Could not save.*Simulated disk failure"):
                    self.store.save(updated)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(self.store.directory.iterdir()), [path])

    def test_io_errors_are_reported_without_creating_profiles_elsewhere(self):
        blocked = self.root / "not-a-folder"
        blocked.write_text("occupied")
        store = ProfileStore(blocked)
        with self.assertRaisesRegex(ProfileError, "Could not save profile"):
            store.save(self.profile)
        with self.assertRaisesRegex(ProfileError, "Could not read profiles folder"):
            store.load_all()
        with self.assertRaisesRegex(ProfileError, "Could not load profile 'missing.lrprof'"):
            store.load(self.root / "missing.lrprof")
        with self.assertRaisesRegex(ProfileError, "must use the .lrprof extension"):
            store.load(self.root / "settings.json")
        self.assertEqual(list(self.root.iterdir()), [blocked])

    def test_management_preserves_identity_and_uses_the_actual_profile_file(self):
        original_path = self.store.create(self.profile)
        path = original_path.rename(self.store.directory / "readable-name.lrprof")
        filters = replace(self.profile.filters, context=51)
        updated = self.store.update(self.profile, filters)
        renamed = self.store.rename(updated, "Renamed")
        self.assertEqual(renamed.profile_id, self.profile.profile_id)
        self.assertEqual(renamed.filters, filters)
        self.assertEqual(self.store.get(renamed.profile_id), renamed)
        self.assertEqual(self.store.load(path), renamed)
        self.assertEqual(list(self.store.directory.iterdir()), [path])
        self.store.delete(renamed)
        self.assertEqual(list(self.store.directory.iterdir()), [])
        with self.assertRaisesRegex(ProfileError, "no longer available"):
            self.store.update(renamed, filters)
        self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_management_rejects_name_collisions_stale_records_and_ambiguous_identity(self):
        path = self.store.create(self.profile)
        before = path.read_bytes()
        with self.assertRaisesRegex(ProfileError, "name already exists"):
            self.store.create(Profile(" DATABASE BLÅ ", FilterSnapshot()))
        with self.assertRaisesRegex(ProfileError, "already exists"):
            self.store.create(replace(self.profile, name="Same ID"))
        another = Profile("Other", FilterSnapshot())
        self.store.create(another)
        with self.assertRaisesRegex(ProfileError, "name already exists"):
            self.store.rename(self.profile, "other")
        self.assertEqual(path.read_bytes(), before)
        current = replace(self.profile, filters=replace(self.profile.filters, context=88))
        self.store.save(current)
        for operation in (lambda: self.store.update(self.profile, FilterSnapshot()),
                          lambda: self.store.rename(self.profile, "Rename"),
                          lambda: self.store.delete(self.profile)):
            with self.assertRaisesRegex(ProfileError, "has changed"):
                operation()
            self.assertEqual(self.store.load(path), current)
        duplicate = self.store.directory / "duplicate.lrprof"
        duplicate.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ProfileError, "Multiple files"):
            self.store.delete(current)
        self.assertTrue(path.exists())
        self.assertTrue(duplicate.exists())

    def test_delete_failure_preserves_the_saved_profile(self):
        path = self.store.create(self.profile)
        with patch.object(Path, "unlink", side_effect=PermissionError("Access denied")):
            with self.assertRaisesRegex(ProfileError, "Could not delete.*Access denied"):
                self.store.delete(self.profile)
        self.assertEqual(self.store.load(path), self.profile)
