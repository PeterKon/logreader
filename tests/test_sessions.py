import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSaveFile

from logreader.core import CategoryIdentity
from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot
from logreader.session_snapshot import BookmarkSnapshot, SavedSession, SessionTab
from logreader.sessions import SessionError, SessionStore, session_directory


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SessionStore(self.root / "sessions")
        self.instant = datetime(2026, 11, 2, 17, 4, 9, 123456, tzinfo=timezone.utc)
        self.log = self.root / "blå.log"
        line = "sensitive log contents"
        self.log.write_text(line, encoding="utf-8")
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        self.tabs = (
            SessionTab(self.log, FilterSnapshot(
                custom_patterns=(PatternSnapshot("hide", enabled=False, exclude=True),),
                regex_patterns=(PatternSnapshot("["),), max_lines_scanned=15,
            ), custom_draft="  uncommitted  ", regex_draft="(?", bookmarks=(
                BookmarkSnapshot(9, digest, "Preferred result", "line one\n\nblå\t ",
                                 CategoryIdentity("literal", "needle", True, 1), converted=True),
                BookmarkSnapshot(3, digest, "Source", convert_when_shown=True),
            )),
            SessionTab(self.root / "missing.log", FilterSnapshot(context=2)),
        )

    def save(self, name=None, **options):
        return self.store.save(self.tabs, 1, name=name, saved_at=self.instant, **options)

    def test_round_trip_preserves_order_drafts_filters_notes_and_locations(self):
        path = self.save("Investigation")
        self.assertEqual(path, self.store.directory / "Investigation.lrsess")
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("sensitive log contents", raw)
        data = json.loads(raw)
        self.assertEqual(set(data), {"format", "version", "name", "saved_at", "selected_tab", "tabs"})
        self.assertEqual((data["format"], data["version"]), ("logreader-session", 1))
        self.assertEqual(set(data["tabs"][0]), {"path", "filters", "custom_draft", "regex_draft", "bookmarks"})
        self.assertEqual(data["tabs"][0]["filters"], self.tabs[0].filters.to_dict())
        self.log.unlink()
        restored = SessionStore(self.store.directory).load(path)
        self.assertEqual(restored, SavedSession("Investigation", self.instant, 1, self.tabs))

    def test_default_location_and_empty_store(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "logreader.local_storage.QStandardPaths.writableLocation", return_value=str(self.root),
        ):
            self.assertEqual(session_directory(), self.root / "Logreader" / "sessions")
        with patch.dict(os.environ, {"LOGREADER_SESSION_DIR": str(self.store.directory)}):
            self.assertEqual(SessionStore().directory, self.store.directory)
        self.assertEqual(self.store.load_all().sessions, ())
        self.assertFalse(self.store.directory.exists())

    def test_same_second_saves_claim_distinct_local_names_even_across_writers(self):
        base = self.instant.astimezone().strftime("%Y-%m-%d %H-%M-%S")
        self.assertEqual(self.store.default_name(self.instant), base)
        with ThreadPoolExecutor(max_workers=3) as pool:
            paths = tuple(pool.map(lambda _: self.save(), range(3)))
        self.assertEqual({path.stem for path in paths}, {base, f"{base} (2)", f"{base} (3)"})
        self.assertEqual([self.store.load(path).name for path in paths], [path.stem for path in paths])
        self.assertEqual(self.store.default_name(self.instant), f"{base} (4)")

    def test_lists_by_embedded_instant_and_reports_each_damaged_file(self):
        earlier = self.save("A")
        later = self.store.save(self.tabs, 0, name="Z", saved_at=self.instant + timedelta(hours=1))
        # The local clock in the later file appears earlier than the UTC clock in A.
        data = json.loads(later.read_text(encoding="utf-8"))
        data["saved_at"] = (self.instant + timedelta(hours=1)).astimezone(
            timezone(timedelta(hours=-6)),
        ).isoformat()
        later.write_text(json.dumps(data), encoding="utf-8")
        renamed = later.rename(self.store.directory / "renamed.LRSESS")
        os.utime(renamed, (10, 10))
        broken = self.store.directory / "broken.lrsess"
        broken.write_bytes(b"\xff")
        newer = self.store.directory / "future.lrsess"
        newer.write_text(json.dumps({**data, "version": 2}), encoding="utf-8")
        (self.store.directory / "other.lrprof").write_text("{}")
        found = self.store.load_all()
        self.assertEqual([(entry.path, entry.session.name) for entry in found.sessions],
                         [(renamed, "Z"), (earlier, "A")])
        self.assertEqual({error.path for error in found.errors}, {broken, newer})
        with self.assertRaisesRegex(SessionError, "Unsupported session version"):
            self.store.load(newer)

    def test_whole_session_rejected_for_invalid_tab_or_bookmark(self):
        original = self.save("Invalid")
        raw = original.read_text(encoding="utf-8")
        for field, changes, message in (
            ("session", {"version": True}, "version"),
            ("session", {"saved_at": "2026-11-02T17:04:09"}, "time zone"),
            ("session", {"selected_tab": True}, "Selected tab"),
            ("session", {"selected_tab": 2}, "Selected tab"),
            ("session", {"tabs": []}, "at least one tab"),
            ("tab", {"path": "relative.log"}, "Tab 2.*absolute"),
            ("tab", {"path": str(self.root / "other" / ".." / self.log.name)}, "duplicate tab paths"),
            ("tab", {"regex_draft": False}, "Tab 2.*drafts"),
            ("tab", {"filters": {}}, "Tab 2.*Filter snapshot"),
            ("tab", {"bookmarks": None}, "Tab 2.*Bookmark"),
            ("tab", {"results": "stored content"}, "Tab 2.*Unknown tab fields"),
            ("bookmark", {"line": True}, "Bookmark 1.*positive integer"),
            ("bookmark", {"note": None}, "Bookmark 1.*text note"),
            ("bookmark", {"category": None}, "Bookmark 1.*converted"),
            ("bookmark", {"line_sha256": "line text"}, "Bookmark 1.*digest"),
            ("bookmark", {"convert_when_shown": True}, "Bookmark 1.*source bookmark"),
            ("category", {"kind": "other"}, "category kind"),
            ("category", {"occurrence": False}, "category options"),
        ):
            with self.subTest(field=field, changes=changes):
                data = json.loads(raw)
                bookmark = data["tabs"][0]["bookmarks"][0]
                target = {"session": data, "tab": data["tabs"][1],
                          "bookmark": bookmark, "category": bookmark["category"]}[field]
                target.update(changes)
                original.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(SessionError, message):
                    self.store.load(original)
        data = json.loads(raw)
        data["tabs"][0]["bookmarks"][1]["line"] = data["tabs"][0]["bookmarks"][0]["line"]
        original.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(SessionError, "duplicate bookmarked lines"):
            self.store.load(original)

    def test_overwrite_requires_an_explicit_name_and_failed_commit_preserves_file(self):
        path = self.save("Keep")
        before = path.read_bytes()
        with self.assertRaisesRegex(SessionError, "already exists"):
            self.save("Keep")
        with self.assertRaisesRegex(SessionError, "name to overwrite"):
            self.save(overwrite=True)
        with patch.object(QSaveFile, "commit", return_value=False):
            with self.assertRaisesRegex(SessionError, "Could not save"):
                self.store.save(self.tabs, 0, name="Keep", overwrite=True)
            with self.assertRaisesRegex(SessionError, "Could not save"):
                self.save("New")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.store.directory.iterdir()), [path])
        self.assertEqual(self.store.save(self.tabs, 0, name="Keep", overwrite=True), path)
        self.assertEqual(self.store.load(path).selected_tab, 0)

    def test_names_cannot_escape_the_sessions_folder_or_target_a_windows_device(self):
        for name in ("../escape", str(self.root / "escape"), "NUL.old", "ends.", "bad:name"):
            with self.subTest(name=name), self.assertRaisesRegex(SessionError, "filename"):
                self.save(name)
        self.assertFalse(self.store.directory.exists())
