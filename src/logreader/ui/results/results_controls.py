"""Shared controls and source-view actions for the results panel."""

from __future__ import annotations

from array import array
from typing import Callable, Iterator
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, QSize, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QStackedLayout, QVBoxLayout, QWidget

from ..bookmarks import ResultsBookmarks
from ..widgets.search_widgets import SearchMatchHighlighter, SearchMarkerScrollBar
from .results_style import _results_editor_style_sheet
from .results_model import ResultLocation, SourceLocation
from ..source_view import SourceView
from ..widgets.input_menus import InputContextMenu, ScrollbarContextMenu
from ..theme import THEME_COLORS, configure_action_button, configure_clear_button, vertical_resize_icon


CheckBoxFactory = Callable[[], QCheckBox]
SpinBoxFactory = Callable[[], QSpinBox]


class ResultsControls(QWidget):
    """Results search, bookmarks, wrapping and source controls."""

    maximized_changed = Signal(bool)
    rendering_completed = Signal(int, float)
    rendering_failed = Signal(int, str)
    bookmarks_cleared = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        checkbox_factory: CheckBoxFactory = QCheckBox,
        spinbox_factory: SpinBoxFactory = QSpinBox,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultsPanel")
        self._maximized = False
        self._renderer = None
        self._source_active = False
        self._rendering_paused = False
        self._results_query = ""
        self._snapshot_id = uuid4().hex
        self._return_position = None
        self._search_matches = None
        self._current_search_match: int | None = None
        self._searched_query: str | None = None
        self._search_from_viewport = True
        self._search_generation = 0
        self._search_work: Iterator[tuple[int, int, int] | None] | None = None
        self._pending_matches = None
        self._pending_blocks = array("I")
        self._pending_navigation: bool | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search_next_batch)

        panel_layout = QVBoxLayout(self)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("resultsHeader")
        header.setMinimumHeight(36)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 5, 8, 5)
        header_layout.setSpacing(8)

        self._expand_icon = vertical_resize_icon()
        self._contract_icon = vertical_resize_icon(contract=True)
        self._maximize_button = QPushButton()
        configure_action_button(self._maximize_button)
        self._maximize_button.setIcon(self._expand_icon)
        self._maximize_button.setIconSize(QSize(18, 18))
        self._maximize_button.setObjectName("maximizeResultsButton")
        self._maximize_button.setAccessibleName("Maximize results")
        self._maximize_button.setFixedSize(38, 28)
        self._maximize_button.setStyleSheet(
            "QPushButton#maximizeResultsButton {"
            " padding: 0;"
            "}"
            "QToolTip { font-weight: 400; }"
        )
        self._maximize_button.setToolTip("Expand results window")
        self._maximize_button.clicked.connect(self.toggle_maximized)
        header_layout.addWidget(self._maximize_button)
        self._source_button = QPushButton("Go to source")
        self._source_button.setObjectName("sourceToggleButton")
        self._source_button.setToolTip("Open the original file")
        configure_action_button(self._source_button)
        self._source_button.clicked.connect(self.toggle_source)
        header_layout.addWidget(self._source_button)
        header_layout.addStretch(1)

        self._search_count_label = QLabel()
        self._search_count_label.setObjectName("resultsSearchCount")
        self._search_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._search_count_label.setStyleSheet(
            f"color: {THEME_COLORS['ui_muted']};"
        )
        self._search_count_label.setMinimumWidth(84)
        count_size_policy = self._search_count_label.sizePolicy()
        count_size_policy.setRetainSizeWhenHidden(True)
        self._search_count_label.setSizePolicy(count_size_policy)
        self._search_count_label.hide()
        self._source_search_count = QLabel()
        self._source_search_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._source_search_count.setMinimumWidth(84)
        self._count_stack = QStackedWidget()
        self._count_stack.setObjectName("searchCountStack")
        self._count_stack.addWidget(self._search_count_label)
        self._count_stack.addWidget(self._source_search_count)
        self._search_count_label.hide()
        header_layout.addWidget(self._count_stack)

        search_controls = QWidget(header)
        search_controls.setObjectName("resultsSearchControls")
        search_controls_layout = QHBoxLayout(search_controls)
        search_controls_layout.setContentsMargins(0, 0, 0, 0)
        search_controls_layout.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("resultsSearch")
        InputContextMenu(self._search_input, undo=True)
        self._search_input.setAccessibleName("Search results")
        self._search_input.setPlaceholderText("Press enter to search...")
        configure_clear_button(self._search_input)
        self._search_input.setFixedWidth(220)
        self._search_input.setStyleSheet(
            "QLineEdit#resultsSearch {"
            " border-right: none;"
            " border-top-right-radius: 0;"
            " border-bottom-right-radius: 0;"
            "}"
        )
        self._search_input.textChanged.connect(self._invalidate_search_results)
        self._search_input.returnPressed.connect(self.search_results)
        search_controls_layout.addWidget(self._search_input)

        search_button_separator = QFrame(search_controls)
        search_button_separator.setObjectName("resultsSearchButtonSeparator")
        search_button_separator.setFixedSize(1, 28)
        search_button_separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']};"
            " border: none;"
        )
        search_controls_layout.addWidget(search_button_separator)

        self._search_navigation = spinbox_factory()
        self._search_navigation.setObjectName("resultsSearchNavigation")
        self._search_navigation.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self._search_navigation.setAccessibleName("Navigate search results")
        self._search_navigation.setRange(-1, 1)
        self._search_navigation.setValue(0)
        self._search_navigation.setFixedSize(22, 28)
        self._search_navigation.setStyleSheet(
            "QSpinBox#resultsSearchNavigation {"
            " border-left: none;"
            " border-top-left-radius: 0;"
            " border-bottom-left-radius: 0;"
            " padding: 0;"
            "}"
        )
        self._search_navigation.lineEdit().hide()
        self._search_navigation.valueChanged.connect(
            self._navigate_from_search_arrows
        )
        search_controls_layout.addWidget(self._search_navigation)
        header_layout.addWidget(search_controls)

        search_separator = QFrame()
        search_separator.setObjectName("resultsSearchSeparator")
        search_separator.setFrameShape(QFrame.Shape.VLine)
        search_separator.setFrameShadow(QFrame.Shadow.Plain)
        search_separator.setFixedWidth(1)
        search_separator.setMaximumHeight(22)
        search_separator.setStyleSheet(
            f"background-color: {THEME_COLORS['ui_border_strong']};"
            " border: none;"
        )
        header_layout.addWidget(search_separator)

        line_wrap_label = QLabel("Line wrapping")
        line_wrap_label.setObjectName("lineWrapLabel")
        header_layout.addWidget(line_wrap_label)

        self._line_wrap_check = checkbox_factory()
        self._line_wrap_check.setObjectName("lineWrapCheck")
        self._line_wrap_check.setAccessibleName("Line wrapping")
        self._line_wrap_check.setToolTip(
            "Enable/disable line-wrapping"
        )
        self._line_wrap_check.toggled.connect(self.set_line_wrapping)
        header_layout.addWidget(self._line_wrap_check)
        panel_layout.addWidget(header)

        self._editor = QPlainTextEdit(self)
        self._source_map = None
        self._editor.setObjectName("resultsView")
        self._editor.setReadOnly(True)
        # Rendering is programmatic; retaining undo commands only wastes memory.
        self._editor.setUndoRedoEnabled(False)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self._editor.setStyleSheet(_results_editor_style_sheet())
        self._search_marker_scrollbar = SearchMarkerScrollBar(
            Qt.Orientation.Vertical,
            self._editor,
        )
        self._editor.setVerticalScrollBar(self._search_marker_scrollbar)
        for scrollbar in (
            self._search_marker_scrollbar,
            self._editor.horizontalScrollBar(),
        ):
            ScrollbarContextMenu(scrollbar)
            # User actions re-anchor navigation; ordinary value changes from
            # revealing a match or laying out the document must not do so.
            scrollbar.sliderPressed.connect(self._use_viewport_search_anchor)
            scrollbar.actionTriggered.connect(self._use_viewport_search_anchor)
        self._editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._editor.customContextMenuRequested.connect(self._results_context_menu)
        self.source_view = SourceView(
            self, highlighter_factory=SearchMatchHighlighter,
            scrollbar_factory=SearchMarkerScrollBar, editor_style=_results_editor_style_sheet(),
        )
        self.source_view.search_status_changed.connect(self._source_search_count.setText)
        self._view_stack = QStackedLayout()
        self._view_stack.addWidget(self._editor)
        self._view_stack.addWidget(self.source_view)
        panel_layout.addLayout(self._view_stack, 1)
        self.bookmarks = ResultsBookmarks(self)
        panel_layout.insertWidget(1, self.bookmarks.bar)
        source_editor = self.source_view.editor
        source_editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        source_editor.customContextMenuRequested.connect(self._source_context_menu)
        source_editor.gutter.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        source_editor.gutter.customContextMenuRequested.connect(
            lambda point: self._source_context_menu(
                source_editor.viewport().mapFromGlobal(source_editor.gutter.mapToGlobal(point))
            )
        )

    @property
    def source_active(self) -> bool:
        return self._source_active

    def set_source(
        self, lines: tuple[str, ...], total_line_count: int, *, snapshot_id: str | None = None,
    ) -> None:
        snapshot_id = snapshot_id if snapshot_id is not None else uuid4().hex
        if self._snapshot_id != snapshot_id:
            self.reset_for_loaded_file("")
        self._snapshot_id = snapshot_id
        self.source_view.set_source(lines, total_line_count)
        if self._source_active:
            self.source_view.ensure_page()
        self.bookmarks.refresh()

    def toggle_source(self) -> None:
        self.set_source_active(not self._source_active)


    def source_line_at(self, point) -> int | None:
        location = self.result_location_at(point)
        return location.source.line if location is not None else None


    def _results_context_menu(self, point) -> None:
        location = self.result_location_at(point)
        self._exec_line_context_menu(self._editor, point, location, show_source=True)

    def _exec_line_context_menu(self, editor, point, location, *, show_source=False) -> None:
        source = location.source if isinstance(location, ResultLocation) else location
        menu = editor.createStandardContextMenu()
        for action in menu.actions():
            if action.isSeparator():
                menu.removeAction(action)
        editor.set_context_target(editor.cursorForPosition(point).block() if source else None)
        try:
            if show_source:
                menu.addSeparator()
                action = menu.addAction("Show in source")
                action.setEnabled(source is not None)
                if source is not None:
                    action.triggered.connect(lambda: self.show_source_line(source.line)
                                             if source.snapshot_id == self._snapshot_id else None)
            if location is not None:
                menu.addSeparator()
                self.bookmarks.add_menu_actions(menu, location)
            menu.exec(editor.viewport().mapToGlobal(point))
        finally:
            editor.set_context_target(None)
            menu.deleteLater()

    def source_location_at(self, point) -> SourceLocation | None:
        editor = self.source_view.editor
        if not self.source_view.lines:
            return None
        block = editor.cursorForPosition(point).block()
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        if not rect.top() <= point.y() < rect.bottom():
            return None
        number = editor.source_number(block.blockNumber())
        if not (self.source_view.first_line + self.source_view.page_start <= number <
                self.source_view.first_line + self.source_view.page_end):
            return None
        return SourceLocation(self._snapshot_id, number)

    def _source_context_menu(self, point) -> None:
        location = self.source_location_at(point)
        self._exec_line_context_menu(self.source_view.editor, point, location)

    @property
    def editor(self) -> QPlainTextEdit:
        """Return the read-only editor displaying formatted results."""

        return self._editor

    @property
    def is_maximized(self) -> bool:
        return self._maximized


    def focus_editor(self) -> None:
        self._search_input.deselect()
        self._search_input.clearFocus()
        (self.source_view.editor if self._source_active else self._editor).setFocus()

    @Slot()
    def toggle_maximized(self) -> None:
        self.set_maximized(not self._maximized)

    def set_maximized(self, maximized: bool) -> None:
        """Update the results expansion state and notify the window shell."""

        if maximized == self._maximized:
            return

        self._maximized = maximized
        if maximized:
            self._maximize_button.setIcon(self._contract_icon)
            self._maximize_button.setAccessibleName("Restore layout")
            self._maximize_button.setToolTip("Show menu and filters")
        else:
            self._maximize_button.setIcon(self._expand_icon)
            self._maximize_button.setAccessibleName("Maximize results")
            self._maximize_button.setToolTip("Expand results window")
        self.maximized_changed.emit(maximized)


    @Slot()
    def _use_viewport_search_anchor(self) -> None:
        """Start the next navigation from the top visible text line."""

        self._search_from_viewport = True


    @property
    def is_searching(self) -> bool:
        return self._search_work is not None


    @Slot()
    def _search_next_batch(self) -> None:
        self._advance_search(self._search_generation)


    @Slot()
    def find_next(self) -> None:
        """Move to the next result-search match, wrapping at the end."""

        if self._source_active:
            self.source_view.navigate(True)
        else:
            self._navigate_search(forward=True)

    @Slot()
    def find_previous(self) -> None:
        """Move to the previous result-search match, wrapping at the start."""

        if self._source_active:
            self.source_view.navigate(False)
        else:
            self._navigate_search(forward=False)


    @Slot(int)
    def _navigate_from_search_arrows(self, value: int) -> None:
        if value > 0:
            self.find_previous()
        elif value < 0:
            self.find_next()

        blocker = QSignalBlocker(self._search_navigation)
        self._search_navigation.setValue(0)
        del blocker
