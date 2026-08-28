"""Minimal PySide6 desktop frontend for Logreader."""

from __future__ import annotations

import re
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
    OPTIONAL_PATTERN_KEYS,
    PATTERN_PRESETS_BY_KEY,
    LogreaderConfig,
)
from .core import AnalysisResult, CategoryResult, ResultLine, analyze_lines


COLORS = {
    "text": QColor("#d8dee9"),
    "muted": QColor("#8b949e"),
    "heading": QColor("#d2a8ff"),
    "red": QColor("#ff7b72"),
    "green": QColor("#7ee787"),
    "blue": QColor("#79c0ff"),
}
RULE = "─" * 72
SEPARATOR = "-------->"


class LogreaderWindow(QMainWindow):
    """Small desktop shell around the shared Logreader engine."""

    def __init__(self) -> None:
        super().__init__()
        self._source_path: Path | None = None
        self._source_lines: tuple[str, ...] = ()
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
            "QPlainTextEdit {"
            " background: #0d1117;"
            " color: #d8dee9;"
            " border: 1px solid #30363d;"
            " selection-background-color: #264f78;"
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
        layout.addWidget(QLabel("ERROR: context"), 0, 0)
        layout.addWidget(self._context_spin, 0, 1)

        self._generic_context_spin = self._make_spin_box(0, 1_000, 0)
        self._generic_context_spin.setObjectName("genericContextSpin")
        layout.addWidget(QLabel("Other context"), 0, 2)
        layout.addWidget(self._generic_context_spin, 0, 3)

        self._limit_spin = self._make_spin_box(0, 1_000_000, 0)
        self._limit_spin.setObjectName("limitSpin")
        self._limit_spin.setSpecialValueText("Unlimited")
        layout.addWidget(QLabel("Per-pattern limit"), 0, 4)
        layout.addWidget(self._limit_spin, 0, 5)

        always_label = QLabel("ERROR: and ERROR are always enabled")
        always_label.setStyleSheet("color: #6e7781;")
        layout.addWidget(always_label, 0, 6, 1, 2)

        pattern_layout = QGridLayout()
        for index, key in enumerate(OPTIONAL_PATTERN_KEYS):
            checkbox = QCheckBox(PATTERN_PRESETS_BY_KEY[key].label)
            checkbox.setObjectName(f"pattern_{key}")
            checkbox.setChecked(key in DEFAULT_ENABLED_PATTERNS)
            self._pattern_checkboxes[key] = checkbox
            pattern_layout.addWidget(checkbox, index // 4, index % 4)
        layout.addLayout(pattern_layout, 1, 0, 1, 8)

        self._custom_pattern = QLineEdit()
        self._custom_pattern.setObjectName("customPattern")
        self._custom_pattern.setClearButtonEnabled(True)
        self._custom_pattern.setPlaceholderText(
            "Optional case-insensitive literal pattern"
        )
        self._custom_pattern.returnPressed.connect(self.analyze_current)
        layout.addWidget(QLabel("Custom pattern"), 2, 0)
        layout.addWidget(self._custom_pattern, 2, 1, 1, 7)
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
            generic_context=self._generic_context_spin.value(),
            limit=self._limit_spin.value() or None,
            enabled_patterns=tuple(
                key
                for key in OPTIONAL_PATTERN_KEYS
                if self._pattern_checkboxes[key].isChecked()
            ),
            custom_patterns=(custom_pattern,) if custom_pattern else (),
        )

    def open_file(self) -> None:
        """Prompt for a local log file and analyze it."""

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
        """Load and analyze a file, returning whether it could be read."""

        path = Path(source_path)
        try:
            source_lines = tuple(path.read_text().splitlines())
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(
                self,
                "Unable to open log",
                f"Could not read:\n{path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Unable to read {path.name}")
            return False

        self._source_path = path
        self._source_lines = source_lines
        self._path_label.setText(path.name)
        self._path_label.setToolTip(str(path))
        self._analyze_button.setEnabled(True)
        self.setWindowTitle(f"{APP_VERSION} — {path.name}")
        self.analyze_current()
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
            f"{len(analysis.categories)} active patterns"
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
            _insert(cursor, f"{label:<20}", "text")
            _insert(cursor, f"{result.match_count:>8} matches\n", _count_color(result))

        _insert(
            cursor,
            f"\n{analysis.line_count:,} source lines  •  "
            f"ERROR: context {config.context}  •  "
            f"other context {config.generic_context}\n",
            "muted",
        )

        for key, result in analysis.categories.items():
            _render_category(cursor, key, result, config)

        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        view.setTextCursor(cursor)
    finally:
        view.setUpdatesEnabled(True)


def _render_category(
    cursor: QTextCursor,
    key: str,
    result: CategoryResult,
    config: LogreaderConfig,
) -> None:
    label = config.label_for(key)
    _insert(cursor, f"\n{RULE}\n", "muted")
    _insert(cursor, f"{label} — {result.match_count} matches\n", "heading", bold=True)
    _insert(cursor, f"{RULE}\n", "muted")

    if not result.excerpts:
        _insert(cursor, "No matches.\n", "muted")
        return

    matches_rendered = 0
    stopped_at_limit = False
    for excerpt_index, excerpt in enumerate(result.excerpts):
        for line in excerpt.lines:
            if line.is_match:
                if config.limit is not None and matches_rendered >= config.limit:
                    stopped_at_limit = True
                    break
                matches_rendered += 1
            _render_result_line(cursor, line, result.pattern.needle)

        if stopped_at_limit:
            break
        if config.limit is not None and matches_rendered >= config.limit:
            break
        if (
            config.show_separator_for(key)
            and excerpt_index < len(result.excerpts) - 1
        ):
            _insert(cursor, f"{SEPARATOR}\n", "muted")

    if config.limit is not None and result.match_count > config.limit:
        _insert(
            cursor,
            f"Showing {config.limit} of {result.match_count} matches.\n",
            "blue",
            bold=True,
        )


def _render_result_line(
    cursor: QTextCursor,
    line: ResultLine,
    needle: str,
) -> None:
    line_number = f"{line.number:<7}-> "
    if not line.is_match:
        _insert(cursor, line_number, "blue", bold=True)
        _insert(cursor, f"{line.text}\n", "text")
        return

    _insert(cursor, line_number, "red", bold=True)
    match = re.search(re.escape(needle), line.text, re.IGNORECASE)
    if match is None:
        _insert(cursor, f"{line.text}\n", "text")
        return

    _insert(cursor, line.text[: match.start()], "green")
    _insert(cursor, line.text[match.start() : match.end()], "red", bold=True)
    _insert(cursor, f"{line.text[match.end() :]}\n", "green")


def _count_color(result: CategoryResult) -> str:
    return "red" if result.match_count else "muted"


def _insert(
    cursor: QTextCursor,
    text: str,
    color: str,
    *,
    bold: bool = False,
) -> None:
    text_format = QTextCharFormat()
    text_format.setForeground(COLORS[color])
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
