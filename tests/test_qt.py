import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qt_helpers import wait_for_search, wait_for_load
    from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import (
        QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent,
        QTextCursor, QWheelEvent,
    )
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFrame,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QStyle,
        QStyleOptionButton,
        QStyleOptionSlider,
        QStyleOptionSpinBox,
        QToolButton,
        QWidget,
    )

    from logreader.config import (
        APP_VERSION,
    )
    from logreader.core import analyze_lines
    from logreader.file_loader import load_log
    from logreader.document_session import AnalysisPhase
    from logreader.ui.filter_panel import (
        FilterPanel,
        VisibleSpinBox,
    )
    from logreader.ui.qt_app import (
        COLORS,
        LogreaderWindow,
    )
    from logreader.ui.results.results_view import (
        ResultsView,
        SearchMarkerScrollBar,
    )
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False
else:
    PYSIDE_AVAILABLE = True


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class LogreaderQtTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = LogreaderWindow()
        # These tests exercise one document's controls and rendering. Tab/opening
        # behavior is covered separately in test_tabs.py.
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        initial_path = Path(self.directory.name) / "initial.log"
        initial_path.write_text("", encoding="utf-8")
        self.window.load_file(initial_path)
        wait_for_load(self.window._document)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def _stage_file(self, path):
        self.window._document.stage_loaded_log(Path(path), load_log(path))
        self.window._current_document_changed(self.window._tabs.currentIndex())
        return True

    def _click_analyze_and_wait(self, timeout: int = 5_000) -> None:
        completed = QSignalSpy(self.window.analysis_finished)
        self.window.findChild(QPushButton, "analyzeButton").click()
        self._wait_for_signal(completed, timeout)

    def _wait_for_signal(
        self,
        signal_spy: QSignalSpy,
        timeout: int = 5_000,
    ) -> None:
        for _ in range(max(1, timeout // 10)):
            self.app.processEvents()
            if signal_spy.count():
                return
            QTest.qWait(10)
        self.fail("Analysis did not finish")

    def _drop_urls(self, target, urls):
        mime = QMimeData()
        mime.setUrls(urls)
        events = [
            event_type(
                position, Qt.DropAction.CopyAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
            for event_type, position in (
                (QDragEnterEvent, QPoint(5, 5)),
                (QDragMoveEvent, QPoint(5, 5)),
                (QDropEvent, QPointF(5, 5)),
            )
        ]
        for event in events:
            self.app.sendEvent(target, event)
        return events

    def test_file_drop_anywhere_opens_tab_and_waits_for_analyze(self):
        self.window.show()
        self.app.processEvents()
        page = self.window._document
        custom = page.findChild(QLineEdit, "customPattern")
        custom.setText("keep this draft")
        targets = (
            self.window, self.window.centralWidget(), self.window._open_button,
            page.filter_panel, custom,
            page.findChild(QLineEdit, "resultsSearch"),
            page.results_view.editor.viewport(), self.window.statusBar(),
        )
        for index, target in enumerate(targets):
            with self.subTest(target=target.objectName()):
                self.window._select_document(page)
                path = Path(self.directory.name) / f"drop-{index}.log"
                path.write_text("ERROR: new\n", encoding="utf-8")
                events = self._drop_urls(target, [QUrl.fromLocalFile(str(path))])
                self.assertTrue(all(event.isAccepted() for event in events))
                current = self.window._document
                wait_for_load(current)
                self.assertIsNot(current, page)
                self.assertEqual(current.session.path, path)
                self.assertIsNone(current.session.analysis)
                self.assertEqual(current.results_view.editor.toPlainText(), "")
                self.assertEqual(current.findChild(QLineEdit, "customPattern").text(), "")
                self.assertEqual(custom.text(), "keep this draft")
                self.assertTrue(self.window._analyze_button.isEnabled())

    def test_invalid_drops_preserve_loaded_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.log"
            path.write_text("ERROR: original\n", encoding="utf-8")
            self._stage_file(path)
            self._click_analyze_and_wait()
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            original = results.toPlainText()
            local_url = QUrl.fromLocalFile(str(path))
            for urls in (
                [], [QUrl("https://example.com/server.log")],
                [QUrl.fromLocalFile(directory)],
                [QUrl.fromLocalFile(str(path.with_name("missing.log")))],
            ):
                with self.subTest(urls=urls):
                    events = self._drop_urls(self.window, urls)
                    self.assertFalse(any(event.isAccepted() for event in events))
                    self.assertEqual(self.window._document.session.path, path)
                    self.assertEqual(results.toPlainText(), original)

    def test_drop_overlay_tracks_hover_leave_resize_and_drop(self):
        self.window.show()
        self.app.processEvents()
        overlay = self.window.findChild(QLabel, "dropOverlay")
        self.assertFalse(overlay.isVisible())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hover.log"
            path.write_text("ERROR: hover\n", encoding="utf-8")
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])

            def enter(target):
                event = QDragEnterEvent(
                    QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                )
                self.app.sendEvent(target, event)
                self.assertTrue(event.isAccepted())

            enter(self.window)
            self.assertTrue(overlay.isVisible())
            self.assertEqual(overlay.text(), "Drop file")
            self.assertEqual(self.window._tabs.count(), 1)
            self.assertTrue(overlay.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            ))
            self.window.resize(1200, 850)
            self.app.processEvents()
            self.assertEqual(overlay.geometry(), self.window.rect())

            self.app.sendEvent(self.window, QDragLeaveEvent())
            search = self.window.findChild(QLineEdit, "resultsSearch")
            enter(search)
            self.app.processEvents()
            self.assertTrue(overlay.isVisible())
            self.app.sendEvent(search, QDragLeaveEvent())
            self.app.processEvents()
            self.assertFalse(overlay.isVisible())

            self.window._document.results_view.set_maximized(True)
            enter(self.window)
            self.assertEqual(overlay.geometry(), self.window.rect())
            self._drop_urls(self.window, [QUrl.fromLocalFile(str(path))])
            self.assertFalse(overlay.isVisible())
            self.assertEqual(self.window._document.session.path, path)

            enter(self.window)
            self._drop_urls(self.window, [QUrl("https://example.com/file.log")])
            self.assertFalse(overlay.isVisible())

    def test_default_controls_build_the_shared_configuration(self):
        filter_panel = self.window.findChild(FilterPanel, "filterGroup")
        config = filter_panel.build_config()

        self.assertEqual(self.window.build_config(), config)
        self.assertEqual(config.context, 5)
        self.assertEqual(config.max_lines_scanned, 2_000_000)
        self.assertEqual(
            config.enabled_patterns,
            (
                "error_colon",
                "error",
                "exception",
                "exception_generic",
                "failed",
                "failure",
                "fatal",
                "critical",
                "refused",
            ),
        )
        self.assertEqual(config.custom_patterns, ())
        self.assertEqual(config.regex_patterns, ())
        self.assertTrue(config.separate_entries)
        self.assertTrue(config.combined_view)
        self.assertEqual(
            self.window.findChild(QLabel, "limitLabel").text(),
            "Max lines scanned",
        )
        self.assertEqual(
            self.window.findChild(QLabel, "contextLabel").text(),
            "Context around matches",
        )
        self.assertEqual(
            self.window.findChild(QCheckBox, "separateEntriesCheck").text(),
            "Line-spacing",
        )
        self.assertEqual(
            self.window.findChild(QCheckBox, "combinedViewCheck").text(),
            "Combined view",
        )
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Loaded as UTF-8: initial.log",
        )

    def test_results_scrollbars_use_visible_theme_colors(self):
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        style_sheet = results.styleSheet()

        self.assertIn("QScrollBar::handle:vertical", style_sheet)
        self.assertIn("QScrollBar::handle:horizontal", style_sheet)
        self.assertIn("QScrollBar:horizontal", style_sheet)
        self.assertIn(COLORS["scrollbar_track"].name(), style_sheet)
        self.assertIn(COLORS["scrollbar_handle"].name(), style_sheet)
        self.assertIn(COLORS["scrollbar_handle_hover"].name(), style_sheet)

    def test_checkbox_marks_and_spin_arrows_are_painted_visibly(self):
        checkbox = self.window.findChild(QCheckBox, "separateEntriesCheck")
        checkbox.setChecked(True)
        self.window.show()
        self.app.processEvents()

        checkbox_option = QStyleOptionButton()
        checkbox.initStyleOption(checkbox_option)
        indicator = checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            checkbox_option,
            checkbox,
        )
        checkbox_image = checkbox.grab().toImage()
        self.assertGreater(
            self._light_pixel_count(checkbox_image, indicator, threshold=220),
            2,
        )

        for object_name in ("contextSpin", "limitSpin"):
            spin_box = self.window.findChild(QSpinBox, object_name)
            spin_option = QStyleOptionSpinBox()
            spin_box.initStyleOption(spin_option)
            spin_image = spin_box.grab().toImage()
            edit_field = spin_box.lineEdit().geometry()
            up_button = spin_box.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                spin_option,
                QStyle.SubControl.SC_SpinBoxUp,
                spin_box,
            )
            self.assertEqual(edit_field.right(), up_button.left() - 1)
            for subcontrol in (
                QStyle.SubControl.SC_SpinBoxUp,
                QStyle.SubControl.SC_SpinBoxDown,
            ):
                button = spin_box.style().subControlRect(
                    QStyle.ComplexControl.CC_SpinBox,
                    spin_option,
                    subcontrol,
                    spin_box,
                )
                self.assertGreater(
                    self._light_pixel_count(spin_image, button, threshold=205),
                    2,
                )
                left, center, right = spin_box._chevron_points(
                    button,
                    subcontrol == QStyle.SubControl.SC_SpinBoxDown,
                )
                self.assertEqual(center.x(), button.center().x() + 1)
                if subcontrol == QStyle.SubControl.SC_SpinBoxDown:
                    self.assertGreater(center.y(), left.y())
                    self.assertGreater(center.y(), right.y())
                    self.assertEqual(center.y(), button.center().y() + 1.5)
                else:
                    self.assertLess(center.y(), left.y())
                    self.assertLess(center.y(), right.y())
                    self.assertEqual(center.y(), button.center().y() - 0.5)

    def test_spin_arrow_hover_outlines_each_button_on_all_sides(self):
        # Give the platform font enough room before inspecting hover painting.
        self.window.resize(self.window.size().expandedTo(self.window.minimumSizeHint()))
        self.window.show()
        self.window.activateWindow()
        self.assertTrue(QTest.qWaitForWindowExposed(self.window))

        for object_name in (
            "contextSpin",
            "limitSpin",
            "resultsSearchNavigation",
        ):
            spin_box = self.window.findChild(QSpinBox, object_name)
            for subcontrol in (
                QStyle.SubControl.SC_SpinBoxUp,
                QStyle.SubControl.SC_SpinBoxDown,
            ):
                with self.subTest(
                    object_name=object_name,
                    subcontrol=subcontrol,
                ):
                    option = QStyleOptionSpinBox()
                    spin_box.initStyleOption(option)
                    button = spin_box.style().subControlRect(
                        QStyle.ComplexControl.CC_SpinBox,
                        option,
                        subcontrol,
                        spin_box,
                    )
                    QTest.mouseMove(spin_box, button.center())
                    # Native Windows mouse moves arrive through the window
                    # system, rather than synchronously as with offscreen Qt.
                    QTest.qWait(30)
                    image = spin_box.grab().toImage()

                    edge_points = {
                        "top": (button.center().x(), button.top()),
                        "bottom": (button.center().x(), button.bottom()),
                        "left": (button.left(), button.center().y()),
                        "right": (button.right(), button.center().y()),
                    }
                    for edge, (x, y) in edge_points.items():
                        self.assertEqual(
                            image.pixelColor(x, y),
                            COLORS["ui_accent"],
                            f"{object_name} {subcontrol} {edge}",
                        )

    @staticmethod
    def _light_pixel_count(image, area, *, threshold: int) -> int:
        count = 0
        for y in range(max(0, area.top()), min(image.height(), area.bottom() + 1)):
            for x in range(
                max(0, area.left()),
                min(image.width(), area.right() + 1),
            ):
                color = image.pixelColor(x, y)
                if (
                    color.red() >= threshold
                    and color.green() >= threshold
                    and color.blue() >= threshold
                ):
                    count += 1
        return count

    def test_window_icon_loads_packaged_artwork_at_small_and_large_sizes(self):
        icon = self.window.windowIcon()
        self.assertFalse(icon.isNull())
        sizes = {size.width() for size in icon.availableSizes()}
        self.assertTrue({16, 24, 32, 48, 256}.issubset(sizes))
        for size in (16, 24, 32, 48, 256):
            with self.subTest(size=size):
                image = icon.pixmap(size, size).toImage()
                self.assertEqual(image.width(), size)
                self.assertEqual(image.height(), size)
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertGreater(image.pixelColor(size // 2, size // 2).alpha(), 0)
                visible = [
                    (x, y)
                    for y in range(size)
                    for x in range(size)
                    if image.pixelColor(x, y).alpha() > 8
                ]
                self.assertGreaterEqual(
                    max(x for x, y in visible) - min(x for x, y in visible) + 1,
                    round(size * 0.88),
                )
                self.assertGreaterEqual(
                    max(y for x, y in visible) - min(y for x, y in visible) + 1,
                    round(size * 0.78),
                )
                border_alpha = [
                    image.pixelColor(x, y).alpha()
                    for x in range(size)
                    for y in (0, size - 1)
                ] + [
                    image.pixelColor(x, y).alpha()
                    for y in range(size)
                    for x in (0, size - 1)
                ]
                self.assertLess(max(border_alpha), 128)

    def test_filter_tabs_and_list_drag_resize_only_the_upper_controls(self):
        self.window.resize(self.window.size().expandedTo(self.window.minimumSizeHint()))
        self.window.show()
        self.app.processEvents()
        page = self.window._document
        filters = page.filter_panel
        header = page.results_view.findChild(QWidget, "resultsHeader")
        widgets = [header] + header.findChildren(QWidget)
        before = [widget.geometry() for widget in widgets]
        initial_height = page.controls_container.height()
        config = page.build_config()
        output = page.results_view.editor.toPlainText()
        grip = filters._resize_handle
        self.assertFalse(grip.isVisible())

        filters._tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertLess(page.controls_container.height(), initial_height)
        self.assertTrue(filters._pattern_checkboxes["http_4xx"].isVisible())
        self.assertFalse(filters._pattern_checkboxes["unavailable"].isVisible())
        self.assertFalse(grip.isVisible())
        for widget, geometry in zip(widgets, before):
            self.assertEqual(widget.geometry(), geometry, widget.objectName())

        filters._tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.assertGreater(page.controls_container.height(), initial_height)
        for pattern_list in (filters._custom_pattern_list, filters._regex_pattern_list):
            self.assertTrue(pattern_list.isVisible())
            self.assertEqual(pattern_list.height(), 160)
            self.assertGreater(pattern_list.width(), filters.width() * 0.4)
        self.assertTrue(grip.isVisible())
        self.assertLess(grip.mapTo(page, grip.rect().bottomLeft()).y(),
                        header.mapTo(page, header.rect().topLeft()).y())
        for button, distance, expected_height in (
            (Qt.MouseButton.RightButton, 60, 160),
            (Qt.MouseButton.LeftButton, 60, 220),
            (Qt.MouseButton.LeftButton, -200, 124),
            (Qt.MouseButton.LeftButton, 500, 310),
            (Qt.MouseButton.LeftButton, -90, 220),
        ):
            with self.subTest(button=button, distance=distance):
                previous_list_height = filters._custom_pattern_list.height()
                previous_controls_height = page.controls_container.height()
                start = grip.rect().center()
                destination = grip.mapToGlobal(start) + QPoint(0, distance)
                QTest.mousePress(grip, button, pos=start)
                QTest.mouseMove(grip, grip.mapFromGlobal(destination))
                QTest.qWait(20)
                # A second move at the same screen position must not compound the delta.
                QTest.mouseMove(grip, grip.mapFromGlobal(destination))
                QTest.mouseRelease(grip, button, pos=grip.mapFromGlobal(destination))
                QTest.qWait(20)
                self.assertEqual(filters._custom_pattern_list.height(), expected_height)
                self.assertEqual(filters._regex_pattern_list.height(), expected_height)
                self.assertEqual(page.controls_container.height() - previous_controls_height,
                                 expected_height - previous_list_height)
        self.assertEqual(page.build_config(), config)
        self.assertEqual(page.results_view.editor.toPlainText(), output)
        for widget, geometry in zip(widgets, before):
            self.assertEqual(widget.geometry(), geometry, widget.objectName())

        page.results_view.set_maximized(True)
        page.results_view.set_maximized(False)
        self.app.processEvents()
        self.assertEqual(filters._tabs.currentIndex(), 2)
        self.assertEqual(filters._custom_pattern_list.height(), 220)
        filters._tabs.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(page.controls_container.height(), initial_height)
        self.assertFalse(grip.isVisible())
        filters._tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.assertEqual(filters._custom_pattern_list.height(), 220)
        self.assertEqual(filters._regex_pattern_list.height(), 220)

    def test_shrinking_search_lists_keeps_upper_controls_stationary(self):
        self.window.resize(self.window.size().expandedTo(self.window.minimumSizeHint()))
        filters = self.window._document.filter_panel
        filters._tabs.setCurrentIndex(2)
        self.window.show()
        QTest.qWait(20)
        grip = filters._resize_handle
        start = grip.rect().center()
        destination = grip.mapToGlobal(start) + QPoint(0, 100)
        QTest.mousePress(grip, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(grip, grip.mapFromGlobal(destination))
        QTest.qWait(20)
        QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=grip.mapFromGlobal(destination))
        self.assertEqual(filters._custom_pattern_list.height(), 260)

        anchored = [self.window._analyze_button, filters._context_spin, filters._tabs,
                    filters._custom_heading, filters._regex_heading,
                    filters._custom_pattern, filters._regex_pattern,
                    filters._custom_pattern_list, filters._regex_pattern_list]
        expected = [widget.mapTo(self.window, QPoint()) for widget in anchored]
        frames = []
        window = self.window

        class PaintPositions(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Paint:
                    frames.append([widget.mapTo(window, QPoint()) for widget in anchored])
                return False

        observer = PaintPositions()
        for widget in anchored:
            widget.installEventFilter(observer)
        try:
            start = grip.rect().center()
            origin = grip.mapToGlobal(start)
            QTest.mousePress(grip, Qt.MouseButton.LeftButton, pos=start)
            for distance in range(5, 101, 5):
                destination = origin - QPoint(0, distance)
                QTest.mouseMove(grip, grip.mapFromGlobal(destination))
                QTest.qWait(10)
            QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=grip.mapFromGlobal(destination))
            QTest.qWait(20)
        finally:
            for widget in anchored:
                widget.removeEventFilter(observer)

        self.assertEqual(filters._custom_pattern_list.height(), 160)
        self.assertEqual(filters._regex_pattern_list.height(), 160)
        self.assertTrue(frames)
        for frame in frames:
            self.assertEqual(frame, expected)

    def test_results_view_can_be_maximized_and_restored(self):
        file_controls = self.window.findChild(QWidget, "fileControlsRow")
        filter_group = self.window.findChild(QGroupBox, "filterGroup")
        results_header = self.window.findChild(QWidget, "resultsHeader")
        results_panel = self.window.findChild(QWidget, "resultsPanel")
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        controls_container = self.window.findChild(QWidget, "controlsContainer")
        button = self.window.findChild(QPushButton, "maximizeResultsButton")

        self.assertIsInstance(results_panel, ResultsView)
        self.assertFalse(file_controls.isHidden())
        self.assertFalse(filter_group.isHidden())
        self.assertFalse(results_header.isHidden())
        self.assertFalse(results.isHidden())
        self.assertIs(results_header.parentWidget(), results_panel)
        self.assertIs(results.parentWidget(), results_panel)
        self.assertEqual(results_panel.layout().spacing(), 0)
        panel_margins = results_panel.layout().contentsMargins()
        self.assertEqual(
            (
                panel_margins.left(),
                panel_margins.top(),
                panel_margins.right(),
                panel_margins.bottom(),
            ),
            (0, 0, 0, 0),
        )
        self.window.show()
        self.app.processEvents()
        self.assertEqual(results.geometry().top(), results_header.geometry().bottom() + 1)
        self.assertIn("border: none", results.styleSheet())
        self.assertEqual(results_panel.geometry().left(), 0)
        self.assertEqual(results_panel.geometry().right(), self.window._document.width() - 1)
        self.assertEqual(results_panel.geometry().bottom(), self.window._document.height() - 1)
        self.assertFalse(controls_container.isHidden())
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        expand_icon_key = button.icon().cacheKey()
        self.assertEqual(button.accessibleName(), "Maximize results")
        self.assertEqual(button.toolTip(), "Expand results window")
        self.assertIn("QToolTip { font-weight: 400; }", button.styleSheet())
        self.assertEqual(button.width(), 38)
        self.assertEqual(button.height(), 28)
        header_layout = results_header.layout()
        self.assertIs(header_layout.itemAt(0).widget(), button)
        self.assertEqual(header_layout.itemAt(1).widget().text(), "Go to source")
        self.assertIsNone(header_layout.itemAt(2).widget())
        self.assertEqual(header_layout.stretch(2), 1)
        self.assertEqual(
            header_layout.itemAt(3).widget().objectName(),
            "searchCountStack",
        )
        self.assertEqual(
            header_layout.itemAt(4).widget().objectName(),
            "resultsSearchControls",
        )
        self.assertEqual(
            header_layout.itemAt(5).widget().objectName(),
            "resultsSearchSeparator",
        )
        self.assertEqual(
            header_layout.itemAt(6).widget().objectName(),
            "lineWrapLabel",
        )
        self.assertEqual(
            header_layout.itemAt(7).widget().objectName(),
            "lineWrapCheck",
        )

        button.click()

        self.app.processEvents()
        self.assertFalse(file_controls.isVisible())
        self.assertTrue(self.window._tabs.isVisible())
        self.assertEqual(
            results_panel.mapTo(self.window.centralWidget(), results_panel.rect().topLeft()).y(),
            self.window._tab_controls.geometry().bottom() + 1,
        )
        self.assertTrue(filter_group.isHidden())
        self.assertTrue(controls_container.isHidden())
        self.assertFalse(results_header.isHidden())
        self.assertFalse(results.isHidden())
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        self.assertNotEqual(button.icon().cacheKey(), expand_icon_key)
        self.assertEqual(button.accessibleName(), "Restore layout")
        self.assertEqual(button.toolTip(), "Show menu and filters")

        button.click()

        self.assertFalse(file_controls.isHidden())
        self.assertFalse(filter_group.isHidden())
        self.assertFalse(controls_container.isHidden())
        self.assertEqual(button.text(), "")
        self.assertEqual(button.icon().cacheKey(), expand_icon_key)
        self.assertEqual(button.accessibleName(), "Maximize results")
        self.assertEqual(button.toolTip(), "Expand results window")

    def test_line_wrapping_can_be_toggled_from_results_header(self):
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        label = self.window.findChild(QLabel, "lineWrapLabel")
        checkbox = self.window.findChild(QCheckBox, "lineWrapCheck")

        self.assertEqual(label.text(), "Line wrapping")
        self.assertFalse(checkbox.isChecked())
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.NoWrap,
        )

        checkbox.click()
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.WidgetWidth,
        )

        checkbox.click()
        self.assertEqual(
            results.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.NoWrap,
        )

    def test_results_search_highlights_without_jumping_and_navigates(self):
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        search = self.window.findChild(QLineEdit, "resultsSearch")
        count = self.window.findChild(QLabel, "resultsSearchCount")
        navigation = self.window.findChild(QSpinBox, "resultsSearchNavigation")
        button_separator = self.window.findChild(
            QFrame,
            "resultsSearchButtonSeparator",
        )
        separator = self.window.findChild(QFrame, "resultsSearchSeparator")
        search_controls = self.window.findChild(QWidget, "resultsSearchControls")

        self.assertEqual(search.placeholderText(), "Press enter to search...")
        self.assertTrue(search.isClearButtonEnabled())
        self.assertIsInstance(navigation, VisibleSpinBox)
        self.assertFalse(navigation.lineEdit().isVisibleTo(navigation))
        self.assertEqual(navigation.width(), 22)
        self.assertEqual(search_controls.layout().spacing(), 0)
        self.assertEqual(
            search_controls.layout().contentsMargins().left(),
            0,
        )
        self.assertIs(search_controls.layout().itemAt(0).widget(), search)
        self.assertIs(
            search_controls.layout().itemAt(1).widget(),
            button_separator,
        )
        self.assertIs(search_controls.layout().itemAt(2).widget(), navigation)
        self.assertIn("border-right: none", search.styleSheet())
        self.assertIn("border-left: none", navigation.styleSheet())
        self.assertEqual(button_separator.width(), 1)
        self.assertEqual(button_separator.height(), 28)
        self.assertIn(
            f"background-color: {COLORS['ui_border_strong'].name()}",
            button_separator.styleSheet(),
        )
        self.assertEqual(separator.width(), 1)
        self.assertTrue(count.isHidden())
        self.assertTrue(count.sizePolicy().retainSizeWhenHidden())

        results.setPlainText(
            "header\nERROR: first\nneutral\nerror: second\nERROR: third\n"
        )
        cursor = results.textCursor()
        cursor.setPosition(0)
        results.setTextCursor(cursor)
        original_position = results.textCursor().position()

        search.setText("error")

        self.assertEqual(results.textCursor().position(), original_position)
        self.assertTrue(count.isHidden())
        self.assertEqual(results.extraSelections(), [])

        search.returnPressed.emit()
        wait_for_search(self.window)

        self.assertEqual(count.text(), "0 / 3")
        self.assertEqual(results.textCursor().position(), original_position)
        self.assertEqual(results.extraSelections(), [])

        navigation.stepDown()
        wait_for_search(self.window)
        self.assertEqual(count.text(), "1 / 3")
        self.assertEqual(results.textCursor().position(), 7)
        self.assertEqual(len(results.extraSelections()), 1)
        self.assertEqual(
            [
                selection.cursor.selectedText()
                for selection in results.extraSelections()
            ],
            ["ERROR"],
        )
        search_highlights = results.extraSelections()
        self.assertEqual(
            search_highlights[0].format.background().color().name(),
            COLORS["search_current"].name(),
        )
        block_highlights = [
            format_range
            for block in (
                results.document().findBlockByNumber(block_number)
                for block_number in range(results.document().blockCount())
            )
            for format_range in block.layout().formats()
            if format_range.format.background().color().name()
            == COLORS["ui_primary"].name()
        ]
        self.assertEqual(len(block_highlights), 3)
        self.assertTrue(
            all(format_range.length == 5 for format_range in block_highlights)
        )

        navigation.stepDown()
        wait_for_search(self.window)
        self.assertEqual(count.text(), "2 / 3")
        search_highlights = results.extraSelections()
        self.assertEqual(
            search_highlights[0].cursor.selectedText(),
            "error",
        )
        self.assertEqual(
            search_highlights[0].format.background().color().name(),
            COLORS["search_current"].name(),
        )

        navigation.stepUp()
        self.assertEqual(count.text(), "1 / 3")

        search.setText("missing")
        self.assertTrue(count.isHidden())
        self.assertEqual(results.extraSelections(), [])

        search.returnPressed.emit()
        wait_for_search(self.window)
        self.assertFalse(count.isHidden())
        self.assertEqual(count.text(), "No matches")
        self.assertEqual(results.extraSelections(), [])

        search.setText("neutral")
        navigation.stepDown()
        wait_for_search(self.window)
        self.assertEqual(count.text(), "1 / 1")
        self.assertEqual(results.textCursor().position(), 20)

    def _prepare_positioned_search(self):
        view = self.window.findChild(ResultsView, "resultsPanel")
        view.editor.setPlainText("\n".join(
            f"line {index} " + "padding " * 30
            + ("error" if index in (100, 110, 500, 510, 900) else "ordinary")
            for index in range(1_000)
        ))
        self.window.show()
        self.app.processEvents()
        view._search_input.setText("error")
        return view

    def test_results_search_in_middle_preserves_view_and_selection(self):
        view = self._prepare_positioned_search()
        editor = view.editor
        for forward, expected_block in ((True, 500), (False, 110)):
            with self.subTest(forward=forward):
                view._search_input.clear()
                view._search_input.setText("error")
                cursor = editor.textCursor()
                cursor.setPosition(0)
                cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
                editor.setTextCursor(cursor)
                editor.verticalScrollBar().setValue(450)
                editor.horizontalScrollBar().setValue(25)
                before = (
                    editor.verticalScrollBar().value(),
                    editor.horizontalScrollBar().value(),
                    editor.textCursor().selectionStart(),
                    editor.textCursor().selectionEnd(),
                )

                view._search_input.returnPressed.emit()
                wait_for_search(self.window)
                self.app.processEvents()

                self.assertEqual(view._search_count_label.text(), "0 / 5")
                self.assertEqual(editor.extraSelections(), [])
                self.assertEqual(before, (
                    editor.verticalScrollBar().value(),
                    editor.horizontalScrollBar().value(),
                    editor.textCursor().selectionStart(),
                    editor.textCursor().selectionEnd(),
                ))
                if forward:
                    view.find_next()
                    wait_for_search(self.window)
                else:
                    view.find_previous()
                    wait_for_search(self.window)
                self.assertEqual(editor.textCursor().blockNumber(), expected_block)

    def test_results_search_repeated_enter_navigates_cached_matches(self):
        view = self._prepare_positioned_search()
        editor = view.editor
        scrollbar = editor.verticalScrollBar()
        scrollbar.setValue(450)
        view._search_input.returnPressed.emit()
        wait_for_search(self.window)
        self.assertEqual(scrollbar.value(), 450)
        self.assertEqual(view._search_count_label.text(), "0 / 5")

        with patch.object(view, "_refresh_search_matches") as refresh:
            for expected_block in (500, 510, 900, 100):
                view._search_input.returnPressed.emit()
                wait_for_search(self.window)
                self.assertEqual(editor.textCursor().blockNumber(), expected_block)
            refresh.assert_not_called()

        scrollbar.setValue(850)
        option = QStyleOptionSlider()
        scrollbar.initStyleOption(option)
        thumb = scrollbar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, option,
            QStyle.SubControl.SC_ScrollBarSlider, scrollbar,
        )
        QTest.mouseClick(scrollbar, Qt.MouseButton.LeftButton, pos=thumb.center())
        view._search_input.returnPressed.emit()
        wait_for_search(self.window)
        self.assertEqual(editor.textCursor().blockNumber(), 900)

        # Changing the query starts a fresh search without navigation.
        before = (scrollbar.value(), editor.textCursor().position())
        view._search_input.setText("ordinary")
        view._search_input.returnPressed.emit()
        wait_for_search(self.window)
        self.assertEqual(before, (scrollbar.value(), editor.textCursor().position()))
        self.assertEqual(editor.extraSelections(), [])
        for query in ("missing", ""):
            view._search_input.setText(query)
            view._search_input.returnPressed.emit()
            wait_for_search(self.window)
            view._search_input.returnPressed.emit()
            wait_for_search(self.window)
            self.assertEqual(before, (scrollbar.value(), editor.textCursor().position()))

    def test_results_search_repeated_arrows_continue_and_wrap(self):
        view = self._prepare_positioned_search()
        view.editor.verticalScrollBar().setValue(450)
        view._search_input.returnPressed.emit()
        wait_for_search(self.window)
        for expected_block in (500, 510, 900, 100):
            view._search_navigation.stepDown()
            self.assertEqual(view.editor.textCursor().blockNumber(), expected_block)
        for expected_block in (900, 510, 500):
            view._search_navigation.stepUp()
            self.assertEqual(view.editor.textCursor().blockNumber(), expected_block)

    def test_results_search_thumb_touch_reanchors_without_moving_thumb(self):
        view = self._prepare_positioned_search()
        scrollbar = view.editor.verticalScrollBar()
        view.find_next()
        wait_for_search(self.window)
        self.assertEqual(view.editor.textCursor().blockNumber(), 100)

        # Layout/programmatic scrolling alone must not reset the match sequence.
        scrollbar.setValue(850)
        view.find_next()
        wait_for_search(self.window)
        self.assertEqual(view.editor.textCursor().blockNumber(), 110)

        for forward, position, expected in ((True, 850, 900), (False, 450, 110)):
            with self.subTest(forward=forward):
                scrollbar.setValue(position)
                option = QStyleOptionSlider()
                scrollbar.initStyleOption(option)
                thumb = scrollbar.style().subControlRect(
                    QStyle.ComplexControl.CC_ScrollBar, option,
                    QStyle.SubControl.SC_ScrollBarSlider, scrollbar,
                )
                QTest.mouseClick(scrollbar, Qt.MouseButton.LeftButton, pos=thumb.center())
                self.assertEqual(scrollbar.value(), position)
                if forward:
                    view.find_next()
                    wait_for_search(self.window)
                else:
                    view.find_previous()
                    wait_for_search(self.window)
                self.assertEqual(view.editor.textCursor().blockNumber(), expected)
        view.find_previous()
        wait_for_search(self.window)
        self.assertEqual(view.editor.textCursor().blockNumber(), 100)

    def test_results_search_track_drag_and_wheel_scroll_reanchor(self):
        view = self._prepare_positioned_search()
        scrollbar = view.editor.verticalScrollBar()
        for interaction in ("track", "drag", "wheel"):
            with self.subTest(interaction=interaction):
                view._search_input.clear()
                view._search_input.setText("error")
                scrollbar.setValue(0)
                view.find_next()
                wait_for_search(self.window)
                self.assertEqual(view.editor.textCursor().blockNumber(), 100)
                if interaction in ("track", "drag"):
                    option = QStyleOptionSlider()
                    scrollbar.initStyleOption(option)
                    groove = scrollbar.style().subControlRect(
                        QStyle.ComplexControl.CC_ScrollBar, option,
                        QStyle.SubControl.SC_ScrollBarGroove, scrollbar,
                    )
                    if interaction == "track":
                        QTest.mouseClick(
                            scrollbar, Qt.MouseButton.LeftButton, pos=groove.center(),
                        )
                    else:
                        thumb = scrollbar.style().subControlRect(
                            QStyle.ComplexControl.CC_ScrollBar, option,
                            QStyle.SubControl.SC_ScrollBarSlider, scrollbar,
                        )
                        QTest.mousePress(
                            scrollbar, Qt.MouseButton.LeftButton, pos=thumb.center(),
                        )
                        QTest.mouseMove(scrollbar, groove.center())
                        QTest.mouseRelease(
                            scrollbar, Qt.MouseButton.LeftButton, pos=groove.center(),
                        )
                else:
                    scrollbar.setValue(450)
                    viewport = view.editor.viewport()
                    position = viewport.rect().center()
                    wheel = QWheelEvent(
                        QPointF(position), QPointF(viewport.mapToGlobal(position)),
                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
                    )
                    self.app.sendEvent(viewport, wheel)
                self.app.processEvents()
                top = view.editor.firstVisibleBlock().blockNumber()
                self.assertGreater(top, 110)
                expected = next(block for block in (500, 510, 900) if block >= top)
                view.find_next()
                wait_for_search(self.window)
                self.assertEqual(view.editor.textCursor().blockNumber(), expected)

    def test_results_search_retains_only_the_current_match_cursor(self):
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = results_view.editor
        search = self.window.findChild(QLineEdit, "resultsSearch")
        match_count = 5_000
        results.setPlainText("error\n" * match_count)

        search.setText("error")
        search.returnPressed.emit()
        wait_for_search(self.window)

        self.assertEqual(len(results_view._search_matches), match_count)
        self.assertEqual(results.extraSelections(), [])
        results_view.find_next()
        wait_for_search(self.window)
        current_highlights = results.extraSelections()
        self.assertEqual(len(current_highlights), 1)
        self.assertEqual(
            current_highlights[0].cursor.selectedText(),
            "error",
        )
        self.assertTrue(
            all(
                isinstance(position, int)
                for match in results_view._search_matches
                for position in match
            )
        )

        search.clear()
        self.assertEqual(results.extraSelections(), [])
        self.assertFalse(results_view._search_highlighter._matches)

    def test_results_search_marks_each_occupied_scrollbar_row_once(self):
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = results_view.editor
        search = self.window.findChild(QLineEdit, "resultsSearch")
        scrollbar = results.verticalScrollBar()

        self.assertIsInstance(scrollbar, SearchMarkerScrollBar)
        match_count = 5_000
        results.setPlainText("error\n" * match_count)
        search.setText("error")
        search.returnPressed.emit()
        wait_for_search(self.window)

        self.window.resize(1_000, 700)
        self.window.show()
        self.app.processEvents()
        option = QStyleOptionSlider()
        scrollbar.initStyleOption(option)
        groove = scrollbar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarGroove,
            scrollbar,
        )
        marker_rows = scrollbar._marker_rows_for_groove(groove)

        self.assertIs(
            scrollbar._match_blocks,
            results_view._search_match_blocks,
        )
        self.assertEqual(marker_rows, tuple(sorted(set(marker_rows))))
        self.assertLessEqual(len(marker_rows), groove.height())
        self.assertTrue(
            all(groove.top() <= row <= groove.bottom() for row in marker_rows)
        )

        slider = scrollbar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarSlider,
            scrollbar,
        )
        scrollbar_image = scrollbar.grab().toImage()
        visible_marker_pixels = [
            (x, y)
            for y in range(scrollbar_image.height())
            for x in range(scrollbar_image.width())
            if scrollbar_image.pixelColor(x, y).name()
            == COLORS["ui_primary"].name()
        ]
        self.assertTrue(visible_marker_pixels)
        self.assertTrue(
            all(not slider.contains(x, y) for x, y in visible_marker_pixels)
        )

        cached_rows = scrollbar._marker_rows
        results_view.find_next()
        wait_for_search(self.window)
        self.assertIs(scrollbar._marker_rows, cached_rows)

        search.clear()
        self.assertEqual(scrollbar._match_blocks.tolist(), [])
        self.assertEqual(scrollbar._marker_rows, ())

    def test_results_search_marker_alignment_uses_blocks_after_resize(self):
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = results_view.editor
        search = self.window.findChild(QLineEdit, "resultsSearch")
        lines = ["ordinary"] * 2_001
        lines[100] = "TARGET short"
        lines[1_000] = f"{'x' * 100_000} TARGET"
        lines[1_900] = "TARGET short"
        results.setPlainText("\n".join(lines))
        search.setText("TARGET")
        search.returnPressed.emit()
        wait_for_search(self.window)

        for height in (700, 350):
            with self.subTest(height=height):
                self.window.resize(1_000, height)
                self.window.show()
                self.app.processEvents()
                scrollbar = results.verticalScrollBar()
                option = QStyleOptionSlider()
                scrollbar.initStyleOption(option)
                groove = scrollbar.style().subControlRect(
                    QStyle.ComplexControl.CC_ScrollBar,
                    option,
                    QStyle.SubControl.SC_ScrollBarGroove,
                    scrollbar,
                )

                marker_rows = scrollbar._marker_rows_for_groove(groove)
                row_span = groove.height() - 1
                block_span = results.blockCount() - 1
                expected_rows = tuple(
                    groove.top() + block * row_span // block_span
                    for block in (100, 1_000, 1_900)
                )
                self.assertEqual(marker_rows, expected_rows)

    def test_wrapped_search_markers_follow_visual_line_layout(self):
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = results_view.editor
        search = self.window.findChild(QLineEdit, "resultsSearch")
        lines = ["ordinary"] * 201
        lines[20] = "TARGET short"
        lines[100] = f"{'x' * 4_000} TARGET"
        lines[180] = "TARGET short"
        results.setPlainText("\n".join(lines))
        results_view.set_line_wrapping(True)
        search.setText("TARGET")
        search.returnPressed.emit()
        wait_for_search(self.window)
        results_view.find_next()
        wait_for_search(self.window)
        results_view.find_next()
        wait_for_search(self.window)
        self.assertEqual(results.textCursor().blockNumber(), 100)

        for width in (1_200, 650):
            with self.subTest(width=width):
                self.window.resize(width, 400)
                self.window.show()
                self.app.processEvents()
                results.ensureCursorVisible()
                self.app.processEvents()
                scrollbar = results.verticalScrollBar()
                option = QStyleOptionSlider()
                scrollbar.initStyleOption(option)
                groove = scrollbar.style().subControlRect(
                    QStyle.ComplexControl.CC_ScrollBar,
                    option,
                    QStyle.SubControl.SC_ScrollBarGroove,
                    scrollbar,
                )

                scroll_extent = scrollbar.maximum() + scrollbar.pageStep()
                self.assertGreater(scroll_extent, results.blockCount())
                visual_lines = tuple(
                    results.document()
                    .findBlockByNumber(block)
                    .firstLineNumber()
                    for block in (20, 100, 180)
                )
                expected_rows = tuple(
                    groove.top()
                    + line * (groove.height() - 1) // (scroll_extent - 1)
                    for line in visual_lines
                )
                self.assertEqual(
                    scrollbar._marker_rows_for_groove(groove),
                    expected_rows,
                )

    def test_search_entry_clear_buttons_use_white_glyphs(self):
        for input_name in ("customPattern", "regexPattern", "resultsSearch"):
            with self.subTest(input_name=input_name):
                input_box = self.window.findChild(QLineEdit, input_name)
                clear_button = input_box.findChild(
                    QToolButton,
                    f"{input_name}ClearButton",
                )
                self.assertIsNotNone(clear_button)

                icon_image = clear_button.icon().pixmap(
                    clear_button.iconSize()
                ).toImage()
                opaque_colors = {
                    icon_image.pixelColor(x, y).getRgb()[:3]
                    for y in range(icon_image.height())
                    for x in range(icon_image.width())
                    if icon_image.pixelColor(x, y).alpha() > 0
                }
                self.assertTrue(opaque_colors)
                self.assertEqual(opaque_colors, {(255, 255, 255)})

    def test_error_patterns_and_plain_variants_are_available_as_toggles(self):
        expected_labels = {
            "pattern_error_colon": "Error:",
            "pattern_error": "Error",
            "pattern_warning": "Warning:",
            "pattern_warning_generic": "Warning",
            "pattern_exception": "Exception:",
            "pattern_exception_generic": "Exception",
            "pattern_failed": "Failed",
            "pattern_fatal": "Fatal",
            "pattern_failure": "Failure",
            "pattern_critical": "Critical",
            "pattern_illegal": "Illegal",
            "pattern_invalid": "Invalid",
            "pattern_aborted": "Aborted",
            "pattern_terminated": "Terminated",
            "pattern_timeout": "Timeout",
            "pattern_uninitialized": "Uninitialized",
            "pattern_not_found": "Not found",
            "pattern_denied": "Denied",
            "pattern_refused": "Refused",
            "pattern_unauthorized": "Unauthorized",
            "pattern_expired": "Expired",
            "pattern_http_4xx": "4xx",
            "pattern_http_5xx": "5xx",
        }

        for object_name, label in expected_labels.items():
            checkbox = self.window.findChild(QCheckBox, object_name)
            self.assertIsNotNone(checkbox)
            self.assertEqual(checkbox.text(), label)

        self.window.findChild(QCheckBox, "pattern_error_colon").setChecked(False)
        self.window.findChild(QCheckBox, "pattern_error").setChecked(False)
        config = self.window.build_config()
        self.assertNotIn("error_colon", config.enabled_patterns)
        self.assertNotIn("error", config.enabled_patterns)

    def test_plain_text_match_case_is_per_item_and_controls_analysis(self):
        self.window._document.filter_panel._tabs.setCurrentIndex(2)
        input_box = self.window.findChild(QLineEdit, "customPattern")
        pattern_list = self.window.findChild(QListWidget, "customPatternList")
        for _ in range(2):
            input_box.setText("Error")
            input_box.returnPressed.emit()
        rows = [pattern_list.itemWidget(pattern_list.item(i)) for i in range(2)]
        buttons = [row.findChild(QPushButton, "customPatternMatchCaseButton") for row in rows]
        self.assertTrue(all(button.isEnabled() and not button.isChecked() for button in buttons))
        buttons[0].click()
        self.assertEqual(self.window.build_config().custom_pattern_match_case, (True, False))
        self.window.show()
        self.app.processEvents()
        for row, button in zip(rows, buttons):
            remove = row.findChild(QPushButton, "customPatternRemoveButton")
            self.assertLess(button.geometry().right(), remove.geometry().left())
            self.assertTrue(row.rect().contains(button.geometry()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.log"
            path.write_text("Error\nerror\nERROR\n", encoding="utf-8")
            self._stage_file(path)
            self._click_analyze_and_wait()
            counts = self.window._document.session.analysis.category_match_counts
            self.assertEqual((counts["custom_1"], counts["custom_2"]), (1, 3))
            buttons[0].click()
            self._click_analyze_and_wait()
            self.assertEqual(self.window._document.session.analysis.category_match_counts["custom_1"], 3)
        buttons[1].click()
        rows[0].findChild(QPushButton, "customPatternRemoveButton").click()
        self.assertEqual(self.window.build_config().custom_pattern_match_case, (True,))
        input_box.setText("New")
        input_box.returnPressed.emit()
        self.assertEqual(self.window.build_config().custom_pattern_match_case, (True, False))

    def test_exclude_toggle_filters_analysis_and_survives_other_item_deletion(self):
        self.window._document.filter_panel._tabs.setCurrentIndex(2)
        entry = self.window.findChild(QLineEdit, "customPattern")
        pattern_list = self.window.findChild(QListWidget, "customPatternList")
        for text in ("unused", "Skip"):
            entry.setText(text)
            entry.returnPressed.emit()
        row = pattern_list.itemWidget(pattern_list.item(1))
        exclude = row.findChild(QPushButton, "customPatternExcludeButton")
        case = row.findChild(QPushButton, "customPatternMatchCaseButton")
        self.assertFalse(exclude.isChecked())
        self.assertEqual(exclude.focusPolicy(), Qt.FocusPolicy.NoFocus)
        exclude.click()
        self.assertFalse(case.isChecked())
        self.window.show()
        self.app.processEvents()
        self.assertLess(exclude.geometry().right(), case.geometry().left())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exclude.log"
            path.write_text("ERROR: keep\nERROR: Skip\nERROR: skip\n", encoding="utf-8")
            self._stage_file(path)
            self._click_analyze_and_wait()
            self.assertEqual(self.window._document.session.analysis.category_match_counts["error_colon"], 1)
            case.click()
            self._click_analyze_and_wait()
            self.assertEqual(self.window._document.session.analysis.category_match_counts["error_colon"], 2)
            exclude.click()
            self._click_analyze_and_wait()
            counts = self.window._document.session.analysis.category_match_counts
            self.assertEqual(counts["error_colon"], 3)
            self.assertEqual(counts["custom_2"], 1)
        exclude.click()
        first_row = pattern_list.itemWidget(pattern_list.item(0))
        first_row.findChild(QPushButton, "customPatternRemoveButton").click()
        config = self.window.build_config()
        self.assertEqual(config.custom_pattern_exclude, (True,))
        self.assertEqual(config.custom_pattern_match_case, (True,))

    def test_regex_exclude_toggle_controls_analysis_and_stays_with_item(self):
        self.window._document.filter_panel._tabs.setCurrentIndex(2)
        entry = self.window.findChild(QLineEdit, "regexPattern")
        pattern_list = self.window.findChild(QListWidget, "regexPatternList")
        for text in ("unused", r"skip\d+"):
            entry.setText(text)
            entry.returnPressed.emit()
        row = pattern_list.itemWidget(pattern_list.item(1))
        exclude = row.findChild(QPushButton, "regexPatternExcludeButton")
        self.assertFalse(exclude.isChecked())
        self.assertEqual(exclude.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(exclude.toolTip(), "Click for this pattern to exclude matches")
        self.window.show()
        self.app.processEvents()
        remove = row.findChild(QPushButton, "regexPatternRemoveButton")
        self.assertLess(exclude.geometry().right(), remove.geometry().left())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regex-exclude.log"
            path.write_text("ERROR: keep\nERROR: skip42\nERROR: SKIP42\n", encoding="utf-8")
            self._stage_file(path)
            QTest.mouseClick(exclude, Qt.MouseButton.LeftButton)
            self.assertFalse(exclude.hasFocus())
            self.assertEqual(exclude.toolTip(), "Click for this pattern to not exclude matches")
            self._click_analyze_and_wait()
            counts = self.window._document.session.analysis.category_match_counts
            self.assertEqual(counts["error_colon"], 2)
            self.assertNotIn("regex_2", counts)
            exclude.click()
            self._click_analyze_and_wait()
            counts = self.window._document.session.analysis.category_match_counts
            self.assertEqual(counts["error_colon"], 3)
            self.assertEqual(counts["regex_2"], 1)
        exclude.click()
        pattern_list.itemWidget(pattern_list.item(0)).findChild(
            QPushButton, "regexPatternRemoveButton",
        ).click()
        self.assertEqual(self.window.build_config().regex_pattern_exclude, (True,))
        entry.setText("new")
        entry.returnPressed.emit()
        self.assertEqual(self.window.build_config().regex_pattern_exclude, (True, False))

    def test_loading_stages_file_until_analyze_button_is_pressed(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server.log"
            log_path.write_text(
                "before\nERROR: boom\nafter\n",
                encoding="utf-8",
            )

            loaded = self._stage_file(log_path)
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            staged_output = results.toPlainText()
            staged_status = self.window.statusBar().currentMessage()

            self.assertEqual(self.window._document.session.path, log_path)
            self.assertEqual(
                self.window._document.session.lines,
                ("before", "ERROR: boom", "after"),
            )
            self.assertEqual(self.window._document.session.encoding, "UTF-8")
            self.assertEqual(self.window._document.session.phase, AnalysisPhase.IDLE)

            self.window.findChild(QLineEdit, "customPattern").returnPressed.emit()
            output_after_return = results.toPlainText()

            with (
                patch(
                    "logreader.workers.analysis_worker.perf_counter",
                    side_effect=(10.0, 12.3456),
                ),
                patch(
                    "logreader.ui.results.results_renderer.perf_counter",
                    side_effect=(20.0, 24.5678),
                ),
            ):
                self._click_analyze_and_wait()
            output = results.toPlainText()
            html = results.document().toHtml()

            self.assertEqual(self.window._document.session.phase, AnalysisPhase.IDLE)
            self.assertIsNotNone(self.window._document.session.analysis)
            self.assertIsNotNone(self.window._document.session.analysis_config)
            self.assertAlmostEqual(self.window._document.session.analysis_seconds, 2.3456)
            self.assertAlmostEqual(
                self.window._document.session.rendering_seconds,
                4.5678,
            )

        self.assertTrue(loaded)
        self.assertEqual(staged_output, "")
        self.assertEqual(output_after_return, "")
        self.assertEqual("Loaded as UTF-8: server.log", staged_status)
        self.assertNotIn("Performance results", output)
        self.assertNotIn("Analysis:", output)
        self.assertNotIn("Rendering:", output)
        self.assertIn("ERROR: boom", output)
        self.assertNotIn("\033[", output)
        self.assertIn(COLORS["match"].name(), html)
        self.assertIn(COLORS["matched_text"].name(), html)
        self.assertNotIn(COLORS["line_number"].name(), html)
        self.assertGreater(self.window._document.results_view.editor.gutter.width(), 0)
        self.assertIn("UTF-8", self.window.statusBar().currentMessage())

    def test_analysis_runs_in_background_and_restores_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "background.log"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")
            self._stage_file(log_path)
            self.window.show()
            self.app.processEvents()

            started = Event()
            release = Event()

            def blocking_analysis(lines, patterns, *, combined=False, line_offset=0, cancellation=None):
                started.set()
                if not release.wait(2):
                    raise TimeoutError("Test analysis was not released")
                return analyze_lines(lines, patterns, combined=combined, line_offset=line_offset, cancellation=cancellation)

            completed = QSignalSpy(self.window.analysis_finished)
            analyze_button = self.window.findChild(
                QPushButton,
                "analyzeButton",
            )
            open_button = self.window.findChild(QPushButton, "openButton")
            filter_group = self.window.findChild(QGroupBox, "filterGroup")
            line_wrap = self.window.findChild(QCheckBox, "lineWrapCheck")
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            search = self.window.findChild(QLineEdit, "resultsSearch")
            search.setText("error")
            search.selectAll()
            search.setFocus()
            self.app.processEvents()
            self.assertIs(self.app.focusWidget(), search)
            self.assertEqual(search.selectedText(), "error")

            try:
                with patch(
                    "logreader.workers.analysis_worker.analyze_lines",
                    side_effect=blocking_analysis,
                ) as mocked_analysis:
                    analyze_button.click()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(analyze_button.isEnabled())
                    self.assertEqual(analyze_button.text(), "Analyzing…")
                    self.assertIs(self.app.focusWidget(), results)
                    self.assertEqual(search.selectedText(), "")
                    self.assertTrue(open_button.isEnabled())
                    self.assertTrue(filter_group.isEnabled())
                    self.assertIn(
                        "Analyzing",
                        self.window.statusBar().currentMessage(),
                    )
                    self.assertTrue(self.window._document._analysis_busy_timer.isActive())
                    self.assertEqual(
                        self.window._document._analysis_busy_timer.interval(),
                        1_000,
                    )

                    analyze_button.click()
                    self.assertEqual(mocked_analysis.call_count, 1)

                    self.window._document._show_analysis_busy()
                    self.assertFalse(analyze_button.isEnabled())
                    self.assertEqual(analyze_button.text(), "Analyzing…")
                    self.assertTrue(open_button.isEnabled())
                    self.assertTrue(filter_group.isEnabled())
                    self.assertIn(
                        "Analyzing: background.log",
                        self.window.statusBar().currentMessage(),
                    )

                    line_wrap.click()
                    self.assertTrue(line_wrap.isChecked())

                    release.set()
                    self._wait_for_signal(completed)
            finally:
                release.set()

        self.assertTrue(analyze_button.isEnabled())
        self.assertEqual(analyze_button.text(), "&Analyze")
        self.assertTrue(open_button.isEnabled())
        self.assertTrue(filter_group.isEnabled())
        self.assertIn(
            "ERROR: boom",
            self.window.findChild(QPlainTextEdit, "resultsView").toPlainText(),
        )

    def test_analyze_button_keeps_analyzing_label_during_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "rendering-label.log"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")
            self._stage_file(log_path)

            config = self.window.build_config()
            analysis = analyze_lines(
                self.window._document.session.lines,
                config.search_patterns(),
                combined=config.combined_view,
            )
            request = self.window._document.session.begin_analysis(
                config,
                len(config.search_patterns()),
            )
            self.window._document._set_analysis_busy(True)

            try:
                with patch.object(
                    self.window._document.results_view,
                    "start_rendering",
                ) as start_rendering:
                    self.window._document._complete_analysis(
                        request.request_id,
                        analysis,
                        0.1,
                    )

                self.assertEqual(
                    self.window._document.session.phase,
                    AnalysisPhase.RENDERING,
                )
                self.assertEqual(
                    self.window.findChild(QPushButton, "analyzeButton").text(),
                    "Analyzing…",
                )
                start_rendering.assert_called_once()
            finally:
                self.window._document.session.fail_request(request.request_id)
                self.window._document._finish_analysis_request()

    def test_result_rendering_yields_between_formatted_batches(self):
        config = self.window.build_config()
        analysis = analyze_lines(
            ("before", "ERROR: boom", "after"),
            config.search_patterns(),
            combined=config.combined_view,
        )
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = self.window.findChild(QPlainTextEdit, "resultsView")
        line_wrap = self.window.findChild(QCheckBox, "lineWrapCheck")
        search = self.window.findChild(QLineEdit, "resultsSearch")
        count = self.window.findChild(QLabel, "resultsSearchCount")
        completed = QSignalSpy(results_view.rendering_completed)

        with patch("logreader.ui.results.results_renderer.INCREMENTAL_RENDER_BATCH_MS", 0):
            results_view.start_rendering(
                17,
                "incremental.log",
                analysis,
                config,
            )
            renderer = results_view._renderer
            self.assertIsNotNone(renderer)
            self.assertTrue(renderer._timer.isActive())
            self.assertEqual(results.toPlainText(), "")
            self.assertFalse(results.updatesEnabled())

            renderer._timer.stop()
            # Index construction also yields before document rendering begins.
            while renderer._index_work is not None:
                renderer._render_next_batch()
                renderer._timer.stop()
            renderer._render_next_batch()
            renderer._timer.stop()
            self.assertEqual(results.toPlainText(), "Matches (1 total):\n")
            self.assertEqual(completed.count(), 0)

            search.setText("e")
            search.returnPressed.emit()
            wait_for_search(self.window)
            self.assertTrue(count.isHidden())
            self.assertEqual(results.extraSelections(), [])

            line_wrap.click()
            self.assertTrue(line_wrap.isChecked())

            renderer._timer.start(0)
            self._wait_for_signal(completed)

        self.assertTrue(results.updatesEnabled())
        self.assertNotIn("incremental.log", results.toPlainText())
        self.assertIn("ERROR: boom", results.toPlainText())
        self.assertTrue(count.isHidden())
        self.assertEqual(results.extraSelections(), [])

    def test_results_view_cancels_incremental_rendering(self):
        config = self.window.build_config()
        analysis = analyze_lines(
            ("before", "ERROR: boom", "after"),
            config.search_patterns(),
            combined=config.combined_view,
        )
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results = results_view.editor
        completed = QSignalSpy(results_view.rendering_completed)
        failed = QSignalSpy(results_view.rendering_failed)

        with patch("logreader.ui.results.results_renderer.INCREMENTAL_RENDER_BATCH_MS", 0):
            results_view.start_rendering(
                23,
                "cancelled.log",
                analysis,
                config,
            )
            renderer = results_view._renderer
            self.assertIsNotNone(renderer)
            renderer._timer.stop()
            renderer._render_next_batch()
            renderer._timer.stop()
            partial_output = results.toPlainText()

            results_view.cancel_rendering()
            self.assertFalse(renderer._timer.isActive())
            self.assertTrue(results.updatesEnabled())
            renderer._render_next_batch()
            self.app.processEvents()

        self.assertIsNone(results_view._renderer)
        self.assertEqual(results.toPlainText(), partial_output)
        self.assertEqual(completed.count(), 0)
        self.assertEqual(failed.count(), 0)

    def test_results_view_prepends_performance_timings(self):
        results_view = self.window.findChild(ResultsView, "resultsPanel")
        results_view.editor.setPlainText("Rendered output")

        results_view.prepend_performance_timings(1.2345, 6.7894)

        self.assertTrue(
            results_view.editor.toPlainText().startswith(
                "Performance results\n"
                "Analysis: 1.234 s\n"
                "Rendering: 6.789 s\n"
                "Total: 8.024 s\n\n"
                "Analysis per 100K source rows: N/A\n"
                "Rendering per 100K result rows: N/A\n\n"
                "Rendered output"
            )
        )
        self.assertEqual(results_view.editor.textCursor().position(), 0)

    def test_summary_grid_fills_rows_and_preserves_long_entries(self):
        from logreader.ui.results.result_formatting import _iter_positive_summary_entries, _iter_summary_entries

        def text(entries):
            return "".join(value for value, _, _ in _iter_summary_entries(entries))

        oversized = "Z" * 101
        self.assertEqual(
            "".join(value for value, _, _ in _iter_positive_summary_entries([
                ("ERROR:", 13), ("ERROR", 206), ("EXCEPTION", 4),
                (oversized, 3), ("FATAL", 4),
            ])),
            "ERROR:           13     ERROR           206     EXCEPTION         4\n"
            f"{oversized} 3     FATAL             4",
        )
        self.assertEqual(
            text([("A" * 100, None), ("FAILED", None), (oversized, None), ("FATAL", None)]),
            f"{'A' * 100}\nFAILED\n{oversized}\nFATAL",
        )

    def test_summary_places_custom_and_regex_entries_after_presets(self):
        from dataclasses import replace
        from logreader.config import LogreaderConfig
        from logreader.ui.results.result_formatting import _iter_analysis_render_operations

        for combined in (False, True):
            config = LogreaderConfig(
                enabled_patterns=("error_colon",), custom_patterns=("needle",),
                regex_patterns=(r"code=\d+",), combined_view=combined,
            )
            for source, expected in (
                ("ERROR: needle code=42", "Matches (3 total):\nERROR:            1     needle            1     code=\\d+          1\n"),
                ("ordinary", "Matches (0 total):\n0\n\nNo matches:\nERROR:, needle, code=\\d+\n"),
            ):
                analysis = analyze_lines((source,), config.search_patterns(), combined=combined)
                analysis = replace(
                    analysis,
                    categories=dict(reversed(list(analysis.categories.items()))),
                    category_match_counts=dict(reversed(list(analysis.category_match_counts.items()))),
                )
                output = "".join(
                    value for value, _, _ in _iter_analysis_render_operations("test.log", analysis, config)
                )
                self.assertTrue(output.startswith(expected), output)

    def test_zero_match_patterns_stay_in_summary_without_blank_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "summary.log"
            log_path.write_text("ERROR: boom\n", encoding="utf-8")

            self._stage_file(log_path)
            self._click_analyze_and_wait()
            output = self.window.findChild(
                QPlainTextEdit,
                "resultsView",
            ).toPlainText()

        self.assertIn(
            "No matches:\nERROR, EXCEPTION:, EXCEPTION, FAILED, FAILURE, FATAL, CRITICAL, REFUSED\n",
            output,
        )
        self.assertNotIn(APP_VERSION, output)
        self.assertNotIn(str(log_path), output)
        self.assertNotIn("source lines", output)
        self.assertTrue(output.startswith("Matches (1 total):\n"))
        self.assertIn("REFUSED\n\nERROR: boom", output)
        self.assertNotIn("Total matches", output)
        self.assertNotIn("FAILED - 0 matches", output)
        self.assertNotIn("FATAL - 0 matches", output)
        self.assertNotIn("No matches.", output)

    def test_combined_view_replaces_categories_and_includes_enabled_searches(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(0)
        self.window.findChild(QCheckBox, "combinedViewCheck").setChecked(True)
        self.window.findChild(QCheckBox, "pattern_fatal").setChecked(False)
        self.window.findChild(QLineEdit, "customPattern").setText("panic")
        self.window.findChild(QPushButton, "customPatternAddButton").click()
        self.window.findChild(QLineEdit, "regexPattern").setText(r"code=\d+")
        self.window.findChild(QPushButton, "regexPatternAddButton").click()

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "combined.log"
            log_path.write_text(
                "ERROR: failed\npanic code=42\nFATAL ignored\n",
                encoding="utf-8",
            )

            self._stage_file(log_path)
            self._click_analyze_and_wait()
            output = self.window.findChild(
                QPlainTextEdit,
                "resultsView",
            ).toPlainText()

        self.assertEqual(
            tuple(self.window._document.session.analysis.categories),
            ("combined",),
        )
        summary = output.split("\nERROR: failed", 1)[0]
        self.assertTrue(summary.startswith(
            "Matches (4 total):\nERROR:            1     FAILED            1     panic             1\n"
            "code=\\d+          1\n\n"
        ), summary)
        self.assertIn("No matches:\nERROR, EXCEPTION:, EXCEPTION, FAILURE, CRITICAL, REFUSED\n", summary)
        self.assertNotIn("Total matches", summary)
        self.assertNotIn("Total matches", output)
        self.assertNotIn(" · ", summary)
        self.assertIn("ERROR: failed", output)
        self.assertIn("panic code=42", output)
        self.assertNotIn("FATAL ignored", output)
        self.assertEqual(
            "All 3 lines scanned - UTF-8",
            self.window.statusBar().currentMessage(),
        )

    def test_scan_limit_selects_tail_and_preserves_source_numbers(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(0)
        self.window.findChild(QSpinBox, "limitSpin").setValue(1)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "limited.log"
            log_path.write_text(
                "ERROR: first\nneutral\nERROR: second\n",
                encoding="utf-8",
            )

            self._stage_file(log_path)
            self._click_analyze_and_wait()
            output = self.window.findChild(
                QPlainTextEdit,
                "resultsView",
            ).toPlainText()

        self.assertNotIn("ERROR: first", output)
        self.assertIn("ERROR: second", output)
        view = self.window._document.results_view
        self.assertEqual(view.model.line(0).number, 3)
        self.assertNotIn("Showing", output)
        self.assertEqual("1 of 3 lines were scanned - UTF-8", self.window.statusBar().currentMessage())

    def test_scan_limit_warning_tracks_completed_analysis_and_preserves_results(self):
        from logreader.ui.results.results_editor import SummaryBlock

        path = Path(self.directory.name) / "limited-warning.log"
        path.write_text("ERROR: first\nneutral\nERROR: third\nneutral\n", encoding="utf-8")
        self._stage_file(path)
        page = self.window._document
        view = page.results_view
        limit_control = self.window.findChild(QSpinBox, "limitSpin")
        for timings in (False, True):
            page.show_performance = timings
            for limit in (2, 4, 5, 2):
                with self.subTest(timings=timings, limit=limit):
                    limit_control.setValue(limit)
                    self._click_analyze_and_wait()
                    editor = view.editor
                    output = editor.toPlainText()
                    limited = limit < 4
                    self.assertEqual(output.count("WARNING:"), int(limited))
                    if limited:
                        self.assertTrue(output.startswith("WARNING: Only 2 of this file’s 4 lines"))
                        warning_text = " ".join(output.split())
                        self.assertIn("these results cover the last 2 lines", warning_text)
                        self.assertIn("end/tail of the file", warning_text)
                        self.assertIn('increase "Max lines scanned" to at least 4 and press Analyze again.', warning_text)
                        self.assertIn("\n\nIf you want the entire file to be scanned", output)
                        self.assertIn("more system memory", output)
                        self.assertEqual(editor.document().find("WARNING:").charFormat().foreground().color(),
                                         COLORS["warning"])
                        self.assertEqual(editor.document().find("Only 2").charFormat().foreground().color(),
                                         COLORS["muted"])
                    if timings:
                        self.assertLess(output.index("Performance results"), output.index("Matches ("))
                    summary = editor.document().find("Matches (").block().userData()
                    self.assertIsInstance(summary, SummaryBlock)
                    self.assertTrue(summary.first)
                    first = editor.document().findBlockByNumber(view._source_map.block(0))
                    self.assertEqual(first.text(), view.model.line(0).text)
                    self.assertIsNone(first.userData())
                    editor.selectAll()
                    self.assertNotIn("WARNING:", editor.createMimeDataFromSelection().text())

    def test_entry_separation_is_optional_and_uses_blank_spacing(self):
        self.window.findChild(QSpinBox, "contextSpin").setValue(0)
        self.window.findChild(
            QCheckBox,
            "separateEntriesCheck",
        ).setChecked(False)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "separated.log"
            log_path.write_text(
                "ERROR: first\nneutral\nneutral\nneutral\nneutral\nERROR: second\n",
                encoding="utf-8",
            )

            self._stage_file(log_path)
            results = self.window.findChild(QPlainTextEdit, "resultsView")
            self._click_analyze_and_wait()
            without_separator = results.toPlainText()

            self.window.findChild(
                QCheckBox,
                "separateEntriesCheck",
            ).setChecked(True)
            self._click_analyze_and_wait()
            with_separator = results.toPlainText()

        adjacent_results = (
            "ERROR: first\n"
            "ERROR: second"
        )
        separated_results = (
            "ERROR: first\n\n"
            "ERROR: second"
        )
        self.assertIn(adjacent_results, without_separator)
        self.assertNotIn(separated_results, without_separator)
        self.assertIn(separated_results, with_separator)
        self.assertNotIn("-------->", with_separator)


if __name__ == "__main__":
    unittest.main()
