"""Paged plain source display with independent snapshot-wide search state."""

from array import array
from bisect import bisect_left

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QFontMetricsF, QIcon, QPalette, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit,
    QStyle, QStyleOptionButton, QStylePainter, QToolTip, QVBoxLayout, QWidget,
)

from .search_storage import SearchMatches
from .source_search import SourceMatches, iter_source_matches
from .theme import THEME_COLORS, configure_action_button, page_navigation_icon
from .line_number_editor import LineNumberEditor


SOURCE_PAGE_LINES = 10_000
SOURCE_PAGE_CHARACTERS = 2560 * 1024
SOURCE_BATCH_MS = 4


class SegmentedButton(QPushButton):
    """Centre visible label glyphs and icons together within a native button."""

    def __init__(self, text: str, partner: QPushButton | None = None) -> None:
        super().__init__(text)
        self._partner = partner

    def sizeHint(self):  # noqa: N802
        size = super().sizeHint()
        if self._partner is not None:
            size.setWidth(self._partner.sizeHint().width())
        return size

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        # Preserve native/stylesheet backgrounds, borders and focus feedback.
        background = QStyleOptionButton(option)
        background.text = ""
        background.icon = QIcon()
        painter.drawControl(QStyle.ControlElement.CE_PushButton, background)

        content = QRectF(self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self,
        ))
        painter.setFont(self.font())
        metrics = QFontMetricsF(self.font())
        glyphs = metrics.tightBoundingRect(self.text())
        text_width = metrics.horizontalAdvance(self.text())
        has_icon = not self.icon().isNull()
        icon_width = self.iconSize().width() if has_icon else 0
        gap = 4 if has_icon else 0
        left = content.center().x() - (text_width + icon_width + gap) / 2
        forward = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        text_x = left if forward else left + icon_width + gap
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        painter.setPen(option.palette.color(group, QPalette.ColorRole.ButtonText))
        painter.drawText(QPointF(text_x, content.center().y() - glyphs.center().y()), self.text())
        if has_icon:
            icon_x = left + text_width + gap if forward else left
            pixmap = self.icon().pixmap(
                self.iconSize(), self.devicePixelRatioF(),
                QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
            )
            painter.drawPixmap(
                QPointF(icon_x, content.center().y() - self.iconSize().height() / 2), pixmap,
            )


class SourceEditor(LineNumberEditor):
    """Original line numbers live in a gutter, not in selected/copied text."""

    def __init__(self, parent=None) -> None:
        self.first_source_line = 1
        super().__init__(parent)

    def source_number(self, block: int) -> int:
        return self.first_source_line + block

    def largest_source_number(self) -> int:
        return self.first_source_line + self.blockCount() - 1


