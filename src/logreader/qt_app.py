"""Minimal PySide6 desktop frontend for Logreader."""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

from PySide6.QtCore import (
    QObject,
    QPointF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSpinBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from .config import (
    APP_VERSION,
    DEFAULT_ENABLED_PATTERNS,
    HTTP_STATUS_PATTERN_KEYS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    PATTERN_PRESETS_BY_KEY,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
from .core import (
    AnalysisResult,
    CategoryResult,
    ResultLine,
    SearchPattern,
    analyze_lines,
)
from .file_loader import LogDecodeError, load_log
from .presentation import CategoryPresentation, build_category_presentations
from .theme import THEME_COLORS


COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
RULE = "─" * 72
ENTRY_SEPARATOR = "-------->"
FILTER_ALIGNMENT_EXTRA_WIDTH = 115
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


class VisibleCheckBox(QCheckBox):
    """Checkbox with a platform-independent painted checkmark."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().paintEvent(event)
        if self.checkState() == Qt.CheckState.Unchecked:
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            option,
            self,
        )
        if not indicator.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mark_color = (
            QColor("#ffffff")
            if self.isEnabled()
            else COLORS["ui_disabled_text"]
        )
        painter.setPen(
            QPen(
                mark_color,
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        if self.checkState() == Qt.CheckState.PartiallyChecked:
            painter.drawLine(
                QPointF(indicator.left() + 4, indicator.center().y()),
                QPointF(indicator.right() - 4, indicator.center().y()),
            )
            return

        painter.drawLine(
            QPointF(indicator.left() + 3.5, indicator.center().y()),
            QPointF(indicator.left() + 6.5, indicator.bottom() - 3.5),
        )
        painter.drawLine(
            QPointF(indicator.left() + 6.5, indicator.bottom() - 3.5),
            QPointF(indicator.right() - 3, indicator.top() + 3.5),
        )


class VisibleSpinBox(QSpinBox):
    """Spin box with platform-independent painted up/down chevrons."""

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        up_button = self.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxUp,
            self,
        )
        editor_geometry = self.lineEdit().geometry()
        editor_geometry.setRight(up_button.left() - 1)
        self.lineEdit().setGeometry(editor_geometry)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().paintEvent(event)

        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                COLORS["ui_text"],
                1.7,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        for subcontrol, points_down in (
            (QStyle.SubControl.SC_SpinBoxUp, False),
            (QStyle.SubControl.SC_SpinBoxDown, True),
        ):
            button = self.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                subcontrol,
                self,
            )
            if not button.isValid():
                continue

            left, center, right = self._chevron_points(button, points_down)
            painter.drawLine(left, center)
            painter.drawLine(center, right)

    @staticmethod
    def _chevron_points(button, points_down: bool) -> tuple[QPointF, ...]:
        center_x = button.center().x() + 1
        center_y = button.center().y() + (0 if points_down else 1)
        vertical_offset = 1.5 if points_down else -1.5
        return (
            QPointF(center_x - 3.5, center_y - vertical_offset),
            QPointF(center_x, center_y + vertical_offset),
            QPointF(center_x + 3.5, center_y - vertical_offset),
        )


class UnclippedPushButton(QPushButton):
    """Push button that paints its label clear of stylesheet padding clips."""

    _TEXT_INSET = 6

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        option = QStyleOptionButton()
        self.initStyleOption(option)
        label = option.text
        option.text = ""

        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.setPen(option.palette.color(QPalette.ColorRole.ButtonText))
        painter.drawText(
            self.rect().adjusted(
                self._TEXT_INSET,
                0,
                -self._TEXT_INSET,
                0,
            ),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextShowMnemonic,
            label,
        )


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
        self._source_path: Path | None = None
        self._source_lines: tuple[str, ...] = ()
        self._source_encoding: str | None = None
        self._pattern_checkboxes: dict[str, QCheckBox] = {}
        self._results_maximized = False
        self._analysis_busy = False
        self._analysis_busy_visible = False
        self._analysis_request_id = 0
        self._analysis_worker: AnalysisWorker | None = None
        self._analysis_config: LogreaderConfig | None = None
        self._analysis_source_path: Path | None = None
        self._analysis_pattern_count = 0
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

        self._filter_group = self._build_filter_group()
        controls_layout.addWidget(self._filter_group)
        root_layout.addWidget(self._controls_container)

        self._results_panel = QWidget(central_widget)
        self._results_panel.setObjectName("resultsPanel")
        results_panel_layout = QVBoxLayout(self._results_panel)
        results_panel_layout.setContentsMargins(0, 0, 0, 0)
        results_panel_layout.setSpacing(0)

        results_header = QWidget(self._results_panel)
        results_header.setObjectName("resultsHeader")
        results_header.setMinimumHeight(36)
        results_header_layout = QHBoxLayout(results_header)
        results_header_layout.setContentsMargins(8, 5, 8, 5)
        results_header_layout.setSpacing(8)

        self._maximize_results_button = QPushButton("▲")
        self._maximize_results_button.setObjectName("maximizeResultsButton")
        self._maximize_results_button.setAccessibleName("Maximize results")
        self._maximize_results_button.setFixedSize(38, 26)
        self._maximize_results_button.setStyleSheet(
            "QPushButton#maximizeResultsButton {"
            " font-size: 14px; font-weight: 700; padding: 0;"
            "}"
            "QToolTip { font-weight: 400; }"
        )
        self._maximize_results_button.setToolTip("Expand results window")
        self._maximize_results_button.clicked.connect(
            self.toggle_results_maximized
        )
        results_header_layout.addWidget(self._maximize_results_button)
        results_header_layout.addStretch(1)

        line_wrap_label = QLabel("Line wrapping")
        line_wrap_label.setObjectName("lineWrapLabel")
        results_header_layout.addWidget(line_wrap_label)

        self._line_wrap_check = VisibleCheckBox()
        self._line_wrap_check.setObjectName("lineWrapCheck")
        self._line_wrap_check.setAccessibleName("Line wrapping")
        self._line_wrap_check.setToolTip(
            "Wrap long result lines to the width of the results window."
        )
        self._line_wrap_check.toggled.connect(self.set_results_line_wrapping)
        results_header_layout.addWidget(self._line_wrap_check)
        results_panel_layout.addWidget(results_header)

        self._results = QPlainTextEdit(self._results_panel)
        self._results.setObjectName("resultsView")
        self._results.setReadOnly(True)
        self._results.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._results.setPlaceholderText(
            "Open a log file to display the analyzed results here."
        )
        self._results.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self._results.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background: {THEME_COLORS['background']};"
            f" color: {THEME_COLORS['body']};"
            " border: none;"
            f" selection-background-color: {THEME_COLORS['selection']};"
            " padding: 8px;"
            "}"
            "QPlainTextEdit QScrollBar:vertical {"
            f" background: {THEME_COLORS['scrollbar_track']};"
            " width: 12px;"
            " margin: 0;"
            "}"
            "QPlainTextEdit QScrollBar:horizontal {"
            f" background: {THEME_COLORS['scrollbar_track']};"
            " height: 12px;"
            " margin: 0;"
            "}"
            "QPlainTextEdit QScrollBar::handle:vertical {"
            f" background: {THEME_COLORS['scrollbar_handle']};"
            " min-height: 28px;"
            " border-radius: 5px;"
            " margin: 2px;"
            "}"
            "QPlainTextEdit QScrollBar::handle:vertical:hover {"
            f" background: {THEME_COLORS['scrollbar_handle_hover']};"
            "}"
            "QPlainTextEdit QScrollBar::handle:horizontal {"
            f" background: {THEME_COLORS['scrollbar_handle']};"
            " min-width: 28px;"
            " border-radius: 5px;"
            " margin: 2px;"
            "}"
            "QPlainTextEdit QScrollBar::handle:horizontal:hover {"
            f" background: {THEME_COLORS['scrollbar_handle_hover']};"
            "}"
            "QPlainTextEdit QScrollBar::add-line:vertical,"
            "QPlainTextEdit QScrollBar::sub-line:vertical,"
            "QPlainTextEdit QScrollBar::add-line:horizontal,"
            "QPlainTextEdit QScrollBar::sub-line:horizontal {"
            " height: 0;"
            " width: 0;"
            "}"
            "QPlainTextEdit QScrollBar::add-page:vertical,"
            "QPlainTextEdit QScrollBar::sub-page:vertical,"
            "QPlainTextEdit QScrollBar::add-page:horizontal,"
            "QPlainTextEdit QScrollBar::sub-page:horizontal {"
            " background: transparent;"
            "}"
        )
        results_panel_layout.addWidget(self._results, 1)
        root_layout.addWidget(self._results_panel, 1)
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

    def _build_filter_group(self) -> QGroupBox:
        group = QGroupBox("Filters")
        group.setObjectName("filterGroup")
        outer_layout = QHBoxLayout(group)
        outer_layout.setContentsMargins(10, 18, 10, 10)
        outer_layout.setSpacing(0)

        self._filter_alignment_container = QWidget(group)
        self._filter_alignment_container.setObjectName(
            "filterAlignmentContainer"
        )
        self._filter_alignment_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout = QVBoxLayout(self._filter_alignment_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        outer_layout.addWidget(
            self._filter_alignment_container,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        outer_layout.addStretch(1)

        top_controls = QWidget(self._filter_alignment_container)
        top_controls.setObjectName("topControlsRow")
        top_layout = QHBoxLayout(top_controls)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self._context_spin = self._make_spin_box(0, 1_000, 3)
        self._context_spin.setObjectName("contextSpin")
        context_label = QLabel("Context around errors")
        context_label.setObjectName("contextLabel")
        top_layout.addWidget(context_label)
        top_layout.addWidget(self._context_spin)
        top_layout.addWidget(self._make_top_separator("topSeparatorContext"))

        self._limit_spin = self._make_spin_box(0, 1_000_000, 0)
        self._limit_spin.setObjectName("limitSpin")
        self._limit_spin.setSpecialValueText("Unlimited")
        limit_label = QLabel("Total errors limit")
        limit_label.setObjectName("limitLabel")
        top_layout.addWidget(limit_label)
        top_layout.addWidget(self._limit_spin)
        top_layout.addWidget(self._make_top_separator("topSeparatorLimit"))

        self._toggle_all_button = UnclippedPushButton("Global toggle all")
        self._toggle_all_button.setObjectName("toggleAllButton")
        self._toggle_all_button.setToolTip(
            "Enable every pattern, or disable every pattern when all are enabled."
        )
        self._toggle_all_button.clicked.connect(self.toggle_all_patterns)
        top_layout.addWidget(self._toggle_all_button)

        self._separate_entries = VisibleCheckBox("Line-separator")
        self._separate_entries.setObjectName("separateEntriesCheck")
        self._separate_entries.setProperty("islandIndicator", True)
        self._separate_entries.setChecked(False)
        self._separate_entries.setToolTip(
            "Draw a horizontal rule between non-contiguous result excerpts."
        )
        top_layout.addStretch(1)
        layout.addWidget(top_controls)

        self._text_groups = QWidget(self._filter_alignment_container)
        self._text_groups.setObjectName("textPatternGroupsRow")
        text_groups_layout = QHBoxLayout(self._text_groups)
        text_groups_layout.setContentsMargins(0, 0, 0, 0)
        text_groups_layout.setSpacing(8)
        text_groups_layout.addWidget(
            self._build_pattern_group(
                "Colon / plain error pairs",
                PAIRED_PATTERN_KEYS,
                object_name="pairedPatternGroup",
                columns=2,
                toggle_object_name="togglePairedButton",
            )
        )
        self._text_pattern_group = self._build_pattern_group(
            "Other errors",
            TEXT_PATTERN_KEYS,
            object_name="textPatternGroup",
            columns=4,
            toggle_object_name="toggleTextButton",
        )
        self._text_pattern_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        text_groups_layout.addWidget(self._text_pattern_group, 1)
        layout.addWidget(self._text_groups)

        self._http_row = QWidget(self._filter_alignment_container)
        self._http_row.setObjectName("httpStatusRow")
        http_layout = QHBoxLayout(self._http_row)
        http_layout.setContentsMargins(0, 0, 0, 0)
        http_layout.setSpacing(8)
        http_layout.addWidget(
            self._build_custom_pattern_group(),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        http_layout.addWidget(
            self._build_regex_pattern_group(),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self._http_status_group = self._build_pattern_group(
            "HTTP codes",
            HTTP_STATUS_PATTERN_KEYS,
            object_name="httpStatusGroup",
            columns=1,
        )
        http_options = QWidget(self._http_row)
        http_options.setObjectName("httpOptionsColumn")
        http_options.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        http_options_layout = QVBoxLayout(http_options)
        http_options_layout.setContentsMargins(0, 0, 0, 0)
        http_options_layout.setSpacing(9)
        self._http_status_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        http_options_layout.addWidget(self._http_status_group)
        http_options_layout.addWidget(
            self._separate_entries,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        http_layout.addWidget(http_options, 1, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._http_row)
        self._filter_alignment_container.setMaximumWidth(
            top_controls.sizeHint().width() + FILTER_ALIGNMENT_EXTRA_WIDTH
        )
        return group

    def _build_custom_pattern_group(self) -> QGroupBox:
        (
            group,
            self._custom_pattern,
            self._add_custom_pattern_button,
            self._custom_pattern_list,
        ) = self._build_list_search_group(
            title="Plain text search",
            group_object_name="customPatternGroup",
            input_object_name="customPattern",
            add_button_object_name="customPatternAddButton",
            list_object_name="customPatternList",
            add_handler=self.add_custom_pattern,
        )
        return group

    def _build_regex_pattern_group(self) -> QGroupBox:
        (
            group,
            self._regex_pattern,
            self._add_regex_pattern_button,
            self._regex_pattern_list,
        ) = self._build_list_search_group(
            title="Regex search",
            group_object_name="regexPatternGroup",
            input_object_name="regexPattern",
            add_button_object_name="regexPatternAddButton",
            list_object_name="regexPatternList",
            add_handler=self.add_regex_pattern,
        )
        return group

    def _build_list_search_group(
        self,
        *,
        title: str,
        group_object_name: str,
        input_object_name: str,
        add_button_object_name: str,
        list_object_name: str,
        add_handler: Callable[[], None],
    ) -> tuple[QGroupBox, QLineEdit, QPushButton, QListWidget]:
        group = QGroupBox(title)
        group.setObjectName(group_object_name)
        group.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(4)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        input_box = QLineEdit()
        input_box.setObjectName(input_object_name)
        input_box.setClearButtonEnabled(True)
        input_box.setPlaceholderText("Enter item")
        input_palette = input_box.palette()
        placeholder_color = input_palette.color(
            QPalette.ColorRole.PlaceholderText
        )
        placeholder_color.setAlpha(90)
        input_palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            placeholder_color,
        )
        input_box.setPalette(input_palette)
        input_box.returnPressed.connect(add_handler)
        entry_row.addWidget(input_box)

        add_button = QPushButton("+add")
        add_button.setObjectName(add_button_object_name)
        add_button.clicked.connect(add_handler)
        entry_row.addWidget(add_button)
        layout.addLayout(entry_row)

        pattern_list = QListWidget()
        pattern_list.setObjectName(list_object_name)
        pattern_list.setSpacing(0)
        pattern_list.setUniformItemSizes(True)
        pattern_list.setStyleSheet(
            "QListWidget::item { margin: 0; padding: 0; }"
        )
        pattern_list.setFixedHeight(64)
        layout.addWidget(pattern_list)
        return group, input_box, add_button, pattern_list

    @staticmethod
    def _make_top_separator(object_name: str) -> QFrame:
        separator = QFrame()
        separator.setObjectName(object_name)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setLineWidth(1)
        separator.setFixedWidth(1)
        separator.setMaximumHeight(24)
        separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']};"
            " border: none;"
            f" color: {THEME_COLORS['ui_border_strong']};"
        )
        return separator

    def _build_pattern_group(
        self,
        title: str,
        pattern_keys: tuple[str, ...],
        *,
        object_name: str,
        columns: int,
        toggle_object_name: str | None = None,
    ) -> QGroupBox:
        group = QGroupBox(title)
        group.setObjectName(object_name)
        group.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        if object_name == "httpStatusGroup":
            group.setMinimumWidth(
                max(130, group.fontMetrics().horizontalAdvance(title) + 32)
            )
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        checkboxes = []
        for index, key in enumerate(pattern_keys):
            checkbox = VisibleCheckBox(self._pattern_control_label(key))
            checkbox.setObjectName(f"pattern_{key}")
            checkbox.setProperty("islandIndicator", True)
            checkbox.setChecked(key in DEFAULT_ENABLED_PATTERNS)
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            self._pattern_checkboxes[key] = checkbox
            checkboxes.append(checkbox)
            layout.addWidget(
                checkbox,
                index // columns,
                index % columns,
                Qt.AlignmentFlag.AlignLeft,
            )

        column_width = max(checkbox.sizeHint().width() for checkbox in checkboxes)
        for column in range(columns):
            layout.setColumnMinimumWidth(column, column_width)
            layout.setColumnStretch(column, 0)

        if toggle_object_name is not None:
            toggle_button = QPushButton("Toggle all")
            toggle_button.setObjectName(toggle_object_name)
            toggle_button.setMaximumWidth(100)
            toggle_button.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            toggle_button.clicked.connect(
                lambda _checked=False, keys=pattern_keys: self.toggle_patterns(keys)
            )
            layout.addWidget(
                toggle_button,
                (len(pattern_keys) + columns - 1) // columns,
                0,
                Qt.AlignmentFlag.AlignLeft,
            )

        return group

    @staticmethod
    def _pattern_control_label(key: str) -> str:
        """Return a concise GUI label without changing result headings."""

        if key == "http_4xx":
            return "4xx"
        if key == "http_5xx":
            return "5xx"
        return PATTERN_PRESETS_BY_KEY[key].label.capitalize()

    @staticmethod
    def _make_spin_box(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin_box = VisibleSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        return spin_box

    def build_config(self) -> LogreaderConfig:
        """Build the shared configuration represented by the controls."""

        return LogreaderConfig(
            context=self._context_spin.value(),
            limit=self._limit_spin.value() or None,
            enabled_patterns=tuple(
                key
                for key in PATTERN_KEYS
                if self._pattern_checkboxes[key].isChecked()
            ),
            custom_patterns=tuple(
                str(
                    self._custom_pattern_list.item(index).data(
                        Qt.ItemDataRole.UserRole
                    )
                )
                for index in range(self._custom_pattern_list.count())
            ),
            regex_patterns=tuple(
                str(
                    self._regex_pattern_list.item(index).data(
                        Qt.ItemDataRole.UserRole
                    )
                )
                for index in range(self._regex_pattern_list.count())
            ),
            separate_entries=self._separate_entries.isChecked(),
        )

    def add_custom_pattern(self) -> None:
        """Commit the current custom-pattern draft to the filter list."""

        self._add_search_list_item(
            self._custom_pattern,
            self._custom_pattern_list,
            "customPatternRemoveButton",
            self.remove_custom_pattern,
        )

    def add_regex_pattern(self) -> None:
        """Commit the current regex draft to the filter list."""

        self._add_search_list_item(
            self._regex_pattern,
            self._regex_pattern_list,
            "regexPatternRemoveButton",
            self.remove_regex_pattern,
        )

    def _add_search_list_item(
        self,
        input_box: QLineEdit,
        pattern_list: QListWidget,
        remove_button_object_name: str,
        remove_handler: Callable[[QListWidgetItem], None],
    ) -> None:
        pattern = input_box.text().strip()
        if not pattern:
            return

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, pattern)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, pattern)
        item.setSizeHint(QSize(0, 18))
        pattern_list.addItem(item)

        item_row = QWidget()
        item_row.setFixedHeight(18)
        item_layout = QHBoxLayout(item_row)
        item_layout.setContentsMargins(4, 0, 2, 0)
        item_layout.setSpacing(4)
        item_label = QLabel(pattern)
        item_label_font = item_label.font()
        item_label_font.setBold(False)
        item_label_font.setWeight(QFont.Weight.Normal)
        item_label.setFont(item_label_font)
        item_layout.addWidget(item_label, 1)

        remove_button = QPushButton("-")
        remove_button.setObjectName(remove_button_object_name)
        remove_button.setAccessibleName(f"Remove {pattern}")
        remove_button.setToolTip(f"Remove {pattern}")
        remove_button.setFixedSize(24, 16)
        remove_button.clicked.connect(
            lambda _checked=False, list_item=item: remove_handler(list_item)
        )
        item_layout.addWidget(remove_button)
        pattern_list.setItemWidget(item, item_row)

        input_box.clear()
        input_box.setFocus()

    def remove_custom_pattern(self, item: QListWidgetItem) -> None:
        """Remove one committed custom pattern from the filter list."""

        self._remove_search_list_item(self._custom_pattern_list, item)

    def remove_regex_pattern(self, item: QListWidgetItem) -> None:
        """Remove one committed regex from the filter list."""

        self._remove_search_list_item(self._regex_pattern_list, item)

    @staticmethod
    def _remove_search_list_item(
        pattern_list: QListWidget,
        item: QListWidgetItem,
    ) -> None:
        row = pattern_list.row(item)
        if row < 0:
            return

        item_widget = pattern_list.itemWidget(item)
        pattern_list.removeItemWidget(item)
        pattern_list.takeItem(row)
        if item_widget is not None:
            item_widget.deleteLater()

    def toggle_all_patterns(self) -> None:
        """Enable all patterns, or disable them when all are already enabled."""

        self.toggle_patterns(PATTERN_KEYS)

    def toggle_results_maximized(self) -> None:
        """Toggle between the normal controls and an expanded results view."""

        self._results_maximized = not self._results_maximized
        controls_visible = not self._results_maximized
        self._controls_container.setVisible(controls_visible)
        self._file_controls.setVisible(controls_visible)
        self._filter_group.setVisible(controls_visible)

        if self._results_maximized:
            self._maximize_results_button.setText("▼")
            self._maximize_results_button.setAccessibleName("Restore layout")
            self._maximize_results_button.setToolTip("Show menu and filters")
        else:
            self._maximize_results_button.setText("▲")
            self._maximize_results_button.setAccessibleName("Maximize results")
            self._maximize_results_button.setToolTip("Expand results window")

    def set_results_line_wrapping(self, enabled: bool) -> None:
        """Enable or disable wrapping of long lines in the results view."""

        line_wrap_mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self._results.setLineWrapMode(line_wrap_mode)

    def toggle_patterns(self, pattern_keys: tuple[str, ...]) -> None:
        """Toggle every checkbox in one pattern category as a unit."""

        enable_all = not all(
            self._pattern_checkboxes[key].isChecked() for key in pattern_keys
        )
        for key in pattern_keys:
            self._pattern_checkboxes[key].setChecked(enable_all)

    def open_file(self) -> None:
        """Prompt for a local log file and stage it for analysis."""

        initial_directory = (
            self._source_path.parent if self._source_path is not None else Path.home()
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

        if self._analysis_busy:
            self._analysis_request_id += 1
            self._finish_analysis_request()

        self._source_path = path
        self._source_lines = loaded.lines
        self._source_encoding = loaded.encoding
        self._path_label.setText(path.name)
        self._path_label.setToolTip(str(path))
        self._analyze_button.setEnabled(True)
        self.setWindowTitle(f"{APP_VERSION} — {path.name}")
        self._results.clear()
        self._results.setPlaceholderText(
            f"{path.name} is loaded. Choose Analyze to display results."
        )
        self.statusBar().showMessage(
            f"{len(loaded.lines):,} lines loaded as {loaded.encoding}  •  "
            "press Analyze to begin"
        )
        return True

    def analyze_current(self) -> None:
        """Analyze the loaded file using the current controls."""

        if self._source_path is None or self._analysis_busy:
            return

        try:
            config = self.build_config()
            patterns = config.search_patterns()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid filters", str(error))
            self.statusBar().showMessage("Analysis could not be completed")
            return

        self._analysis_request_id += 1
        request_id = self._analysis_request_id
        worker = AnalysisWorker(
            request_id,
            self._source_lines,
            patterns,
        )
        worker.signals.completed.connect(self._complete_analysis)
        worker.signals.failed.connect(self._fail_analysis)
        self._analysis_worker = worker
        self._analysis_config = config
        self._analysis_source_path = self._source_path
        self._analysis_pattern_count = len(patterns)
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

        if request_id != self._analysis_request_id:
            return

        config = self._analysis_config
        source_path = self._analysis_source_path
        if config is None or source_path is None:
            self._finish_analysis_request()
            return

        rendering_started = perf_counter()
        render_analysis(
            self._results,
            str(source_path),
            analysis,
            config,
        )
        rendering_seconds = perf_counter() - rendering_started
        prepend_performance_timings(
            self._results,
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
            f"{self._source_encoding or 'unknown encoding'}"
        )
        self.analysis_finished.emit()

    @Slot(int, str)
    def _fail_analysis(self, request_id: int, message: str) -> None:
        """Restore the interface after a worker-side analysis failure."""

        if request_id != self._analysis_request_id:
            return

        self._finish_analysis_request()
        QMessageBox.warning(self, "Invalid filters", message)
        self.statusBar().showMessage("Analysis could not be completed")

    def _set_analysis_busy(self, busy: bool) -> None:
        self._analysis_busy = busy
        if busy:
            self._analysis_busy_visible = False
            self._results.setFocus(Qt.FocusReason.OtherFocusReason)
            self._analyze_button.setEnabled(False)
            self._analyze_button.setText("Analyzing…")
            self._analysis_busy_timer.start()
            return

        self._analysis_busy_timer.stop()
        self._analyze_button.setEnabled(self._source_path is not None)
        self._analyze_button.setText("&Analyze")
        if self._analysis_busy_visible:
            self._analysis_busy_visible = False
            self.unsetCursor()

    @Slot()
    def _show_analysis_busy(self) -> None:
        if not self._analysis_busy:
            return

        self._analysis_busy_visible = True
        self.setCursor(Qt.CursorShape.WaitCursor)
        source_name = (
            self._analysis_source_path.name
            if self._analysis_source_path is not None
            else "log"
        )
        self.statusBar().showMessage(
            f"Analyzing {source_name} with "
            f"{self._analysis_pattern_count} active patterns…"
        )

    def _finish_analysis_request(self) -> None:
        self._analysis_worker = None
        self._analysis_config = None
        self._analysis_source_path = None
        self._analysis_pattern_count = 0
        self._set_analysis_busy(False)


def render_analysis(
    view: QPlainTextEdit,
    source_name: str,
    analysis: AnalysisResult,
    config: LogreaderConfig,
) -> None:
    """Render a structured analysis result into a colored Qt text view."""

    view.setUpdatesEnabled(False)
    try:
        view.clear()
        cursor = QTextCursor(view.document())
        cursor.beginEditBlock()

        _insert(cursor, f"{APP_VERSION}\n", "heading", bold=True)
        _insert(cursor, f"{source_name}\n\n", "muted")
        for key, result in analysis.categories.items():
            label = config.label_for(key)
            _insert(cursor, f"{label:<20}", "body")
            _insert(cursor, f"{result.match_count:>8} matches\n", _count_role(result))

        _insert(
            cursor,
            f"\n{analysis.line_count:,} source lines  •  "
            f"context {config.context}\n",
            "muted",
        )

        for presentation in build_category_presentations(analysis, config.limit):
            _render_category(cursor, presentation, config)

        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def prepend_performance_timings(
    view: QPlainTextEdit,
    analysis_seconds: float,
    rendering_seconds: float,
) -> None:
    """Place diagnostic analysis and rendering durations above the results."""

    view.setUpdatesEnabled(False)
    try:
        cursor = QTextCursor(view.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        _insert(cursor, "Performance timing\n", "heading", bold=True)
        _insert(cursor, f"Analysis time: {analysis_seconds:.3f} s\n", "muted")
        _insert(
            cursor,
            f"Result rendering time: {rendering_seconds:.3f} s\n\n",
            "muted",
        )
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def _render_category(
    cursor: QTextCursor,
    presentation: CategoryPresentation,
    config: LogreaderConfig,
) -> None:
    label = config.label_for(presentation.key)
    _insert(cursor, f"\n{RULE}\n", "muted")
    _insert(cursor, f"{presentation.heading(label)}\n", "heading", bold=True)
    _insert(cursor, f"{RULE}\n", "muted")

    for excerpt_index, excerpt in enumerate(presentation.excerpts):
        for line in excerpt.lines:
            _render_result_line(cursor, line)

        if (
            config.separate_entries
            and excerpt_index < len(presentation.excerpts) - 1
        ):
            _insert(cursor, f"{ENTRY_SEPARATOR}\n", "body")

    limit_message = presentation.limit_message()
    if limit_message is not None:
        _insert(
            cursor,
            f"{limit_message}\n",
            "limit_notice",
            bold=True,
        )


def _render_result_line(
    cursor: QTextCursor,
    line: ResultLine,
) -> None:
    line_number = f"{line.number:<7}-> "
    if not line.is_match:
        _insert(cursor, line_number, "line_number", bold=True)
        _insert(cursor, f"{line.text}\n", "body")
        return

    _insert(cursor, line_number, "match", bold=True)
    position = 0
    for span in line.match_spans:
        _insert(cursor, line.text[position : span.start], "matched_text")
        _insert(cursor, line.text[span.start : span.end], "match", bold=True)
        position = span.end
    _insert(cursor, f"{line.text[position:]}\n", "matched_text")


def _count_role(result: CategoryResult) -> str:
    return "hit_count" if result.match_count else "muted"


def _insert(
    cursor: QTextCursor,
    text: str,
    role: str,
    *,
    bold: bool = False,
) -> None:
    text_format = QTextCharFormat()
    text_format.setForeground(COLORS[role])
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    cursor.insertText(text, text_format)


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
