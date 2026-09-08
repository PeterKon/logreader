import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QThreadPool
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton, QSpinBox

    from logreader.config import APP_VERSION, LogreaderConfig
    from logreader.document_session import AnalysisPhase
    from logreader.qt_app import LogreaderWindow
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.window = LogreaderWindow()

    def tearDown(self):
        for index in range(self.window._tabs.count()):
            page = self.window._pages.widget(index)
            page.session.cancel_request()
            page._finish_analysis_request()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def make_log(self, name, text="ERROR: example\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def open_log(self, name, text="ERROR: example\n"):
        path = self.make_log(name, text)
        self.assertTrue(self.window.load_file(path))
        return self.window._document

    def wait_for_completion(self, spy):
        for _ in range(500):
            self.app.processEvents()
            if spy.count():
                return
            QTest.qWait(10)
        self.fail("Analysis did not finish")

    def test_empty_state_and_file_picker_open_without_analysis(self):
        self.window.show()
        self.app.processEvents()
        self.assertIsNone(self.window._document)
        self.assertEqual(self.window._tabs.count(), 0)
        self.assertTrue(self.window._empty_page.isVisible())
        self.assertFalse(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.windowTitle(), APP_VERSION)
        self.window.analyze_current()  # Safe in the empty state.
        path = self.make_log("empty.log", "")
        with patch("logreader.qt_app.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            self.window._open_button.click()
        page = self.window._document
        self.assertEqual(self.window._tabs.count(), 1)
        self.assertFalse(self.window._empty_page.isVisible())
        self.assertTrue(self.window._tabs.isVisible())
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertEqual(page.session.path, path)
        self.assertEqual(page.session.lines, ())
        self.assertIsNone(page.session.analysis)
        self.assertEqual(page.session.phase, AnalysisPhase.IDLE)
        self.assertEqual(page.results_view.editor.toPlainText(), "")

    def test_normalized_duplicate_selects_existing_page_without_reloading(self):
        first = self.open_log("first.log")
        self.open_log("second.log")
        variants = [
            first.session.path,
            self.root / "subdir" / ".." / "first.log",
            Path(os.path.relpath(first.session.path)),
        ]
        if os.name == "nt":
            variants.append(Path(str(first.session.path).upper()))
        with patch("logreader.qt_app.load_log", side_effect=AssertionError("Duplicate reread")):
            for path in variants:
                self.assertTrue(self.window.load_file(path))
                self.assertIs(self.window._document, first)
                self.assertEqual(self.window._tabs.count(), 2)

    def test_identical_filenames_have_distinct_labels_and_full_path_tooltips(self):
        first = self.open_log("one/shared/server.log")
        self.assertEqual(self.window._tabs.tabText(0), "server.log")
        second = self.open_log("two/shared/server.log")
        self.assertIs(self.window._document, second)
        self.assertNotEqual(self.window._tabs.tabText(0), self.window._tabs.tabText(1))
        for index, page in enumerate((first, second)):
            self.assertIn("server.log", self.window._tabs.tabText(index))
            self.assertEqual(self.window._tabs.tabToolTip(index), str(page.session.path))

    def test_switching_preserves_filters_drafts_and_results_interaction(self):
        first = self.open_log(
            "first.log", "".join(f"ERROR: first {i} {'x' * 200}\n" for i in range(300))
        )
        self.window.show()
        self.app.processEvents()
        first.findChild(QSpinBox, "contextSpin").setValue(1)
        first.findChild(QCheckBox, "combinedViewCheck").setChecked(False)
        first.findChild(QLineEdit, "customPattern").setText("noise")
        first.findChild(QPushButton, "customPatternAddButton").click()
        # Exercise the per-item match-case and exclusion flags as well.
        first.findChild(QPushButton, "customPatternMatchCaseButton").setChecked(True)
        first.findChild(QPushButton, "customPatternExcludeButton").setChecked(True)
        first.findChild(QLineEdit, "regexPattern").setText("ignored.*")
        first.findChild(QPushButton, "regexPatternAddButton").click()
        first.findChild(QPushButton, "regexPatternExcludeButton").setChecked(True)
        first.findChild(QLineEdit, "customPattern").setText("unfinished text")
        first.findChild(QLineEdit, "regexPattern").setText("unfinished [")
        before_config = first.build_config()
        done = QSignalSpy(first.analysis_finished)
        self.window.analyze_current()
        self.wait_for_completion(done)
        view = first.results_view
        view.findChild(QLineEdit, "resultsSearch").setText("first")
        view.search_results()
        view.find_next()
        editor = view.editor
        cursor = editor.textCursor()
        cursor.setPosition(100)
        cursor.setPosition(125, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.verticalScrollBar().setValue(40)
        before_output = editor.toPlainText()
        before_selection = (cursor.position(), cursor.anchor())
        before_scroll = editor.verticalScrollBar().value()
        editor.horizontalScrollBar().setValue(30)
        before_horizontal = editor.horizontalScrollBar().value()
        before_match = view._current_search_match
        before_matches = view._search_matches
        self.assertGreater(before_scroll, 0)
        self.assertGreater(before_horizontal, 0)
        self.assertGreater(len(before_matches), 100)
        self.assertEqual(before_config.custom_pattern_match_case, (True,))
        self.assertEqual(before_config.custom_pattern_exclude, (True,))
        self.assertEqual(before_config.regex_pattern_exclude, (True,))

        second = self.open_log("second.log")
        self.assertEqual(second.build_config(), LogreaderConfig())
        self.assertEqual(second.findChild(QLineEdit, "customPattern").text(), "")
        self.assertEqual(second.findChild(QLineEdit, "regexPattern").text(), "")
        self.assertEqual(second.findChild(QLineEdit, "resultsSearch").text(), "")
        second.findChild(QCheckBox, "lineWrapCheck").setChecked(True)
        second.findChild(QSpinBox, "contextSpin").setValue(8)
        self.window._select_document(first)
        self.app.processEvents()
        self.assertEqual(first.build_config(), before_config)
        self.assertEqual(first.findChild(QLineEdit, "customPattern").text(), "unfinished text")
        self.assertEqual(first.findChild(QLineEdit, "regexPattern").text(), "unfinished [")
        self.assertEqual(editor.toPlainText(), before_output)
        self.assertEqual((editor.textCursor().position(), editor.textCursor().anchor()), before_selection)
        self.assertEqual(editor.verticalScrollBar().value(), before_scroll)
        self.assertEqual(editor.horizontalScrollBar().value(), before_horizontal)
        self.assertEqual(view._current_search_match, before_match)
        self.assertIs(view._search_matches, before_matches)
        self.assertEqual(view.findChild(QLineEdit, "resultsSearch").text(), "first")
        self.assertFalse(first.findChild(QCheckBox, "lineWrapCheck").isChecked())
        self.window._select_document(second)
        self.assertTrue(second.findChild(QCheckBox, "lineWrapCheck").isChecked())
        self.assertEqual(second.build_config().context, 8)

    def test_failed_open_does_not_create_tab_or_disturb_existing_document(self):
        with patch("logreader.qt_app.QMessageBox.critical") as error:
            self.assertFalse(self.window.load_file(self.root / "missing.log"))
            self.assertEqual(self.window._tabs.count(), 0)
            self.assertIs(self.window._workspace.currentWidget(), self.window._empty_page)
            first = self.open_log("first.log")
            self.assertFalse(self.window.load_file(self.root / "missing.log"))
            self.assertEqual(error.call_count, 2)
        self.assertEqual(self.window._tabs.count(), 1)
        self.assertIs(self.window._document, first)

    def test_background_completion_and_switching_keep_correct_owner_and_status(self):
        first = self.open_log("first.log", "ERROR: first\n")
        workers = []
        with patch.object(QThreadPool, "start", side_effect=workers.append):
            self.window.analyze_current()
            second = self.open_log("second.log", "ERROR: second\n")
            self.window.analyze_current()
        self.assertEqual(workers[0].request_id, workers[1].request_id)
        done = QSignalSpy(second.analysis_finished)
        workers[1].run()
        self.wait_for_completion(done)
        status = self.window.statusBar().currentMessage()
        first_done = QSignalSpy(first.analysis_finished)
        workers[0].run()
        self.wait_for_completion(first_done)
        self.assertIs(self.window._document, second)
        self.assertEqual(self.window.statusBar().currentMessage(), status)
        self.assertIn("ERROR: second", second.results_view.editor.toPlainText())
        self.window._select_document(first)
        self.assertIn("ERROR: first", first.results_view.editor.toPlainText())
        self.assertEqual(self.window.statusBar().currentMessage(), first.status_message)
        self.assertIn("first.log", self.window.windowTitle())
        first.results_view.set_maximized(True)
        self.window._select_document(second)
        self.assertFalse(second.results_view.is_maximized)
        self.window._select_document(first)
        self.assertTrue(first.results_view.is_maximized)
        self.assertFalse(self.window._file_controls.isHidden())
        self.assertFalse(self.window._tabs.isHidden())
