"""Minimal PySide6 desktop frontend for Logreader."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
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
from .core import AnalysisResult, CategoryResult, ResultLine, analyze_lines
from .file_loader import LogDecodeError, load_log
from .presentation import CategoryPresentation, build_category_presentations
from .theme import THEME_COLORS


COLORS = {role: QColor(value) for role, value in THEME_COLORS.items()}
RULE = "─" * 72
ENTRY_SEPARATOR = RULE


class LogreaderWindow(QMainWindow):
    """Small desktop shell around the shared Logreader engine."""

    def __init__(self) -> None:
        super().__init__()
        self._source_path: Path | None = None
        self._source_lines: tuple[str, ...] = ()
        self._source_encoding: str | None = None
        self._pattern_checkboxes: dict[str, QCheckBox] = {}

        self.setWindowTitle(APP_VERSION)
        self.resize(1080, 760)
        self.setMinimumSize(820, 560)
        self._build_interface()
        self.statusBar().showMessage("Ready — open a log file to begin")

    def _build_interface(self) -> None:
        central_widget = QWidget(self)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(12, 12, 12, 10)
        root_layout.setSpacing(10)

        file_row = QHBoxLayout()
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
        root_layout.addLayout(file_row)

        root_layout.addWidget(self._build_filter_group())

        self._results = QPlainTextEdit()
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
            f" border: 1px solid {THEME_COLORS['border']};"
            f" selection-background-color: {THEME_COLORS['selection']};"
            " padding: 8px;"
            "}"
        )
        root_layout.addWidget(self._results, 1)
        self.setCentralWidget(central_widget)

    def _build_filter_group(self) -> QGroupBox:
        group = QGroupBox("Filters")
        layout = QGridLayout(group)
        layout.setColumnStretch(7, 1)

        self._context_spin = self._make_spin_box(0, 1_000, 3)
        self._context_spin.setObjectName("contextSpin")
        context_label = QLabel("Context around entries")
        context_label.setObjectName("contextLabel")
        layout.addWidget(context_label, 0, 0)
        layout.addWidget(self._context_spin, 0, 1)

        self._limit_spin = self._make_spin_box(0, 1_000_000, 0)
        self._limit_spin.setObjectName("limitSpin")
        self._limit_spin.setSpecialValueText("Unlimited")
        limit_label = QLabel("Number of entries - limit")
        limit_label.setObjectName("limitLabel")
        layout.addWidget(limit_label, 0, 2)
        layout.addWidget(self._limit_spin, 0, 3)

        self._toggle_all_button = QPushButton("Global toggle all")
        self._toggle_all_button.setObjectName("toggleAllButton")
        self._toggle_all_button.setToolTip(
            "Enable every pattern, or disable every pattern when all are enabled."
        )
        self._toggle_all_button.clicked.connect(self.toggle_all_patterns)
        layout.addWidget(self._toggle_all_button, 0, 4)

        layout.addWidget(
            self._build_pattern_group(
                "Colon and plain counterparts",
                PAIRED_PATTERN_KEYS,
                object_name="pairedPatternGroup",
                columns=2,
                toggle_object_name="togglePairedButton",
            ),
            1,
            0,
            1,
            8,
        )
        layout.addWidget(
            self._build_pattern_group(
                "Other text errors",
                TEXT_PATTERN_KEYS,
                object_name="textPatternGroup",
                columns=4,
                toggle_object_name="toggleTextButton",
            ),
            2,
            0,
            1,
            8,
        )
        layout.addWidget(
            self._build_pattern_group(
                "HTTP status codes",
                HTTP_STATUS_PATTERN_KEYS,
                object_name="httpStatusGroup",
                columns=2,
            ),
            3,
            0,
            1,
            8,
        )

        self._custom_pattern = QLineEdit()
        self._custom_pattern.setObjectName("customPattern")
        self._custom_pattern.setClearButtonEnabled(True)
        self._custom_pattern.setPlaceholderText(
            "Optional case-insensitive literal pattern"
        )
        layout.addWidget(QLabel("Custom pattern"), 4, 0)
        layout.addWidget(self._custom_pattern, 4, 1, 1, 7)

        self._separate_entries = QCheckBox("Separation of entries")
        self._separate_entries.setObjectName("separateEntriesCheck")
        self._separate_entries.setChecked(False)
        self._separate_entries.setToolTip(
            "Draw a horizontal rule between non-contiguous result excerpts."
        )
        layout.addWidget(self._separate_entries, 5, 0, 1, 8)
        return group

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
        layout = QGridLayout(group)

        for index, key in enumerate(pattern_keys):
            checkbox = QCheckBox(PATTERN_PRESETS_BY_KEY[key].label)
            checkbox.setObjectName(f"pattern_{key}")
            checkbox.setChecked(key in DEFAULT_ENABLED_PATTERNS)
            self._pattern_checkboxes[key] = checkbox
            layout.addWidget(checkbox, index // columns, index % columns)

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
            )

        return group

    @staticmethod
    def _make_spin_box(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin_box = QSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        return spin_box

    def build_config(self) -> LogreaderConfig:
        """Build the shared configuration represented by the controls."""

        custom_pattern = self._custom_pattern.text().strip()
        return LogreaderConfig(
            context=self._context_spin.value(),
            limit=self._limit_spin.value() or None,
            enabled_patterns=tuple(
                key
                for key in PATTERN_KEYS
                if self._pattern_checkboxes[key].isChecked()
            ),
            custom_patterns=(custom_pattern,) if custom_pattern else (),
            separate_entries=self._separate_entries.isChecked(),
        )

    def toggle_all_patterns(self) -> None:
        """Enable all patterns, or disable them when all are already enabled."""

        self.toggle_patterns(PATTERN_KEYS)

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

        if self._source_path is None:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            config = self.build_config()
            analysis = analyze_lines(self._source_lines, config.search_patterns())
            render_analysis(
                self._results,
                str(self._source_path),
                analysis,
                config,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invalid filters", str(error))
            self.statusBar().showMessage("Analysis could not be completed")
            return
        finally:
            QApplication.restoreOverrideCursor()

        match_count = sum(
            result.match_count for result in analysis.categories.values()
        )
        self.statusBar().showMessage(
            f"{analysis.line_count:,} lines  •  {match_count:,} matches  •  "
            f"{len(analysis.categories)} active patterns  •  "
            f"{self._source_encoding or 'unknown encoding'}"
        )


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
            _insert(cursor, f"{ENTRY_SEPARATOR}\n", "muted")

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
