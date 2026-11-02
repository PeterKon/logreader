import os
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qt_helpers import qt_application, retire_window, wait_for_load, wait_until
from logreader.document_session import LoadPhase
from logreader.file_loader import LoadedLog, load_log
from logreader.filter_snapshot import FilterSnapshot
from logreader.session_snapshot import BookmarkSnapshot, SessionTab
from logreader.sessions import SessionStore
from logreader.ui.document_page import DocumentPage
from logreader.ui.qt_app import LogreaderWindow
from logreader.ui.results.results_model import SourceLocation


class WorkspaceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SessionStore(self.root / "sessions")
        self.window = LogreaderWindow()
        self.addCleanup(retire_window, self.window)

    def log(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(f"{name} line {i}" for i in range(1, 6)), encoding="utf-8")
        return path

    def save_workspace(self):
        path = self.store.save(*self.window.capture_session())
        return self.store.load(path)

    def test_rejected_replacements_keep_the_original_tab_and_its_records(self):
        opened = self.log("opened.log")
        bookmark = BookmarkSnapshot(1, sha256(b"original").hexdigest(), "First", "Two\nlines")
        tab = SessionTab(self.root / "missing.log", FilterSnapshot(context=12),
                         "draft", "[", (bookmark,))
        saved = self.store.load(self.store.save((tab, SessionTab(opened, FilterSnapshot())), 0))
        self.window.restore_session(saved)
        page = self.window._document
        wait_for_load(page)
        error = page.session.load_error
        unreadable = self.root / "unreadable.log"
        unreadable.write_bytes(b"\xff\xfe\x00")
        for selected in ("", str(opened.parent / "sub" / ".." / opened.name), str(unreadable)):
            with self.subTest(selected=selected), patch("logreader.ui.qt_app.QFileDialog.getOpenFileName",
                                                        return_value=(selected, "")) as picker:
                page.file_warning.replace.click()
                picker.assert_called_once()
                wait_for_load(page)
                self.assertIs(self.window._document, page)
                self.assertEqual(self.save_workspace().tabs, saved.tabs)
                self.assertEqual(page.session.load_error, error)
                self.assertTrue(page.file_warning.message.toPlainText().startswith(f"{tab.path}\n{error}"))
                self.assertTrue(page.file_warning.retry.isEnabled())
                if selected:
                    self.assertIn("another tab" if selected != str(unreadable) else "Invalid UTF-16",
                                  page.file_warning.message.toPlainText())

    def test_open_file_can_claim_a_candidate_while_replacement_is_reading(self):
        tab = SessionTab(self.root / "missing.log", FilterSnapshot())
        self.window.restore_session(self.store.load(self.store.save((tab,), 0)))
        page = self.window._document
        wait_for_load(page)
        candidate = self.log("candidate.log")
        started, release = Event(), Event()

        def hold_first(path, **options):
            if not started.is_set():
                started.set()
                if not release.wait(10):
                    raise TimeoutError("Candidate was not released")
            return load_log(path, **options)

        with patch("logreader.workers.load_worker.load_log", side_effect=hold_first):
            try:
                with patch("logreader.ui.qt_app.QFileDialog.getOpenFileName", return_value=(str(candidate), "")):
                    page.file_warning.replace.click()
                wait_until(started.is_set)
                self.assertEqual(self.save_workspace().tabs, (tab,))
                self.assertFalse(page.file_warning.replace.isEnabled())
                with patch("logreader.ui.qt_app.QFileDialog.getOpenFileNames", return_value=([str(candidate)], "")):
                    self.window._open_button.click()
                other = self.window._document
                self.assertIsNot(other, page)
            finally:
                release.set()
            wait_for_load(page)
            wait_for_load(other)
        self.assertEqual(page.capture_session_tab(), tab)
        self.assertEqual(page.session.load_phase, LoadPhase.FAILED)
        self.assertIn("another tab", page.file_warning.message.toPlainText())
        self.assertEqual(other.session.path, candidate)
        self.assertEqual(other.session.load_phase, LoadPhase.LOADED)

    def test_restores_display_order_selection_and_bookmarks_during_partial_loads(self):
        paths = [self.log(name) for name in ("z/service.log", "offline.log", "a/service.log")]
        self.window.load_files(paths)
        for index in range(3):
            page = self.window._pages.widget(index)
            wait_for_load(page)
            page.filter_panel.restore_snapshot(FilterSnapshot(context=index, max_lines_scanned=index + 1))
            page.filter_panel.set_pattern_drafts(f" draft {index} ", f"({index}")
            source = SourceLocation(page.session.snapshot_id, 5)
            bookmarks = page.results_view.bookmarks
            self.assertTrue(bookmarks.add(source, f"Bookmark {index}"))
            bookmarks.items[source].note = f"Note {index}\nsecond line"
        self.window._tabs.setCurrentIndex(2)
        saved = self.save_workspace()
        self.assertEqual([tab.path for tab in saved.tabs], paths)
        self.assertEqual(saved.selected_tab, 2)
        self.window.load_file(self.log("extra.log"))
        wait_for_load(self.window._document)
        paths[1].unlink()

        release_first, release_last = Event(), Event()
        reads = []

        def gated_load(path, *, max_lines_scanned, cancellation):
            reads.append((path, max_lines_scanned))
            gate = {paths[0]: release_first, paths[2]: release_last}.get(path)
            if gate is not None and not gate.wait(10):
                raise TimeoutError("Test did not release the source")
            return load_log(path, max_lines_scanned=max_lines_scanned, cancellation=cancellation)

        with patch("logreader.workers.load_worker.load_log", side_effect=gated_load):
            try:
                self.window.restore_session(saved)
                pages = [self.window._pages.widget(i) for i in range(self.window._tabs.count())]
                self.assertEqual([page.session.path for page in pages], paths)
                self.assertIs(self.window._document, pages[2])
                wait_until(lambda: bool(reads))
                self.assertEqual(reads, [(paths[0], 1)])
                self.assertTrue(pages[1].load_queued and pages[2].load_queued)
                pending = self.save_workspace()
                self.assertEqual((pending.tabs, pending.selected_tab), (saved.tabs, 2))

                release_first.set()
                wait_until(lambda: len(reads) == 3)
                self.assertEqual([page.session.load_phase for page in pages],
                                 [LoadPhase.LOADED, LoadPhase.FAILED, LoadPhase.LOADING])
                partial = self.save_workspace()
                self.assertEqual((partial.tabs, partial.selected_tab), (saved.tabs, 2))
            finally:
                release_first.set()
                release_last.set()
            wait_for_load(pages[2])

        self.assertEqual(reads, list(zip(paths, (1, 2, 3))))
        self.assertEqual([len(page.session.lines) for page in pages], [1, 0, 3])
        self.assertTrue(all(page.session.analysis is None for page in pages))
        self.assertEqual(self.window.capture_session(), (saved.tabs, 2))
        self.assertIn("(Failed)", self.window._tabs.tabText(1))
        self.assertIs(self.window._document, pages[2])
        self.window.load_file(paths[0])
        self.assertIs(self.window._document, pages[0])
        self.assertEqual(self.window._tabs.count(), 3)

    def test_invalid_session_or_resolved_alias_preserves_current_tabs_and_selection(self):
        paths = [self.log("first.log"), self.log("second.log")]
        self.window.load_files(paths)
        self.window._tabs.setCurrentIndex(1)
        active = self.window._document
        saved = self.save_workspace()
        invalid = saved.to_dict()
        invalid["tabs"][1]["filters"]["max_lines_scanned"] = 0
        with self.assertRaisesRegex(ValueError, "Tab 2"):
            self.window.restore_session(invalid)

        alias = self.root / "alias.log"
        collision = replace(saved, tabs=(saved.tabs[0], replace(saved.tabs[1], path=alias)))
        # Simulate a junction even where the test process cannot create symlinks.
        resolve = Path.resolve
        with patch.object(Path, "resolve", lambda path: paths[0] if path == alias else resolve(path)):
            with self.assertRaisesRegex(ValueError, "duplicate tab paths"):
                self.window.restore_session(collision)
        self.assertIs(self.window._document, active)
        self.assertEqual(self.window.capture_session(), (saved.tabs, 1))
        for index in range(len(paths)):
            page = self.window._pages.widget(index)
            wait_for_load(page)
            self.assertEqual(page.session.load_phase, LoadPhase.LOADED)

    def test_replacing_workspace_cancels_old_jobs_and_ignores_late_signals_for_the_same_path(self):
        shared, obsolete = self.log("shared.log"), self.log("obsolete.log")
        replacement = SessionTab(shared, FilterSnapshot(context=17, max_lines_scanned=1))
        saved = self.store.load(self.store.save((replacement,), 0))
        started, release = Event(), Event()
        reads = []

        def hold_old_load(path, *, max_lines_scanned, cancellation):
            reads.append(path)
            if len(reads) == 1:
                started.set()
                if not release.wait(10):
                    raise TimeoutError("Test did not release the old load")
                return LoadedLog(("obsolete contents",), "UTF-8")
            return load_log(path, max_lines_scanned=max_lines_scanned, cancellation=cancellation)

        with patch("logreader.workers.load_worker.load_log", side_effect=hold_old_load):
            try:
                self.window.load_files((shared, obsolete))
                wait_until(started.is_set)
                old = self.window._document
                running = old._load_worker
                queued = self.window._pages.widget(1)._load_worker
                self.window.restore_session(saved)
                current = self.window._document
                self.assertIsNot(current, old)
                self.assertTrue(running.cancellation.is_cancelled and queued.cancellation.is_cancelled)
                self.assertTrue(current.load_queued)
                running.signals.completed.emit(running.request_id, LoadedLog(("late contents",), "UTF-8"))
                running.signals.failed.emit(running.request_id, "late failure")
                self.assertIsNone(old.session.path)
                self.assertEqual(current.session.load_phase, LoadPhase.LOADING)
                self.assertEqual(self.window.capture_session(), ((replacement,), 0))
            finally:
                release.set()
            wait_for_load(current)
        self.assertEqual(reads, [shared, shared])
        self.assertEqual(current.session.lines, ("shared.log line 5",))
        self.assertIsNone(current.session.analysis)

    def test_page_setup_failure_discards_staged_pages_and_keeps_original_workspace(self):
        self.window.load_file(self.log("current.log"))
        original = self.window._document
        wait_for_load(original)
        snapshot = self.window.capture_session()
        tabs = tuple(SessionTab(self.log(name), FilterSnapshot()) for name in ("one.log", "two.log"))
        saved = self.store.load(self.store.save(tabs, 1))
        restore_tab = DocumentPage.restore_session_tab
        staged = []

        def fail_second(page, tab):
            staged.append(page)
            if tab == tabs[1]:
                raise RuntimeError("Page setup failed")
            restore_tab(page, tab)

        with patch.object(DocumentPage, "restore_session_tab", fail_second):
            with self.assertRaisesRegex(RuntimeError, "Page setup failed"):
                self.window.restore_session(saved)
        self.assertTrue(all(page._disposed for page in staged))
        self.assertIs(self.window._document, original)
        self.assertEqual(self.window.capture_session(), snapshot)
