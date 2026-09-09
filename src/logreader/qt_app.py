"""Minimal PySide6 desktop frontend for Logreader."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import (
    QEvent,
    QObject,
    Qt,
    QSize,
    QSignalBlocker,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPalette,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .config import APP_VERSION, LogreaderConfig
from .document_page import DocumentPage
from .document_session import LoadPhase
from .theme import THEME_COLORS
from .work_queue import WorkScheduler


COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}

INTERFACE_STYLE_SHEET = f"""
QMainWindow {{
    background-color: {THEME_COLORS['ui_canvas']};
    color: {THEME_COLORS['ui_text']};
}}
QWidget#centralWidget {{
    background-color: {THEME_COLORS['ui_canvas']};
    color: {THEME_COLORS['ui_text']};
}}
QStackedWidget#documentWorkspace,
QStackedWidget#documentPages,
QTabBar#documentTabs {{
    background-color: {THEME_COLORS['ui_canvas']};
}}
QTabBar::tab {{
    background-color: {THEME_COLORS['ui_button']};
    color: {THEME_COLORS['ui_muted']};
    border: 1px solid {THEME_COLORS['ui_border']};
    padding: 6px 12px;
}}
QTabBar::tab:selected {{
    background-color: {THEME_COLORS['ui_island']};
    color: {THEME_COLORS['ui_text']};
    border-bottom: 2px solid {THEME_COLORS['ui_accent']};
}}
QTabBar::tab:hover {{
    background-color: {THEME_COLORS['ui_button_hover']};
}}
QLineEdit#customPattern, QLineEdit#regexPattern {{
    placeholder-text-color: rgba({COLORS['ui_muted'].red()}, {COLORS['ui_muted'].green()}, {COLORS['ui_muted'].blue()}, 90);
}}
QWidget#fileControlsRow {{
    background-color: {THEME_COLORS['ui_canvas']};
    border: 1px solid {THEME_COLORS['ui_border']};
    border-radius: 6px;
}}
QWidget#resultsHeader {{
    background-color: {THEME_COLORS['background']};
    border: none;
    border-bottom: 1px solid {THEME_COLORS['border']};
    border-top: 1px solid {THEME_COLORS['border']};
}}
QLabel {{
    background-color: transparent;
    border: none;
    color: {THEME_COLORS['ui_text']};
}}
QLabel#pathLabel {{
    color: {THEME_COLORS['ui_muted']};
}}
QGroupBox#filterGroup {{
    background-color: {THEME_COLORS['ui_surface']};
    border: 1px solid {THEME_COLORS['ui_border']};
    border-radius: 7px;
    color: {THEME_COLORS['ui_text']};
    margin-top: 10px;
}}
QGroupBox#filterGroup::title {{
    color: {THEME_COLORS['ui_accent']};
    font-weight: 600;
    left: 10px;
    padding: 0 4px;
    subcontrol-origin: margin;
}}
QGroupBox#pairedPatternGroup,
QGroupBox#textPatternGroup,
QGroupBox#customPatternGroup,
QGroupBox#regexPatternGroup,
QGroupBox#httpStatusGroup {{
    background-color: {THEME_COLORS['ui_island']};
    border: 1px solid {THEME_COLORS['ui_border']};
    border-radius: 6px;
    color: {THEME_COLORS['ui_text']};
    margin-top: 10px;
}}
QGroupBox#pairedPatternGroup::title,
QGroupBox#textPatternGroup::title,
QGroupBox#customPatternGroup::title,
QGroupBox#regexPatternGroup::title,
QGroupBox#httpStatusGroup::title {{
    color: {THEME_COLORS['ui_accent']};
    font-weight: 600;
    left: 8px;
    padding: 0 4px;
    subcontrol-origin: margin;
}}
QPushButton {{
    background-color: {THEME_COLORS['ui_button']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    border-radius: 5px;
    color: {THEME_COLORS['ui_text']};
    min-height: 20px;
    padding: 3px 10px;
}}
QPushButton:hover {{
    background-color: {THEME_COLORS['ui_button_hover']};
    border-color: {THEME_COLORS['ui_accent']};
}}
QPushButton:focus {{
    border-color: {THEME_COLORS['ui_accent']};
}}
QPushButton:pressed {{
    background-color: {THEME_COLORS['ui_button_pressed']};
}}
QPushButton:disabled {{
    background-color: {THEME_COLORS['ui_disabled']};
    border-color: {THEME_COLORS['ui_border']};
    color: {THEME_COLORS['ui_disabled_text']};
}}
QPushButton#openButton,
QPushButton#toggleAllButton {{
    background-color: {THEME_COLORS['ui_island']};
}}
QPushButton#togglePairedButton,
QPushButton#toggleTextButton,
QPushButton#customPatternAddButton,
QPushButton#regexPatternAddButton {{
    background-color: {THEME_COLORS['ui_island']};
}}
QPushButton#maximizeResultsButton {{
    background-color: {THEME_COLORS['background']};
}}
QPushButton#analyzeButton {{
    background-color: {THEME_COLORS['ui_primary']};
    border-color: {THEME_COLORS['ui_primary']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#analyzeButton:hover {{
    background-color: {THEME_COLORS['ui_primary_hover']};
    border-color: {THEME_COLORS['ui_accent']};
}}
QPushButton#analyzeButton:disabled {{
    background-color: {THEME_COLORS['ui_island']};
    border-color: {THEME_COLORS['ui_border']};
    color: {THEME_COLORS['ui_disabled_text']};
}}
QPushButton#customPatternAddButton,
QPushButton#regexPatternAddButton {{
    min-width: 42px;
}}
QPushButton#customPatternRemoveButton,
QPushButton#regexPatternRemoveButton {{
    background-color: transparent;
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    border-radius: 3px;
    color: {THEME_COLORS['ui_muted']};
    max-height: 16px;
    max-width: 24px;
    min-height: 16px;
    min-width: 24px;
    padding: 0;
}}
QPushButton#customPatternRemoveButton:hover,
QPushButton#regexPatternRemoveButton:hover {{
    background-color: #4a2028;
    border-color: #ff7b72;
    color: #ffffff;
}}
QLineEdit,
QSpinBox {{
    background-color: {THEME_COLORS['ui_island']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    border-radius: 4px;
    color: {THEME_COLORS['ui_text']};
    min-height: 20px;
    padding: 3px 6px;
    selection-background-color: {THEME_COLORS['selection']};
    selection-color: #ffffff;
}}
QSpinBox {{
    padding-right: 24px;
}}
QLineEdit:hover {{
    border-color: {THEME_COLORS['ui_muted']};
}}
QLineEdit:focus,
QSpinBox:focus {{
    border-color: {THEME_COLORS['ui_accent']};
}}
QLineEdit:disabled,
QSpinBox:disabled {{
    background-color: {THEME_COLORS['ui_disabled']};
    color: {THEME_COLORS['ui_disabled_text']};
}}
QSpinBox::up-button,
QSpinBox::down-button {{
    background-color: {THEME_COLORS['ui_island']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    subcontrol-origin: border;
    width: 20px;
}}
QSpinBox::up-button {{
    border-top-right-radius: 3px;
    subcontrol-position: top right;
}}
QSpinBox::down-button {{
    border-top: none;
    border-bottom-right-radius: 3px;
    subcontrol-position: bottom right;
}}
QSpinBox::up-button:hover,
QSpinBox::down-button:hover {{
    background-color: {THEME_COLORS['ui_button_hover']};
    border: 1px solid {THEME_COLORS['ui_accent']};
}}
QSpinBox::up-arrow {{
    height: 6px;
    image: none;
    width: 9px;
}}
QSpinBox::down-arrow {{
    height: 6px;
    image: none;
    width: 9px;
}}
QListWidget {{
    background-color: {THEME_COLORS['ui_field']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    border-radius: 4px;
    color: {THEME_COLORS['ui_text']};
    outline: none;
    selection-background-color: {THEME_COLORS['selection']};
    selection-color: #ffffff;
}}
QListWidget:focus {{
    border-color: {THEME_COLORS['ui_accent']};
}}
QListWidget::item:hover {{
    background-color: {THEME_COLORS['ui_button_pressed']};
}}
QListWidget::item:selected {{
    background-color: {THEME_COLORS['selection']};
    color: #ffffff;
}}
QListWidget QScrollBar:vertical {{
    background-color: {THEME_COLORS['ui_field']};
    width: 10px;
    margin: 0;
}}
QListWidget QScrollBar::handle:vertical {{
    background-color: {THEME_COLORS['scrollbar_handle']};
    border-radius: 4px;
    min-height: 20px;
    margin: 2px;
}}
QListWidget QScrollBar::handle:vertical:hover {{
    background-color: {THEME_COLORS['scrollbar_handle_hover']};
}}
QListWidget QScrollBar::add-line:vertical,
QListWidget QScrollBar::sub-line:vertical {{
    height: 0;
}}
QCheckBox {{
    background-color: transparent;
    color: {THEME_COLORS['ui_text']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    background-color: {THEME_COLORS['ui_field']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    border-radius: 3px;
    height: 14px;
    width: 14px;
}}
QCheckBox::indicator:hover {{
    border-color: {THEME_COLORS['ui_accent']};
}}
QCheckBox::indicator:checked {{
    background-color: {THEME_COLORS['ui_button_pressed']};
    border-color: {THEME_COLORS['ui_accent']};
}}
QCheckBox[islandIndicator="true"]::indicator:unchecked {{
    background-color: {THEME_COLORS['ui_island']};
}}
QCheckBox::indicator:disabled {{
    background-color: {THEME_COLORS['ui_disabled']};
    border-color: {THEME_COLORS['ui_border']};
}}
QCheckBox:hover,
QCheckBox:focus {{
    color: #ffffff;
}}
QCheckBox:disabled {{
    color: {THEME_COLORS['ui_disabled_text']};
}}
QFrame#topSeparatorContext,
QFrame#topSeparatorLimit {{
    color: {THEME_COLORS['ui_border_strong']};
}}
QStatusBar {{
    background-color: {THEME_COLORS['background']};
    border-top: none;
    color: {THEME_COLORS['ui_muted']};
}}
QStatusBar::item {{
    border: none;
}}
QToolTip {{
    background-color: {THEME_COLORS['ui_island']};
    border: 1px solid {THEME_COLORS['ui_border_strong']};
    color: {THEME_COLORS['ui_text']};
    font-weight: 400;
    padding: 4px;
}}
"""


class TabCloseButton(QAbstractButton):
    """A standalone cross with a generous hit target and no button frame."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tabCloseButton")
        self.setFixedSize(20, 20)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Close tab (Ctrl+W)")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API name
        return QSize(20, 20)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(COLORS["ui_text" if self.underMouse() else "ui_muted"], 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(6, 6, 14, 14)
        painter.drawLine(14, 6, 6, 14)


class LogreaderWindow(QMainWindow):
    """Small desktop shell around the shared Logreader engine."""

    analysis_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._apply_interface_palette()
        self.setStyleSheet(INTERFACE_STYLE_SHEET)
        self.setWindowTitle(APP_VERSION)
        self.resize(1080, 760)
        self.setMinimumSize(820, 560)
        self._scheduler = WorkScheduler(self)
        self._build_interface()
        self._next_tab_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self._next_tab_shortcut.activated.connect(lambda: self._cycle_document(1))
        self._previous_tab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        self._previous_tab_shortcut.activated.connect(lambda: self._cycle_document(-1))
        self._close_tab_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self._close_tab_shortcut.activated.connect(
            lambda: self.close_tab(self._tabs.currentIndex())
        )
        QApplication.instance().aboutToQuit.connect(self._shutdown_documents)
        self.statusBar().showMessage("Ready: Open a log file to begin")
        self._drop_overlay = QLabel("Drop file", self)
        self._drop_overlay.setObjectName("dropOverlay")
        self._drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_overlay.setStyleSheet(
            "QLabel#dropOverlay { background-color: rgba(90, 94, 100, 205);"
            " color: #ffffff; font-size: 32px; font-weight: 600;"
            " border: 2px dashed #d0d3d7; }"
        )
        self._drop_overlay.hide()
        self._drop_leave_timer = QTimer(self)
        self._drop_leave_timer.setSingleShot(True)
        self._drop_leave_timer.timeout.connect(self._drop_overlay.hide)
        self.setAcceptDrops(True)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route file drops over every child control through normal file loading."""

        if watched is self:
            if event.type() == QEvent.Type.Resize:
                self._drop_overlay.setGeometry(self.rect())
            elif event.type() == QEvent.Type.Hide:
                self._drop_overlay.hide()

        if (
            event.type() in (
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
                QEvent.Type.Drop,
                QEvent.Type.DragLeave,
            )
            and isinstance(watched, QWidget)
            and watched.window() is self
        ):
            if event.type() == QEvent.Type.DragLeave:
                # A new child target can receive DragEnter in the same event loop.
                self._drop_leave_timer.start(0)
                return True
            self._drop_leave_timer.stop()
            if event.type() == QEvent.Type.Drop:
                self._drop_overlay.hide()
            urls = event.mimeData().urls()
            paths = [
                Path(url.toLocalFile()) for url in urls
                if url.isLocalFile() and Path(url.toLocalFile()).is_file()
            ]
            if (
                not paths
                or not event.possibleActions() & Qt.DropAction.CopyAction
            ):
                self._drop_overlay.hide()
                event.ignore()
            elif event.type() != QEvent.Type.Drop or self.load_files(paths):
                if event.type() != QEvent.Type.Drop:
                    self._drop_overlay.setText("Drop file" if len(paths) == 1 else f"Drop {len(paths)} files")
                    self._drop_overlay.setGeometry(self.rect())
                    self._drop_overlay.show()
                    self._drop_overlay.raise_()
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _build_interface(self) -> None:
        self._documents_by_path: dict[str, DocumentPage] = {}
        central = QWidget(self)
        central.setObjectName("centralWidget")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._tabs = QTabBar(central)
        self._tabs.setObjectName("documentTabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.hide()
        root.addWidget(self._tabs)
        self._file_controls = QWidget(central)
        self._file_controls.setObjectName("fileControlsRow")
        file_row = QHBoxLayout(self._file_controls)
        file_row.setContentsMargins(8, 6, 8, 6)
        file_row.setSpacing(8)
        self._open_button = QPushButton("&Open log…")
        self._open_button.setObjectName("openButton")
        self._open_button.clicked.connect(self.open_file)
        file_row.addWidget(self._open_button)

        self._path_label = QLabel("No file selected")
        self._path_label.setObjectName("pathLabel")
        self._path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        file_row.addWidget(self._path_label, 1)

        self._analyze_button = QPushButton("&Analyze")
        self._analyze_button.setObjectName("analyzeButton")
        self._analyze_button.setEnabled(False)
        self._analyze_button.clicked.connect(self.analyze_current)
        file_row.addWidget(self._analyze_button)
        action_margin = QWidget(central)
        action_layout = QVBoxLayout(action_margin)
        action_layout.setContentsMargins(12, 12, 12, 0)
        action_layout.addWidget(self._file_controls)
        root.addWidget(action_margin)
        self._workspace = QStackedWidget(central)
        self._workspace.setObjectName("documentWorkspace")
        self._empty_page = QLabel("Open or drop a log file to begin", self._workspace)
        self._empty_page.setObjectName("emptyDocumentPage")
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._workspace.addWidget(self._empty_page)
        self._pages = QStackedWidget(self._workspace)
        self._pages.setObjectName("documentPages")
        self._workspace.addWidget(self._pages)
        self._tabs.currentChanged.connect(self._current_document_changed)
        root.addWidget(self._workspace, 1)
        self.setCentralWidget(central)

    @property
    def _document(self) -> DocumentPage | None:
        """The selected page; document callbacks never use this lookup."""
        return self._pages.currentWidget()

    def _select_document(self, page: DocumentPage) -> None:
        self._tabs.setCurrentIndex(self._pages.indexOf(page))

    def _cycle_document(self, step: int) -> None:
        count = self._tabs.count()
        if count > 1:
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + step) % count)

    def close_tab(self, index: int) -> None:
        """Remove a tab atomically, then dispose its document's pending work."""
        if not 0 <= index < self._tabs.count():
            return
        page = self._pages.widget(index)
        key = os.path.normcase(str(page.session.path))
        self._documents_by_path.pop(key, None)
        close_button = self._tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
        self._tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        if close_button is not None:
            close_button.deleteLater()
        # Do not present an intermediate state with mismatched tab/page indexes.
        with QSignalBlocker(self._tabs), QSignalBlocker(self._pages):
            self._pages.removeWidget(page)
            self._tabs.removeTab(index)
        self._refresh_tab_labels()
        self._current_document_changed(self._tabs.currentIndex())
        page.dispose()

    @Slot()
    def _shutdown_documents(self) -> None:
        self._scheduler.shutdown()
        while self._tabs.count():
            self.close_tab(self._tabs.count() - 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shutdown_documents()
        super().closeEvent(event)

    @Slot(int)
    def _current_document_changed(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._tabs.setVisible(self._tabs.count() > 0)
        page = self._document
        for index in range(self._pages.count()):
            other = self._pages.widget(index)
            if other is not page:
                other.set_render_active(False)
        if page is not None:
            page.set_render_active(True)
        self._workspace.setCurrentWidget(self._pages if page else self._empty_page)
        path = page.session.path if page else None
        self._path_label.setText(path.name if path else "No file selected")
        self._path_label.setToolTip(str(path) if path else "")
        self.setWindowTitle(f"{APP_VERSION} — {path.name}" if path else APP_VERSION)
        self.statusBar().showMessage(
            page.status_message if page else "Ready: Open a log file to begin"
        )
        self._present_analysis_busy()

    @Slot(str)
    def _present_document_status(self, message: str) -> None:
        self._refresh_tab_labels()
        if self.sender() is self._document:
            self.statusBar().showMessage(message)

    def _refresh_tab_labels(self) -> None:
        pages = [self._pages.widget(index) for index in range(self._tabs.count())]
        for index, page in enumerate(pages):
            path = page.session.path
            peers = [
                other.session.path
                for other in pages
                if other is not page
                and other.session.path.name.casefold() == path.name.casefold()
            ]
            label = path.name
            if peers:
                # Show the shortest parent suffix that distinguishes this file.
                # The tooltip always retains the full path.
                for depth in range(1, len(path.parent.parts) + 1):
                    suffix = Path(*path.parent.parts[-depth:])
                    if all(suffix != Path(*peer.parent.parts[-depth:]) for peer in peers):
                        break
                label = f"{path.name} — {suffix}"
            if page.session.load_phase is LoadPhase.LOADING:
                label += " (Queued)" if page.load_queued else " (Loading…)"
            elif page.session.load_phase is LoadPhase.FAILED:
                label += " (Failed)"
            self._tabs.setTabText(index, label)
            self._tabs.setTabToolTip(index, str(path))

    def _apply_interface_palette(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, COLORS["ui_canvas"])
        palette.setColor(QPalette.ColorRole.WindowText, COLORS["ui_text"])
        palette.setColor(QPalette.ColorRole.Base, COLORS["ui_field"])
        palette.setColor(QPalette.ColorRole.AlternateBase, COLORS["ui_island"])
        palette.setColor(QPalette.ColorRole.Text, COLORS["ui_text"])
        palette.setColor(QPalette.ColorRole.Button, COLORS["ui_button"])
        palette.setColor(QPalette.ColorRole.ButtonText, COLORS["ui_text"])
        palette.setColor(QPalette.ColorRole.Highlight, COLORS["ui_primary"])
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, COLORS["ui_muted"])
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            COLORS["ui_disabled_text"],
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            COLORS["ui_disabled_text"],
        )
        self.setPalette(palette)

    def build_config(self) -> LogreaderConfig:
        """Build the shared configuration represented by the controls."""

        return self._document.build_config() if self._document else LogreaderConfig()

    def open_file(self) -> None:
        """Prompt for a local log file and stage it for analysis."""

        initial_directory = (
            self._document.session.path.parent
            if self._document is not None and self._document.session.path is not None
            else Path.home()
        )
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Open log files",
            str(initial_directory),
            "Log and text files (*.log *.txt);;All files (*)",
        )
        if filenames:
            self.load_files(filenames)

    def load_file(self, source_path: str | Path) -> bool:
        """Open one path through the shared multi-file pipeline."""
        return self.load_files([source_path])

    def load_files(self, source_paths: Sequence[str | Path]) -> bool:
        """Append new documents in input order and select the first requested one."""
        first = None
        for source_path in source_paths:
            page = self._open_path(source_path)
            if first is None:
                first = page
        if first is not None:
            self._select_document(first)
        return first is not None

    def _open_path(self, source_path: str | Path) -> DocumentPage:
        path = Path(source_path)
        try:
            path = path.resolve()
        except (OSError, ValueError):
            path = Path(os.path.abspath(path))
        key = os.path.normcase(str(path))
        existing = self._documents_by_path.get(key)
        if existing is not None:
            if existing.session.load_phase is LoadPhase.FAILED:
                existing.load_file(path)
            return existing

        page = DocumentPage(self._pages, scheduler=self._scheduler)
        page.set_render_active(False)
        page.status_changed.connect(self._present_document_status)
        page.busy_changed.connect(self._present_analysis_busy)
        page.analysis_failed.connect(self._present_analysis_failure)
        page.analysis_finished.connect(self.analysis_finished.emit)
        page.load_file(path)
        self._documents_by_path[key] = page
        self._pages.addWidget(page)
        index = self._tabs.addTab(path.name)
        close_button = TabCloseButton(self._tabs)
        close_button.setAccessibleName(f"Close {path.name}")
        close_button.clicked.connect(
            lambda _checked=False, document=page: self.close_tab(self._pages.indexOf(document))
        )
        self._tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)
        self._refresh_tab_labels()
        return page

    def analyze_current(self) -> None:
        """Dispatch Analyze to the document owning the controls and results."""
        if self._document is not None:
            self._document.analyze()

    @Slot()
    def _present_analysis_busy(self) -> None:
        page = self._document
        busy = page is not None and page.session.is_busy
        self._analyze_button.setEnabled(
            page is not None and page.session.has_document and not busy
        )
        loading = page is not None and page.session.load_phase is LoadPhase.LOADING
        self._analyze_button.setText(
            "Queued…" if page is not None and (page.load_queued or page.analysis_queued)
            else "Loading…" if loading else "Analyzing…" if busy else "&Analyze"
        )
        if page is not None and page.busy_visible:
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()

    @Slot(str)
    def _present_analysis_failure(self, message: str) -> None:
        page = self.sender()
        if page is self._document:
            QMessageBox.warning(self, "Invalid filters", message)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PySide6 desktop application."""

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("Logreader")
    app.setApplicationDisplayName(APP_VERSION)
    window = LogreaderWindow()
    window.show()
    try:
        return app.exec()
    finally:
        window._shutdown_documents()
        # Keep Qt alive until cooperative workers return, including on Quit.
        QThreadPool.globalInstance().waitForDone()


if __name__ == "__main__":
    raise SystemExit(main())
