"""Minimal PySide6 desktop frontend for Logreader."""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter
from typing import Sequence

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import APP_VERSION, LogreaderConfig
from .core import (
    AnalysisResult,
    SearchPattern,
    analyze_lines,
)
from .document_session import AnalysisPhase, DocumentSession
from .file_loader import LogDecodeError, load_log
from .filter_panel import FilterPanel, VisibleCheckBox
from .results_view import ResultsView
from .theme import THEME_COLORS


COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
ANALYSIS_BUSY_DELAY_MS = 1_000

INTERFACE_STYLE_SHEET = f"""
QMainWindow {{
    background-color: {THEME_COLORS['ui_canvas']};
    color: {THEME_COLORS['ui_text']};
}}
QWidget#centralWidget {{
    background-color: {THEME_COLORS['ui_canvas']};
    color: {THEME_COLORS['ui_text']};
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


class AnalysisWorkerSignals(QObject):
    """Cross-thread completion signals for one analysis request."""

    completed = Signal(int, object, float)
    failed = Signal(int, str)


class AnalysisWorker(QRunnable):
    """Run the pure log analysis engine outside Qt's GUI thread."""

    def __init__(
        self,
        request_id: int,
        lines: tuple[str, ...],
        patterns: tuple[SearchPattern, ...],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.lines = lines
        self.patterns = patterns
        self.signals = AnalysisWorkerSignals()

    @Slot()
    def run(self) -> None:
        started = perf_counter()
        try:
            analysis = analyze_lines(self.lines, self.patterns)
        except Exception as error:  # Keep worker failures from stranding the UI.
            self.signals.failed.emit(self.request_id, str(error))
            return

        self.signals.completed.emit(
            self.request_id,
            analysis,
            perf_counter() - started,
        )


class LogreaderWindow(QMainWindow):
    """Small desktop shell around the shared Logreader engine."""

    analysis_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._session = DocumentSession()
        self._analysis_busy_visible = False
        self._analysis_worker: AnalysisWorker | None = None
        self._analysis_pool = QThreadPool.globalInstance()
        self._analysis_busy_timer = QTimer(self)
        self._analysis_busy_timer.setSingleShot(True)
        self._analysis_busy_timer.setInterval(ANALYSIS_BUSY_DELAY_MS)
        self._analysis_busy_timer.timeout.connect(self._show_analysis_busy)

        self._apply_interface_palette()
        self.setStyleSheet(INTERFACE_STYLE_SHEET)
        self.setWindowTitle(APP_VERSION)
        self.resize(1080, 760)
        self.setMinimumSize(820, 560)
        self._build_interface()
        self.statusBar().showMessage("Ready: Open a log file to begin")

    def _build_interface(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._controls_container = QWidget(central_widget)
        self._controls_container.setObjectName("controlsContainer")
        controls_layout = QVBoxLayout(self._controls_container)
        controls_layout.setContentsMargins(12, 12, 12, 10)
        controls_layout.setSpacing(10)

        self._file_controls = QWidget(self._controls_container)
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
        controls_layout.addWidget(self._file_controls)

        self._filter_panel = FilterPanel()
        controls_layout.addWidget(self._filter_panel)
        root_layout.addWidget(self._controls_container)

        self._results_view = ResultsView(
            central_widget,
            checkbox_factory=VisibleCheckBox,
        )
        self._results_view.maximized_changed.connect(
            self._set_results_maximized
        )
        self._results_view.rendering_completed.connect(
            self._complete_rendering
        )
        self._results_view.rendering_failed.connect(self._fail_analysis)
        root_layout.addWidget(self._results_view, 1)
        self.setCentralWidget(central_widget)

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

        return self._filter_panel.build_config()

    @Slot(bool)
    def _set_results_maximized(self, maximized: bool) -> None:
        """Show or hide the window controls around the results panel."""

        controls_visible = not maximized
        self._controls_container.setVisible(controls_visible)
        self._file_controls.setVisible(controls_visible)
        self._filter_panel.setVisible(controls_visible)

    def open_file(self) -> None:
        """Prompt for a local log file and stage it for analysis."""

        initial_directory = (
            self._session.path.parent
            if self._session.path is not None
            else Path.home()
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open log file",
            str(initial_directory),
            "Log and text files (*.log *.txt);;All files (*)",
        )
        if filename:
            self.load_file(filename)

    def load_file(self, source_path: str | Path) -> bool:
        """Load a file without analyzing it, returning whether it could be read."""

        path = Path(source_path)
        try:
            loaded = load_log(path)
        except (OSError, LogDecodeError) as error:
            QMessageBox.critical(
                self,
                "Unable to open log",
                f"Could not read:\n{path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Unable to read {path.name}")
            return False

        was_busy = self._session.is_busy
        self._session.stage_loaded_log(path, loaded)
        if was_busy:
            self._finish_analysis_request()

        self._path_label.setText(path.name)
        self._path_label.setToolTip(str(path))
        self._analyze_button.setEnabled(True)
        self.setWindowTitle(f"{APP_VERSION} — {path.name}")
        self._results_view.reset_for_loaded_file(path.name)
        self.statusBar().showMessage(
            f"{len(loaded.lines):,} lines loaded as {loaded.encoding}  •  "
            "press Analyze to begin"
        )
        return True

    def analyze_current(self) -> None:
        """Analyze the loaded file using the current controls."""

        if not self._session.has_document or self._session.is_busy:
            return

        try:
            config = self.build_config()
            patterns = config.search_patterns()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid filters", str(error))
            self.statusBar().showMessage("Analysis could not be completed")
            return

        request = self._session.begin_analysis(config, len(patterns))
        worker = AnalysisWorker(
            request.request_id,
            self._session.lines,
            patterns,
        )
        worker.signals.completed.connect(self._complete_analysis)
        worker.signals.failed.connect(self._fail_analysis)
        self._analysis_worker = worker
        self._set_analysis_busy(True)
        self._analysis_pool.start(worker)

    @Slot(int, object, float)
    def _complete_analysis(
        self,
        request_id: int,
        analysis: AnalysisResult,
        analysis_seconds: float,
    ) -> None:
        """Render the current worker result back on Qt's GUI thread."""

        if not self._session.begin_rendering(
            request_id,
            analysis,
            analysis_seconds,
        ):
            return

        request = self._session.active_request
        if request is None:
            self._finish_analysis_request()
            return

        self._analysis_worker = None
        self._results_view.start_rendering(
            request_id,
            str(request.source_path),
            analysis,
            request.config,
        )
        self._analyze_button.setText("Rendering…")
        if self._analysis_busy_visible:
            self.statusBar().showMessage(
                f"Rendering results for {request.source_path.name}…"
            )

    @Slot(int, float)
    def _complete_rendering(
        self,
        request_id: int,
        rendering_seconds: float,
    ) -> None:
        """Finalize timings and status after all render batches complete."""

        if not self._session.complete_rendering(
            request_id,
            rendering_seconds,
        ):
            return

        analysis = self._session.analysis
        analysis_seconds = self._session.analysis_seconds
        if analysis is None or analysis_seconds is None:
            self._finish_analysis_request()
            return

        self._results_view.prepend_performance_timings(
            analysis_seconds,
            rendering_seconds,
        )

        match_count = sum(
            result.match_count for result in analysis.categories.values()
        )
        self._finish_analysis_request()
        self.statusBar().showMessage(
            f"{analysis.line_count:,} lines  •  {match_count:,} matches  •  "
            f"{len(analysis.categories)} active patterns  •  "
            f"{self._session.encoding or 'unknown encoding'}"
        )
        self.analysis_finished.emit()

    @Slot(int, str)
    def _fail_analysis(self, request_id: int, message: str) -> None:
        """Restore the interface after a worker-side analysis failure."""

        if not self._session.fail_request(request_id):
            return

        self._finish_analysis_request()
        QMessageBox.warning(self, "Invalid filters", message)
        self.statusBar().showMessage("Analysis could not be completed")

    def _set_analysis_busy(self, busy: bool) -> None:
        if busy:
            self._analysis_busy_visible = False
            self._results_view.editor.setFocus(Qt.FocusReason.OtherFocusReason)
            self._analyze_button.setEnabled(False)
            self._analyze_button.setText("Analyzing…")
            self._analysis_busy_timer.start()
            return

        self._analysis_busy_timer.stop()
        self._analyze_button.setEnabled(self._session.has_document)
        self._analyze_button.setText("&Analyze")
        if self._analysis_busy_visible:
            self._analysis_busy_visible = False
            self.unsetCursor()

    @Slot()
    def _show_analysis_busy(self) -> None:
        if not self._session.is_busy:
            return

        self._analysis_busy_visible = True
        self.setCursor(Qt.CursorShape.WaitCursor)
        request = self._session.active_request
        source_name = request.source_path.name if request is not None else "log"
        if self._session.phase is AnalysisPhase.RENDERING:
            self.statusBar().showMessage(
                f"Rendering results for {source_name}…"
            )
        else:
            pattern_count = request.pattern_count if request is not None else 0
            self.statusBar().showMessage(
                f"Analyzing {source_name} with "
                f"{pattern_count} active patterns…"
            )

    def _finish_analysis_request(self) -> None:
        self._results_view.cancel_rendering()
        self._analysis_worker = None
        self._set_analysis_busy(False)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PySide6 desktop application."""

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("Logreader")
    app.setApplicationDisplayName(APP_VERSION)
    window = LogreaderWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
