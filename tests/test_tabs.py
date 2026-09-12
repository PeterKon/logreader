import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import wait_for_search, capture_analysis, wait_for_load
    from PySide6.QtCore import QThreadPool, Qt
    from PySide6.QtGui import QKeySequence, QTextCursor
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton, QSpinBox, QTabBar

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
        wait_for_load(self.window._document)
        return self.window._document

    def wait_for_completion(self, spy):
        for _ in range(500):
            self.app.processEvents()
            if spy.count():
                return
            QTest.qWait(10)
        self.fail("Analysis did not finish")

    def test_empty_state_and_file_picker_open_without_analysis(self):
        self.assertEqual(self.window.size().width(), 975)
        self.assertEqual(self.window.size().height(), 1097)
        self.window.show()
        self.app.processEvents()
        self.assertIsNone(self.window._document)
        self.assertEqual(self.window._tabs.count(), 0)
        self.assertTrue(self.window._empty_page.isVisible())
        self.assertEqual(self.window._open_button.text(), "&Open file")
        self.assertIs(self.window._open_button.parentWidget(), self.window._tab_controls)
        self.assertIs(self.window._file_controls.layout().itemAt(0).widget(), self.window._analyze_button)
        self.assertIs(self.window._file_controls.layout().itemAt(1).widget(), self.window._path_label)
        self.assertEqual(self.window._empty_heading.text(), "Open or drop log files")
        self.assertEqual(self.window._empty_subtitle.text(), "Each file opens in its own tab.")
        self.assertFalse(self.window._action_margin.isVisible())
        self.assertTrue(self.window._empty_tab_label.isVisible())
        self.assertTrue(self.window._empty_version_label.isVisible())
        self.assertEqual(self.window._empty_version_label.text(), APP_VERSION)
        self.assertEqual(self.window.statusBar().currentMessage(), "Ready")
        self.assertEqual(
            self.window._empty_heading.alignment(),
            Qt.AlignmentFlag.AlignCenter,
        )
        self.assertTrue(self.window._empty_heading.font().bold())
        for width, height in ((1080, 760), (900, 640)):
            self.window.resize(width, height)
            self.app.processEvents()
            center = self.window._empty_page.mapTo(
                self.window.centralWidget(), self.window._empty_page.contentsRect().center(),
            )
            expected = self.window.centralWidget().rect().center()
            self.assertLessEqual(abs(center.x() - expected.x()), 1)
            self.assertLessEqual(abs(center.y() - expected.y()), 1)
        self.assertEqual(
            self.window._empty_heading.font().pointSizeF(),
            self.window.font().pointSizeF() + 6,
        )
        self.assertFalse(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.windowTitle(), APP_VERSION)
        self.window.analyze_current()  # Safe in the empty state.
        path = self.make_log("empty.log", "")
        with patch("logreader.qt_app.QFileDialog.getOpenFileNames", return_value=([str(path)], "")):
            self.window._open_button.click()
        page = self.window._document
        wait_for_load(page)
        self.assertEqual(self.window._tabs.count(), 1)
        self.assertFalse(self.window._empty_page.isVisible())
        self.assertFalse(self.window._empty_tab_label.isVisible())
        self.assertFalse(self.window._empty_version_label.isVisible())
        self.assertTrue(self.window._action_margin.isVisible())
        self.assertTrue(self.window._tabs.isVisible())
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertEqual(page.session.path, path)
        self.assertEqual(page.session.lines, ())
        self.assertEqual(page.results_view.editor.toPlainText(), "")
        self.assertEqual(page.results_view.editor.placeholderText(), "")
        self.assertIsNone(page.session.analysis)
        self.assertEqual(page.session.phase, AnalysisPhase.IDLE)
        self.assertEqual(page.results_view.editor.toPlainText(), "")

    def test_performance_option_applies_to_each_document(self):
        self.window.close()
        self.window = LogreaderWindow(show_performance=True)
        self.window.show()
        for name in ("first.log", "second.log"):
            page = self.open_log(name)
            done = QSignalSpy(page.analysis_finished)
            page.analyze()
            self.wait_for_completion(done)
            output = page.results_view.editor.toPlainText()
            self.assertTrue(output.startswith("Performance timing\nAnalysis time:"))
            self.assertIn("Result rendering time:", output)
            self.assertIn("ERROR: example", output)

    def test_performance_cli_flag_preserves_qt_options(self):
        from logreader.qt_app import main

        for flags, enabled in (([], False), (["-p"], True), (["--performance"], True)):
            with (
                self.subTest(flags=flags),
                patch("logreader.qt_app.QApplication") as app,
                patch("logreader.qt_app.LogreaderWindow") as window,
                patch("logreader.qt_app.QThreadPool"),
            ):
                app.return_value.exec.return_value = 0
                self.assertEqual(main(["logreader", *flags, "-platform", "offscreen"]), 0)
                window.assert_called_once_with(show_performance=enabled)
                app.assert_called_once_with(["logreader", "-platform", "offscreen"])

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
        with patch("logreader.load_worker.load_log", side_effect=AssertionError("Duplicate reread")):
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

    def test_long_selected_tab_keeps_close_control_visible_with_overflow(self):
        self.window.resize(820, 560)
        self.window.show()
        self.open_log("ordinary.log")
        page = self.open_log("long_" + "a" * 180 + ".log")
        path = page.session.path
        self.app.processEvents()
        self.assertLessEqual(self.window._tabs.tabRect(1).width(), 280)
        self.assertGreater(self.window._tabs.tabRect(0).width(),
                           self.window._tabs.fontMetrics().horizontalAdvance("ordinary.log") + 20)
        for index in range(11):
            self.open_log(f"document-{index}.log")
        index = self.window._pages.indexOf(page)
        for selected in (0, index, 5, index):
            self.window._tabs.setCurrentIndex(selected)
            self.app.processEvents()
            button = self.window._tabs.tabButton(selected, QTabBar.ButtonPosition.RightSide)
            self.assertTrue(self.window._tabs.rect().contains(button.geometry()))
            self.assertIs(self.window._tabs.childAt(button.geometry().center()), button)
        self.assertEqual(self.window._tabs.tabToolTip(index), str(path))
        button.click()
        self.assertEqual(self.window._tabs.count(), 12)
        self.assertNotIn(str(path), [self.window._tabs.tabToolTip(i) for i in range(12)])

    def test_ampersands_in_filenames_and_duplicate_parent_labels_are_literal(self):
        pages = [self.open_log(f"{parent}/error&warning.log") for parent in ("one&two", "three&four")]
        for index, page in enumerate(pages):
            label = self.window._tabs.tabText(index)
            self.assertTrue(QKeySequence.mnemonic(label).isEmpty())
            self.assertIn(page.session.path.name, label.replace("&&", "&"))
            self.assertIn(page.session.path.parent.name, label.replace("&&", "&"))
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
        wait_for_search(self.window)
        view.find_next()
        wait_for_search(self.window)
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

    def test_failed_open_keeps_error_in_its_tab_and_preserves_other_documents(self):
        first = self.open_log("first.log")
        with patch("logreader.qt_app.QMessageBox.critical") as error:
            self.assertTrue(self.window.load_file(self.root / "missing.log"))
            failed = self.window._document
            wait_for_load(failed)
            error.assert_not_called()
        self.assertEqual(self.window._tabs.count(), 2)
        self.assertIs(self.window._document, failed)
        self.assertFalse(failed.session.has_document)
        self.assertIn("Unable to load missing.log", failed.status_message)
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.window._select_document(first)
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.statusBar().currentMessage(), first.status_message)

    def test_background_completion_and_switching_keep_correct_owner_and_status(self):
        first = self.open_log("first.log", "ERROR: first\n")
        workers = []
        with capture_analysis(workers):
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
        self.assertIsNone(first.results_view._renderer)
        self.assertEqual(first_done.count(), 0)
        self.assertIs(self.window._document, second)
        self.assertEqual(self.window.statusBar().currentMessage(), status)
        self.assertIn("ERROR: second", second.results_view.editor.toPlainText())
        self.window._select_document(first)
        self.wait_for_completion(first_done)
        self.assertIn("ERROR: first", first.results_view.editor.toPlainText())
        self.assertEqual(self.window.statusBar().currentMessage(), first.status_message)
        self.assertEqual(self.window.windowTitle(), f"{APP_VERSION} - first.log")
        self.assertEqual(self.app.applicationDisplayName(), self.window.windowTitle())
        first.results_view.set_maximized(True)
        self.window._select_document(second)
        self.assertFalse(second.results_view.is_maximized)
        self.assertFalse(self.window._action_margin.isHidden())
        self.window._select_document(first)
        self.assertTrue(first.results_view.is_maximized)
        self.assertTrue(self.window._action_margin.isHidden())
        self.assertFalse(self.window._tabs.isHidden())

    def test_keyboard_navigation_wraps_from_controls_and_maximized_results(self):
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        QTest.keyClick(self.window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNone(self.window._document)
        first = self.open_log("first.log")
        QTest.keyClick(self.window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.assertIs(self.window._document, first)
        second = self.open_log("second.log")
        third = self.open_log("third.log")
        for target in (
            third.findChild(QLineEdit, "customPattern"),
            third.findChild(QLineEdit, "resultsSearch"),
            third.findChild(QSpinBox, "contextSpin"),
            third.results_view.editor,
            self.window._open_button,
            self.window._tabs,
        ):
            with self.subTest(target=target.objectName()):
                self.window._select_document(third)
                target.setFocus()
                self.app.processEvents()
                QTest.keyClick(target, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
                self.assertIs(self.window._document, first)
                QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_Tab,
                               Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                self.assertIs(self.window._document, third)
        third.results_view.set_maximized(True)
        third.results_view.editor.setFocus()
        QTest.keyClick(third.results_view.editor, Qt.Key.Key_Backtab,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertIs(self.window._document, second)
        self.window._select_document(third)
        self.assertTrue(third.results_view.is_maximized)
        self.assertTrue(self.window._tabs.isVisible())
        self.assertTrue(self.window._open_button.isVisible())

    def test_completion_preserves_focus_after_user_moves_to_filter_input(self):
        page = self.open_log("first.log")
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        workers = []
        with capture_analysis(workers):
            self.window.analyze_current()
        draft = page.findChild(QLineEdit, "customPattern")
        draft.setText("continue editing")
        draft.selectAll()
        draft.setFocus()
        done = QSignalSpy(page.analysis_finished)
        workers[0].run()
        self.wait_for_completion(done)
        self.assertIs(self.app.focusWidget(), draft)
        self.assertEqual(draft.selectedText(), "continue editing")

    def test_switching_during_analysis_and_rendering_restores_busy_state(self):
        first = self.open_log("first.log", "ERROR: first\n" * 100)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        workers = []
        with capture_analysis(workers):
            self.window.analyze_current()
            first._show_analysis_busy()
            second = self.open_log("second.log")
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertNotEqual(self.window.cursor().shape(), Qt.CursorShape.WaitCursor)
        self.window._select_document(first)
        self.assertFalse(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window.cursor().shape(), Qt.CursorShape.WaitCursor)
        self.assertIn("Analyzing first.log", self.window.statusBar().currentMessage())
        self.window._select_document(second)
        draft = second.findChild(QLineEdit, "customPattern")
        draft.setText("second draft")
        draft.selectAll()
        draft.setFocus()
        status = self.window.statusBar().currentMessage()
        done = QSignalSpy(first.analysis_finished)
        with patch.object(first.results_view, "focus_editor", wraps=first.results_view.focus_editor) as focus:
            workers[0].run()
            self.assertEqual(first.session.phase, AnalysisPhase.RENDERING)
            self.assertIsNone(first.results_view._renderer)
            self.assertIs(self.app.focusWidget(), draft)
            self.assertEqual(draft.selectedText(), "second draft")
            self.assertEqual(self.window.statusBar().currentMessage(), status)
            self.window._select_document(first)
            renderer = first.results_view._renderer
            renderer._timer.stop()
            with patch("logreader.results_view.INCREMENTAL_RENDER_BATCH_MS", 0):
                renderer._render_next_batch()
            first._show_analysis_busy()
            self.assertIn("Rendering results for first.log", self.window.statusBar().currentMessage())
            self.assertFalse(self.window._analyze_button.isEnabled())
            self.assertEqual(self.window.cursor().shape(), Qt.CursorShape.WaitCursor)
            self.window._select_document(second)
            draft.setFocus()
            partial = first.results_view.editor.toPlainText()
            QTest.qWait(20)
            self.assertFalse(renderer._timer.isActive())
            self.assertEqual(first.results_view.editor.toPlainText(), partial)
            self.assertEqual(done.count(), 0)
            self.assertIs(self.app.focusWidget(), draft)
            self.assertEqual(self.window.statusBar().currentMessage(), status)
            self.assertTrue(self.window._analyze_button.isEnabled())
            self.assertNotEqual(self.window.cursor().shape(), Qt.CursorShape.WaitCursor)
            self.window._select_document(first)
            self.wait_for_completion(done)
            focus.assert_not_called()
        self.assertTrue(self.window._analyze_button.isEnabled())
        self.assertEqual(self.window._analyze_button.text(), "&Analyze")
        self.assertFalse(first.busy_visible)

    def test_background_worker_and_renderer_failures_retain_details_in_owner(self):
        for phase in ("analysis", "rendering"):
            with self.subTest(phase=phase):
                first = self.open_log(f"{phase}-first.log")
                workers = []
                with capture_analysis(workers):
                    self.window.analyze_current()
                    second = self.open_log(f"{phase}-second.log")
                    self.window.analyze_current()
                self.assertEqual(workers[0].request_id, workers[1].request_id)
                status = self.window.statusBar().currentMessage()
                message = f"{phase} failed for first"
                with patch("logreader.qt_app.QMessageBox.warning") as warning:
                    if phase == "analysis":
                        with patch("logreader.analysis_worker.analyze_lines", side_effect=RuntimeError(message)):
                            workers[0].run()
                    else:
                        workers[0].run()
                        self.window._select_document(first)
                        renderer = first.results_view._renderer
                        self.window._select_document(second)
                        # A failure already dispatched before a switch still
                        # belongs to this renderer, even after it is paused.
                        renderer.failed.emit(workers[0].request_id, message)
                    warning.assert_not_called()
                    self.assertEqual(self.window.statusBar().currentMessage(), status)
                    self.assertEqual(second.session.phase, AnalysisPhase.ANALYZING)
                    self.assertFalse(self.window._analyze_button.isEnabled())
                    self.window._select_document(first)
                    self.assertIn(message, self.window.statusBar().currentMessage())
                    self.assertEqual(first.session.phase, AnalysisPhase.IDLE)
                    self.assertTrue(self.window._analyze_button.isEnabled())
                    warning.assert_not_called()
                    # An active-tab failure still displays its own dialog.
                    self.window._select_document(second)
                    workers[1].signals.failed.emit(workers[1].request_id, "second failure")
                    warning.assert_called_once_with(self.window, "Invalid filters", "second failure")
                    self.assertIn("second failure", second.status_message)

    def test_open_dialog_uses_active_directory_even_with_maximized_results(self):
        first = self.open_log("first/server.log")
        self.open_log("second/server.log")
        self.window._select_document(first)
        first.results_view.set_maximized(True)
        with patch("logreader.qt_app.QFileDialog.getOpenFileNames", return_value=([], "")) as dialog:
            self.window._open_button.click()
        self.assertEqual(dialog.call_args.args[2], str(first.session.path.parent))
        self.assertIs(self.window._document, first)
        self.assertTrue(first.results_view.is_maximized)