class SourceView(QWidget):
    """Borrow source strings and materialize only the active page in Qt.

    Paging never silently reads a newer disk snapshot. A single unusually long
    source line is kept intact even if it exceeds the normal page character cap.
    """

    search_status_changed = Signal(str)

    def __init__(self, parent, *, highlighter_factory, scrollbar_factory, editor_style):
        super().__init__(parent)
        self.lines: tuple[str, ...] = ()
        self.total_line_count = 0
        self.page_start = self.page_end = 0
        self.target_line: int | None = None
        self.bookmarked_lines: set[int] = set()
        self.query = ""
        self.searched_query: str | None = None
        self.matches = SourceMatches()
        self.current_match: int | None = None
        self.search_status = ""
        self._search_work = None
        self._pending = SourceMatches()
        self._pending_navigation = None
        self._page_work = None
        self._materialized = False
        self._from_viewport = True
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._advance_search)
        self._page_timer = QTimer(self)
        self._page_timer.setSingleShot(True)
        self._page_timer.timeout.connect(self._advance_page_highlights)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controls_bar = QWidget(self)
        controls_bar.setObjectName("sourceNavigationHeader")
        controls_bar.setStyleSheet(
            f"QWidget#sourceNavigationHeader {{ background: {THEME_COLORS['background']}; }}"
        )
        controls = QHBoxLayout(controls_bar)
        controls.setContentsMargins(4, 4, 4, 2)
        self.first_button = SegmentedButton("First")
        self.previous_button = SegmentedButton("Previous")
        self.next_button = SegmentedButton("Next", self.previous_button)
        self.last_button = SegmentedButton("Last", self.first_button)
        self.page_navigation = QFrame()
        self.page_navigation.setObjectName("sourcePageNavigation")
        self.page_navigation.setAccessibleName("Source page navigation")
        segmented_style = (
            "QFrame#sourcePageNavigation, QFrame#sourceLineNavigation {"
            f" background: {THEME_COLORS['background']};"
            f" border: 1px solid {THEME_COLORS['ui_border_strong']}; border-radius: 4px; }}"
            "QPushButton, QLineEdit { border: 1px solid transparent; border-radius: 0;"
            " padding: 1px 3px; margin: 0;"
            f" background: {THEME_COLORS['background']}; color: {THEME_COLORS['ui_text']}; }}"
            "QPushButton#sourceFirstPage, QLineEdit#sourceGoToLine {"
            " border-top-left-radius: 3px; border-bottom-left-radius: 3px; }"
            "QPushButton#sourceLastPage, QPushButton#sourceGoToLineButton {"
            " border-top-right-radius: 3px; border-bottom-right-radius: 3px; }"
            "QPushButton#sourceFirstPage, QPushButton#sourceLastPage {"
            " padding-left: 6px; padding-right: 6px; }"
            f"QLineEdit {{ padding-left: 6px; placeholder-text-color: {THEME_COLORS['ui_muted']}; }}"
            f"QPushButton:hover {{ background: {THEME_COLORS['ui_button_hover']}; }}"
            f"QPushButton:focus, QLineEdit:focus {{ border-color: {THEME_COLORS['ui_accent']}; }}"
            f"QPushButton:pressed {{ background: {THEME_COLORS['ui_button_pressed']}; }}"
            f"QPushButton:disabled, QLineEdit:disabled {{ background: {THEME_COLORS['background']}; border-color: transparent;"
            f" color: {THEME_COLORS['ui_disabled_text']}; }}"
        )
        self.page_navigation.setStyleSheet(segmented_style)
        navigation_layout = QHBoxLayout(self.page_navigation)
        navigation_layout.setContentsMargins(1, 1, 1, 1)
        navigation_layout.setSpacing(0)
        for index, (button, name, forward, boundary) in enumerate((
            (self.first_button, "First", False, True),
            (self.previous_button, "Previous", False, False),
            (self.next_button, "Next", True, False),
            (self.last_button, "Last", True, True),
        )):
            if index:
                separator = QFrame()
                separator.setObjectName(f"sourcePageDivider{index}")
                separator.setFixedWidth(1)
                separator.setStyleSheet(
                    f"background: {THEME_COLORS['ui_border_strong']}; border: none;"
                )
                navigation_layout.addWidget(separator)
            button.setObjectName(f"source{name}Page")
            button.setAccessibleName(f"{name} source page")
            button.setIcon(page_navigation_icon(forward=forward, boundary=boundary))
            button.setIconSize(QSize(16, 16))
            if forward:
                button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            configure_action_button(button)
            navigation_layout.addWidget(button)
        self.goto_input = QLineEdit()
        self.goto_input.setObjectName("sourceGoToLine")
        self.goto_input.setAccessibleName("Original source line number")
        self.goto_input.setPlaceholderText("Line number")
        self.goto_input.setMaximumWidth(125)
        self.goto_button = SegmentedButton("Go to line")
        self.goto_button.setObjectName("sourceGoToLineButton")
        configure_action_button(self.goto_button)
        self.line_navigation = QFrame()
        self.line_navigation.setObjectName("sourceLineNavigation")
        self.line_navigation.setAccessibleName("Go to original source line")
        self.line_navigation.setStyleSheet(segmented_style)
        line_layout = QHBoxLayout(self.line_navigation)
        line_layout.setContentsMargins(1, 1, 1, 1)
        line_layout.setSpacing(0)
        line_layout.addWidget(self.goto_input)
        line_separator = QFrame()
        line_separator.setObjectName("sourceLineDivider")
        line_separator.setFixedWidth(1)
        line_separator.setStyleSheet(
            f"background: {THEME_COLORS['ui_border_strong']}; border: none;"
        )
        line_layout.addWidget(line_separator)
        line_layout.addWidget(self.goto_button)
        self.first_button.clicked.connect(self.first_page)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.last_button.clicked.connect(self.last_page)
        self.goto_button.clicked.connect(self.go_to_input)
        self.goto_input.returnPressed.connect(self.go_to_input)
        controls.addWidget(self.page_navigation)
        self.range_label = QLabel()
        self.range_label.setObjectName("sourceRange")
        self.range_label.setTextFormat(Qt.TextFormat.PlainText)
        self.range_label.setContentsMargins(8, 0, 0, 0)
        self.range_label.setStyleSheet(f"color: {THEME_COLORS['ui_muted']};")
        controls.addWidget(self.range_label)
        controls.addStretch(1)
        controls.addWidget(self.line_navigation)
        layout.addWidget(controls_bar)
        self.editor = SourceEditor(self)
        self.editor.setObjectName("sourceView")
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setStyleSheet(
            editor_style + "QPlainTextEdit#sourceView { color: #ffffff; padding-top: 0; }"
        )
        self.marker = scrollbar_factory(Qt.Orientation.Vertical, self.editor)
        self.editor.setVerticalScrollBar(self.marker)
        for scrollbar in (self.marker, self.editor.horizontalScrollBar()):
            scrollbar.sliderPressed.connect(self._use_viewport_anchor)
            scrollbar.actionTriggered.connect(self._use_viewport_anchor)
        self.highlighter = highlighter_factory(self.editor)
        layout.addWidget(self.editor, 1)
        self.reset()

    @property
    def first_line(self) -> int:
        return self.total_line_count - len(self.lines) + 1

    @property
    def is_searching(self) -> bool:
        return self._search_work is not None

    def _status(self, text: str) -> None:
        self.search_status = text
        self.search_status_changed.emit(text)

    def reset(self, message="Source is not loaded yet.") -> None:
        self.cancel_search()
        self.bookmarked_lines.clear()
        self.lines = ()
        self.total_line_count = 0
        self.page_start = self.page_end = 0
        self.target_line = None
        self._materialized = False
        self.query = ""
        self.goto_input.clear()
        self.goto_input.setToolTip("Enter a line-number to jump to")
        self.editor.clear()
        self.editor.setExtraSelections([])
        self.editor.setPlaceholderText(message)
        self.range_label.clear()
        self.first_button.setEnabled(False)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.last_button.setEnabled(False)

    def set_source(self, lines: tuple[str, ...], total_line_count: int) -> None:
        self.reset()
        self.lines = lines  # Same immutable tuple as the document session.
        self.total_line_count = total_line_count
        self.editor.setPlaceholderText("Empty source file" if not lines else "")

    def _retained_range(self) -> str:
        if not self.lines:
            return "Empty source file"
        return f"Available lines: {self.first_line:,}–{self.total_line_count:,}"

    def ensure_page(self) -> None:
        if self.lines and not self._materialized:
            self._load_page(0, align="start")

    def set_bookmarks(self, lines: set[int]) -> None:
        self.bookmarked_lines = set(lines)
        self._apply_bookmarks()
        self._update_selections()

    def _apply_bookmarks(self) -> None:
        self.editor.set_bookmarked_blocks({
            number - self.first_line - self.page_start: True
            for number in self.bookmarked_lines
            if self.first_line + self.page_start <= number < self.first_line + self.page_end
        })

    def _load_page(self, index: int, *, align="center") -> None:
        self._from_viewport = True
        self._cancel_page_highlights()
        start, end = index, index + 1
        characters = len(self.lines[index]) + 1
        before = SOURCE_PAGE_LINES // 2 if align == "center" else SOURCE_PAGE_LINES - 1
        if align != "start":
            while start > 0 and index - start < before:
                size = len(self.lines[start - 1]) + 1
                if characters + size > SOURCE_PAGE_CHARACTERS:
                    break
                start -= 1
                characters += size
        if align != "end":
            while end < len(self.lines) and end - start < SOURCE_PAGE_LINES:
                size = len(self.lines[end]) + 1
                if characters + size > SOURCE_PAGE_CHARACTERS:
                    break
                characters += size
                end += 1
        self.page_start, self.page_end = start, end
        self._materialized = True
        self.highlighter.set_matches(SearchMatches())
        self.marker.set_match_blocks(array("I"), None)
        self.editor.first_source_line = self.first_line + start
        self.editor.setPlainText("\n".join(self.lines[start:end]))
        self._apply_bookmarks()
        self.editor.update_gutter()
        self.first_button.setEnabled(start > 0)
        self.previous_button.setEnabled(start > 0)
        self.next_button.setEnabled(end < len(self.lines))
        self.last_button.setEnabled(end < len(self.lines))
        self._update_range()
        self._schedule_page_highlights()

    def _update_range(self) -> None:
        self.range_label.setText(
            f"{self.first_line + self.page_start:,}–{self.first_line + self.page_end - 1:,}"
        )

    def _show_line_error(self, message: str) -> None:
        self.goto_input.setToolTip(message)
        QToolTip.showText(
            self.goto_input.mapToGlobal(self.goto_input.rect().bottomLeft()),
            message, self.goto_input,
        )

    def go_to_line(self, number: int, *, highlight=True, center_page=False) -> bool:
        index = number - self.first_line
        if not 0 <= index < len(self.lines):
            self._show_line_error(f"Line {number:,} is not loaded. {self._retained_range()}")
            return False
        self.goto_input.setToolTip("Enter a line-number to jump to")
        QToolTip.hideText()
        if highlight:
            self.target_line = number
            self._from_viewport = True
        margin = max(1, self.editor.viewport().height() // self.editor.fontMetrics().height() // 2)
        near_page_edge = ((self.page_start > 0 and index - self.page_start < margin) or
                          (self.page_end < len(self.lines) and self.page_end - index <= margin))
        if not self.page_start <= index < self.page_end or (center_page and near_page_edge):
            self._load_page(index)
        cursor = QTextCursor(self.editor.document().findBlockByNumber(index - self.page_start))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.goto_input.setText(str(number))
        self._update_range()
        self._update_selections()
        return True

    def go_to_input(self) -> None:
        value = "".join(self.goto_input.text().split())
        if not value.isascii() or not value.isdecimal():
            self._show_line_error(f"Enter a valid line number. {self._retained_range()}")
            return
        # Bound parsing of arbitrary pasted input, without QSpinBox's int32 limit.
        if len(value) > 20:
            self._show_line_error(
                f"Enter a line number between {self.first_line:,} and {self.total_line_count:,}."
                if self.lines else "Empty source file"
            )
            return
        self.go_to_line(int(value))

    def first_page(self) -> None:
        if self.lines:
            self._load_page(0, align="start")
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            self.editor.verticalScrollBar().setValue(0)
            self._update_selections()

    def next_page(self) -> None:
        if self.page_end < len(self.lines):
            self._load_page(self.page_end, align="start")
            self._update_selections()

    def previous_page(self) -> None:
        if self.page_start:
            self._load_page(self.page_start - 1, align="end")
            self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())
            self._update_selections()

    def last_page(self) -> None:
        if self.lines:
            self._load_page(len(self.lines) - 1, align="end")
            self.editor.moveCursor(QTextCursor.MoveOperation.End)
            self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())
            self._update_selections()

    def set_query(self, query: str) -> None:
        self.cancel_search()
        self.query = query

    def _use_viewport_anchor(self, *_args) -> None:
        self._from_viewport = True

    def cancel_search(self) -> None:
        self._search_timer.stop()
        self._search_work = None
        self._pending = SourceMatches()
        self._pending_navigation = None
        self.matches = SourceMatches()
        self.current_match = None
        self._from_viewport = True
        self.searched_query = None
        self._cancel_page_highlights()
        self.highlighter.set_matches(SearchMatches())
        self.marker.set_match_blocks(array("I"), None)
        self._status("")
        self._update_selections()

    def search(self) -> None:
        if self.query == self.searched_query:
            self.navigate(True)
            return
        self.cancel_search()
        self.searched_query = self.query
        if not self.query:
            return
        self._search_work = iter_source_matches(self.lines, self.query)
        self._status("Searching…")
        self._search_timer.start(0)

    def _advance_search(self) -> None:
        if self._search_work is None:
            return
        elapsed = QElapsedTimer()
        elapsed.start()
        while elapsed.elapsed() < SOURCE_BATCH_MS:
            try:
                match = next(self._search_work)
            except StopIteration:
                self._search_work = None
                self.matches = self._pending
                self._pending = SourceMatches()
                self._status(f"0 / {len(self.matches):,}" if self.matches else "No matches")
                self._schedule_page_highlights()
                navigation = self._pending_navigation
                self._pending_navigation = None
                if navigation is not None:
                    self.navigate(navigation)
                return
            if match is not None:
                self._pending.append(*match)
        self._search_timer.start(1)

    def navigate(self, forward: bool) -> None:
        if self.searched_query != self.query:
            self.search()
        if self.is_searching:
            self._pending_navigation = forward
            return
        if not self.matches:
            return
        if self.current_match is None or self._from_viewport:
            anchor = self.page_start + self.editor.firstVisibleBlock().blockNumber()
            index = bisect_left(self.matches.lines, anchor)
            if not forward:
                index -= 1
        else:
            index = self.current_match + (1 if forward else -1)
        self.current_match = index % len(self.matches)
        row = self.matches.lines[self.current_match]
        self.go_to_line(self.first_line + row, highlight=False)
        block = self.editor.document().findBlockByNumber(row - self.page_start)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + self.matches.starts[self.current_match])
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self._from_viewport = False
        self._status(f"{self.current_match + 1:,} / {len(self.matches):,}")
        self._update_selections()

    def _cancel_page_highlights(self) -> None:
        self._page_timer.stop()
        self._page_work = None

    def _schedule_page_highlights(self) -> None:
        self._cancel_page_highlights()
        self._page_work = self._project_page_matches()
        self._page_timer.start(0)

    def _project_page_matches(self):
        matches = SearchMatches()
        blocks = array("I")
        start = bisect_left(self.matches.lines, self.page_start)
        end = bisect_left(self.matches.lines, self.page_end)
        last_row = None
        block_position = 0
        for index in range(start, end):
            row = self.matches.lines[index] - self.page_start
            if row != last_row:
                block_position = self.editor.document().findBlockByNumber(row).position()
                blocks.append(row)
                last_row = row
            matches.append(block_position + self.matches.starts[index],
                           block_position + self.matches.ends[index])
            yield
        self.highlighter.set_matches(matches, blocks)
        self.marker.set_match_blocks(blocks, self.editor.document())

    def _advance_page_highlights(self) -> None:
        elapsed = QElapsedTimer()
        elapsed.start()
        while self._page_work is not None and elapsed.elapsed() < SOURCE_BATCH_MS:
            try:
                next(self._page_work)
            except StopIteration:
                self._page_work = None
        if self._page_work is not None:
            self._page_timer.start(1)

    def _update_selections(self) -> None:
        selections = []
        if self.target_line is not None and self.target_line not in self.bookmarked_lines:
            row = self.target_line - self.first_line - self.page_start
            if 0 <= row < self.page_end - self.page_start:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(self.editor.document().findBlockByNumber(row))
                selection.format.setBackground(QColor(THEME_COLORS["selection"]))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selections.append(selection)
        if self.current_match is not None:
            index = self.current_match
            row = self.matches.lines[index] - self.page_start
            if 0 <= row < self.page_end - self.page_start:
                block = self.editor.document().findBlockByNumber(row)
                selection = QTextEdit.ExtraSelection()
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + self.matches.starts[index])
                cursor.setPosition(block.position() + self.matches.ends[index], QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = cursor
                selection.format.setBackground(QColor(THEME_COLORS["search_current"]))
                selection.format.setForeground(QColor(THEME_COLORS["background"]))
                selections.append(selection)
        self.editor.setExtraSelections(selections)
