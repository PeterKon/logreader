"""Qt filter controls and configuration generation for Logreader."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSpinBox,
    QStylePainter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    DEFAULT_CONTEXT,
    DEFAULT_ENABLED_PATTERNS,
    HTTP_STATUS_PATTERN_KEYS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    PATTERN_PRESETS_BY_KEY,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
from .theme import THEME_COLORS, configure_action_button, configure_clear_button
from ..file_loader import DEFAULT_MAX_LINES_SCANNED
from .widgets.input_menus import InputContextMenu, ScrollbarContextMenu


MATCH_CASE_ROLE = Qt.ItemDataRole.UserRole + 1
EXCLUDE_ROLE = Qt.ItemDataRole.UserRole + 2


class SearchOptionButton(QPushButton):
    """Search option toggle with a crossed-out appearance while off."""

    def __init__(self, text: str, pattern: str, action: str, object_name: str) -> None:
        super().__init__(text)
        self._action = action
        self.setObjectName(object_name)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"{action.capitalize()} for {pattern}")
        self.setFixedSize(self.fontMetrics().horizontalAdvance(self.text()) + 12, 16)
        self.setStyleSheet(
            "QPushButton { background: rgba(128, 128, 128, 12);"
            " color: rgba(170, 170, 170, 115);"
            " border: 1px solid rgba(150, 150, 150, 55);"
            " border-radius: 3px; padding: 0 4px; min-height: 0; }"
            f"QPushButton:!checked:hover {{ background: {THEME_COLORS['ui_button_hover']};"
            " border-color: #a0a0a0; color: #dddddd; }"
            f"QPushButton:checked {{ background: {THEME_COLORS['ui_primary']};"
            f" border-color: {THEME_COLORS['ui_accent']}; color: #ffffff; }}"
            f"QPushButton:checked:hover {{ background: {THEME_COLORS['ui_primary_hover']}; }}"
        )
        self.toggled.connect(self._update_tooltip)
        self._update_tooltip(False)

    def _update_tooltip(self, checked: bool) -> None:
        if self._action == "excluding matches":
            self.setToolTip(
                "Click for this pattern to not exclude matches"
                if checked else "Click for this pattern to exclude matches"
            )
            return
        self.setToolTip(
            f"Click to disable {self._action}"
            if checked else f"Click to enable {self._action}"
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().paintEvent(event)
        if not self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(160, 160, 160, 90), 1.0))
            bounds = self.rect().adjusted(3, 3, -3, -3)
            painter.drawLine(bounds.topLeft(), bounds.bottomRight())
            painter.drawLine(bounds.bottomLeft(), bounds.topRight())


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
            else QColor(THEME_COLORS["ui_disabled_text"])
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
                QColor(THEME_COLORS["ui_text"]),
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


class TieredSpinBox(VisibleSpinBox):
    """Move through step boundaries, using the smaller tier when stepping down."""

    STEP_TIERS: tuple[tuple[int, int], ...] = ()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stepping_with_mouse = False
        InputContextMenu(self.lineEdit(), spin_box=self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        control = self.style().hitTestComplexControl(
            QStyle.ComplexControl.CC_SpinBox, option, event.position().toPoint(), self,
        )
        self._stepping_with_mouse = event.button() == Qt.MouseButton.LeftButton and control in (
            QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown,
        )
        super().mousePressEvent(event)
        if self._stepping_with_mouse:
            self.clearFocus()
            self.lineEdit().deselect()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._stepping_with_mouse:
            self.clearFocus()
            self.lineEdit().deselect()
        self._stepping_with_mouse = False

    def stepBy(self, steps: int) -> None:  # noqa: N802 - Qt API name
        self.interpretText()
        value = self.value()
        for _ in range(abs(steps)):
            lower = self.minimum()
            for upper, increment in self.STEP_TIERS:
                if value < upper or (steps < 0 and value == upper):
                    if steps > 0:
                        target = min(upper, (value // increment + 1) * increment)
                    else:
                        target = max(lower, ((value - 1) // increment) * increment)
                    break
                lower = upper
            else:
                target = self.maximum()
            target = max(self.minimum(), min(self.maximum(), target))
            if target == value:
                break
            value = target
        self.setValue(value)
        if self._stepping_with_mouse:
            self.lineEdit().deselect()


class ContextSpinBox(TieredSpinBox):
    STEP_TIERS = ((5, 1), (10, 5), (100, 10), (1_000, 100))

    def __init__(self) -> None:
        super().__init__()
        self.setRange(0, 1_000)
        self.setValue(DEFAULT_CONTEXT)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)


class ScanLimitSpinBox(TieredSpinBox):
    """Positive source-line count with locale-independent space grouping."""

    STEP_TIERS = (
        (10_000, 1_000),
        (1_000_000, 100_000),
        (10_000_000, 1_000_000),
        (2_147_483_647, 10_000_000),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setRange(1, 2_147_483_647)
        self.setValue(DEFAULT_MAX_LINES_SCANNED)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setKeyboardTracking(False)
        self.setAccessibleName("Max lines scanned")
        self.setToolTip("Scan this many lines from the end/tail of the file.")

    def textFromValue(self, value: int) -> str:  # noqa: N802
        return f"{value:,}".replace(",", " ")

    def valueFromText(self, text: str) -> int:  # noqa: N802
        digits = "".join(text.split())
        return int(digits) if digits else self.minimum()

    def validate(self, text: str, position: int):
        digits = "".join(text.split())
        state = QValidator.State.Invalid
        if not digits:
            state = QValidator.State.Intermediate
        elif digits.isascii() and digits.isdecimal() and len(digits) <= 10:
            value = int(digits)
            if self.minimum() <= value <= self.maximum():
                state = QValidator.State.Acceptable
            elif value < self.minimum():
                state = QValidator.State.Intermediate
        return state, text, position


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


class FilterPages(QStackedWidget):
    """Reserve space for the visible editor only."""

    def sizeHint(self) -> QSize:  # noqa: N802
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()


class SearchListResizeHandle(QWidget):
    """Resize both search lists from a shared drag grip."""

    height_changed = Signal(int)
    DEFAULT_LIST_HEIGHT = 160

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("searchListResizeHandle")
        self.setAccessibleName("Resize search lists")
        self.setToolTip("Drag to resize both lists")
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFixedHeight(10)
        self._list_height = self.DEFAULT_LIST_HEIGHT
        self._drag_origin: tuple[float, int] | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = (event.globalPosition().y(), self._list_height)
            event.accept()
            self.update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            y, height = self._drag_origin
            new_height = max(124, min(310, height + round(event.globalPosition().y() - y)))
            if new_height != self._list_height:
                self._list_height = new_height
                self.height_changed.emit(new_height)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            event.accept()
            self.update()
        else:
            super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = None
        super().hideEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = "ui_accent" if self.underMouse() or self._drag_origin else "ui_border_strong"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME_COLORS[color]))
        painter.drawRoundedRect(QRectF((self.width() - 35) / 2, 3.5, 35, 3), 1.5, 1.5)


class FilterPanel(QGroupBox):
    """Own all filter controls and build their shared configuration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filterGroup")
        self.setAccessibleName("Filters")
        self._pattern_checkboxes: dict[str, QCheckBox] = {}
        self._bulk_buttons: list[tuple[QPushButton, tuple[str, ...]]] = []
        self._build_interface()
        for checkbox in self._pattern_checkboxes.values():
            checkbox.toggled.connect(self._update_summary)
        for pattern_list in (self._custom_pattern_list, self._regex_pattern_list):
            pattern_list.itemChanged.connect(self._update_summary)
        self._update_summary()

    def _build_interface(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._base_controls = QWidget(self)
        self._base_controls.setObjectName("fileControlsRow")
        top_layout = QHBoxLayout(self._base_controls)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addStretch(1)

        self._combined_view = VisibleCheckBox("Combined view")
        self._combined_view.setObjectName("combinedViewCheck")
        self._combined_view.setProperty("islandIndicator", True)
        self._combined_view.setChecked(True)
        self._combined_view.setToolTip(
            "Show all matches in one combined category on the results view."
        )
        top_layout.addWidget(self._combined_view)

        self._separate_entries = VisibleCheckBox("Line-spacing")
        self._separate_entries.setObjectName("separateEntriesCheck")
        self._separate_entries.setProperty("islandIndicator", True)
        self._separate_entries.setChecked(True)
        self._separate_entries.setToolTip(
            "Add a small gap as separation between mismatching context/errors in results."
        )
        top_layout.addWidget(self._separate_entries)
        top_layout.addWidget(self._make_top_separator("topSeparatorContext"))

        self._context_spin = ContextSpinBox()
        self._context_spin.setObjectName("contextSpin")
        self._context_spin.setFixedWidth(self.fontMetrics().horizontalAdvance("1 000") + 48)
        context_label = QLabel("Context around matches")
        context_label.setObjectName("contextLabel")
        top_layout.addWidget(context_label)
        top_layout.addWidget(self._context_spin)
        top_layout.addWidget(self._make_top_separator("topSeparatorLimit"))

        self._limit_spin = ScanLimitSpinBox()
        self._limit_spin.setObjectName("limitSpin")
        self._limit_spin.setFixedWidth(self.fontMetrics().horizontalAdvance("2 147 483 647") + 48)
        limit_label = QLabel("Max lines scanned")
        limit_label.setObjectName("limitLabel")
        top_layout.addWidget(limit_label)
        top_layout.addWidget(self._limit_spin)

        layout.addWidget(self._base_controls)

        filter_header = QWidget(self)
        filter_header.setObjectName("filterHeader")
        header_layout = QHBoxLayout(filter_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        self._tabs = QTabBar(filter_header)
        self._tabs.setObjectName("filterTabs")
        self._tabs.setAccessibleName("Filter editors")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tab_counts: list[QLabel] = []
        for title in ("Common patterns", "Advanced patterns", "Text and Regex"):
            index = self._tabs.addTab(title)
            count = QLabel(self._tabs)
            count.setObjectName("filterTabCount")
            count.setContentsMargins(0, 0, 8, 0)
            count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, count)
            self._tab_counts.append(count)
        header_layout.addWidget(self._tabs)
        header_layout.addStretch(1)
        self._exclusions_label = QLabel()
        self._exclusions_label.setObjectName("filterExclusions")
        header_layout.addWidget(self._exclusions_label)
        self._toggle_all_button = UnclippedPushButton("Select all text patterns")
        configure_action_button(self._toggle_all_button)
        self._toggle_all_button.setObjectName("toggleAllButton")
        self._toggle_all_button.setToolTip(
            "Affects colon / regular and other matches. Keeps HTTP and custom searches unchanged."
        )
        self._toggle_all_button.clicked.connect(self.toggle_all_patterns)
        self._bulk_buttons.append((self._toggle_all_button, PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS))
        header_layout.addWidget(self._toggle_all_button)
        layout.addWidget(filter_header)

        self._pages = FilterPages(self)
        self._pages.setObjectName("filterPages")
        self._pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        patterns = QWidget()
        patterns.setObjectName("commonPatternsPage")
        patterns_layout = QHBoxLayout(patterns)
        patterns_layout.setContentsMargins(0, 4, 0, 4)
        patterns_layout.setSpacing(12)
        patterns_layout.addWidget(
            self._build_pattern_group(
                "Other matches",
                TEXT_PATTERN_KEYS,
                object_name="textPatternGroup",
                columns=4,
                toggle_object_name="toggleTextButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        patterns_layout.addWidget(self._make_group_separator())
        patterns_layout.addWidget(
            self._build_pattern_group(
                "Colon / regular matches",
                PAIRED_PATTERN_KEYS,
                object_name="pairedPatternGroup",
                columns=2,
                toggle_object_name="togglePairedButton",
            ),
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        self._pages.addWidget(patterns)
        advanced = QWidget()
        advanced.setObjectName("advancedPatternsPage")
        advanced_layout = QHBoxLayout(advanced)
        advanced_layout.setContentsMargins(0, 4, 0, 4)
        advanced_layout.setSpacing(12)
        advanced_layout.addWidget(
            self._build_pattern_group(
                "HTTP matches",
                HTTP_STATUS_PATTERN_KEYS,
                object_name="httpStatusGroup",
                columns=1,
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        advanced_layout.addStretch(1)
        self._pages.addWidget(advanced)
        searches = QWidget()
        searches.setObjectName("customSearchesPage")
        searches_layout = QVBoxLayout(searches)
        searches_layout.setContentsMargins(0, 4, 0, 0)
        searches_layout.setSpacing(0)
        searches_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_custom_pattern_group(), 1, Qt.AlignmentFlag.AlignTop)
        columns.addWidget(self._build_regex_pattern_group(), 1, Qt.AlignmentFlag.AlignTop)
        searches_layout.addLayout(columns)
        self._resize_handle = SearchListResizeHandle(searches)
        self._resize_handle.height_changed.connect(self._resize_search_lists)
        searches_layout.addWidget(self._resize_handle)
        searches_layout.addStretch(1)
        self._pages.addWidget(searches)
        self._tabs.currentChanged.connect(self._select_editor)
        layout.addWidget(self._pages)
        layout.addStretch(1)

    def set_analysis_button(self, button: QPushButton) -> None:
        if button.parentWidget() is not self._base_controls:
            self._base_controls.layout().insertWidget(0, button)
        button.show()

    def _select_editor(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._toggle_all_button.setVisible(index == 0)
        self._pages.updateGeometry()

    def _resize_search_lists(self, height: int) -> None:
        for pattern_list in (self._custom_pattern_list, self._regex_pattern_list):
            pattern_list.setFixedHeight(height)
        self._pages.updateGeometry()

    def _update_summary(self) -> None:
        for index, keys in enumerate((PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS, HTTP_STATUS_PATTERN_KEYS)):
            selected = sum(self._pattern_checkboxes[key].isChecked() for key in keys)
            self._set_tab_count(index, f"({selected}/{len(keys)})", f"{selected} of {len(keys)} selected")
        custom_count = self._custom_pattern_list.count()
        regex_count = self._regex_pattern_list.count()
        search_count = custom_count + regex_count
        self._set_tab_count(2, f"({search_count})", f"{search_count} searches")
        self._custom_heading.setText(f"Plain text matches ({custom_count})")
        self._regex_heading.setText(f"Regex matches ({regex_count})")
        excluded = sum(
            bool(pattern_list.item(index).data(EXCLUDE_ROLE))
            for pattern_list in (self._custom_pattern_list, self._regex_pattern_list)
            for index in range(pattern_list.count())
        )
        self._exclusions_label.setText(f"{excluded} exclusion{'s' if excluded != 1 else ''}")
        self._exclusions_label.setVisible(excluded > 0)
        for button, keys in self._bulk_buttons:
            verb = "Clear" if all(self._pattern_checkboxes[key].isChecked() for key in keys) else "Select"
            scope = " all text patterns" if button is self._toggle_all_button else " all"
            button.setText(verb + scope)

    def _set_tab_count(self, index: int, text: str, description: str) -> None:
        label = self._tab_counts[index]
        if label.text() == text:
            return
        label.setText(text)
        label.adjustSize()
        title = self._tabs.tabText(index)
        # Refresh the tab's cached width after its count label changes.
        self._tabs.setTabText(index, title)
        self._tabs.setAccessibleTabName(index, f"{title}: {description}")

    @staticmethod
    def _make_group_separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("filterSectionSeparator")
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedWidth(1)
        return separator

    def _build_custom_pattern_group(self) -> QGroupBox:
        (
            group,
            self._custom_pattern,
            self._custom_pattern_list,
        ) = self._build_list_search_group(
            title="Plain text matches",
            group_object_name="customPatternGroup",
            input_object_name="customPattern",
            add_button_object_name="customPatternAddButton",
            list_object_name="customPatternList",
            add_handler=self.add_custom_pattern,
        )
        self._custom_heading = group.findChild(QLabel, "filterSectionTitle")
        return group

    def _build_regex_pattern_group(self) -> QGroupBox:
        (
            group,
            self._regex_pattern,
            self._regex_pattern_list,
        ) = self._build_list_search_group(
            title="Regex matches",
            group_object_name="regexPatternGroup",
            input_object_name="regexPattern",
            add_button_object_name="regexPatternAddButton",
            list_object_name="regexPatternList",
            add_handler=self.add_regex_pattern,
        )
        self._regex_heading = group.findChild(QLabel, "filterSectionTitle")
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
    ) -> tuple[QGroupBox, QLineEdit, QListWidget]:
        group = QGroupBox()
        group.setObjectName(group_object_name)
        group.setAccessibleName(title)
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 0, 8, 4)
        layout.setSpacing(8)
        # Keep controls anchored while a smaller list height propagates to its parents.
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        heading = QLabel(title)
        heading.setObjectName("filterSectionTitle")
        layout.addWidget(heading)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        input_box = QLineEdit()
        input_box.setObjectName(input_object_name)
        InputContextMenu(input_box, undo=True, redo=True, cut=True)
        configure_clear_button(input_box)
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
        configure_action_button(add_button)
        add_button.setObjectName(add_button_object_name)
        add_button.clicked.connect(add_handler)
        entry_row.addWidget(add_button)
        layout.addLayout(entry_row)

        pattern_list = QListWidget()
        for scrollbar in (pattern_list.verticalScrollBar(), pattern_list.horizontalScrollBar()):
            ScrollbarContextMenu(scrollbar)
        pattern_list.setObjectName(list_object_name)
        pattern_list.setSpacing(0)
        pattern_list.setUniformItemSizes(True)
        pattern_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pattern_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        pattern_list.setStyleSheet(
            "QListWidget::item { margin: 0; padding: 0; }"
            "QListWidget::item:hover, QListWidget::item:selected {"
            " background: transparent; }"
        )
        pattern_list.setFixedHeight(SearchListResizeHandle.DEFAULT_LIST_HEIGHT)
        layout.addWidget(pattern_list)
        layout.addStretch(1)
        return group, input_box, pattern_list

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
        group = QGroupBox()
        group.setObjectName(object_name)
        group.setAccessibleName(title)
        group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        outer_layout = QVBoxLayout(group)
        outer_layout.setContentsMargins(8, 0, 8, 4)
        outer_layout.setSpacing(8)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("filterSectionTitle")
        heading.setMinimumHeight(28)
        header.addWidget(heading)
        if toggle_object_name is not None:
            toggle_button = QPushButton("Select all")
            configure_action_button(toggle_button)
            toggle_button.setObjectName(toggle_object_name)
            toggle_button.clicked.connect(
                lambda _checked=False, keys=pattern_keys: self.toggle_patterns(keys)
            )
            self._bulk_buttons.append((toggle_button, pattern_keys))
            header.addWidget(toggle_button)
        header.addStretch(1)
        outer_layout.addLayout(header)
        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer_layout.addLayout(layout)

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
            row, column = divmod(index, columns)
            layout.addWidget(
                checkbox,
                row,
                column,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )

        column_width = max(checkbox.sizeHint().width() for checkbox in checkboxes)
        for column in range(columns):
            layout.setColumnMinimumWidth(column, column_width)

        return group

    @staticmethod
    def _pattern_control_label(key: str) -> str:
        """Return a concise GUI label without changing result headings."""

        if key == "http_4xx":
            return "4xx"
        if key == "http_5xx":
            return "5xx"
        return PATTERN_PRESETS_BY_KEY[key].label.capitalize()

    def build_config(self) -> LogreaderConfig:
        """Build the shared configuration represented by the controls."""

        self._limit_spin.interpretText()
        return LogreaderConfig(
            context=self._context_spin.value(),
            max_lines_scanned=self._limit_spin.value(),
            enabled_patterns=tuple(
                key
                for key in PATTERN_KEYS
                if self._pattern_checkboxes[key].isChecked()
            ),
            custom_patterns=self._list_values(self._custom_pattern_list),
            custom_pattern_match_case=tuple(
                bool(self._custom_pattern_list.item(index).data(MATCH_CASE_ROLE))
                for index in range(self._custom_pattern_list.count())
            ),
            custom_pattern_exclude=tuple(
                bool(self._custom_pattern_list.item(index).data(EXCLUDE_ROLE))
                for index in range(self._custom_pattern_list.count())
            ),
            regex_patterns=self._list_values(self._regex_pattern_list),
            regex_pattern_exclude=tuple(
                bool(self._regex_pattern_list.item(index).data(EXCLUDE_ROLE))
                for index in range(self._regex_pattern_list.count())
            ),
            separate_entries=self._separate_entries.isChecked(),
            combined_view=self._combined_view.isChecked(),
        )

    @staticmethod
    def _list_values(pattern_list: QListWidget) -> tuple[str, ...]:
        return tuple(
            str(
                pattern_list.item(index).data(Qt.ItemDataRole.UserRole)
            )
            for index in range(pattern_list.count())
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

        item_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        item_label.setToolTip(pattern)
        is_custom = pattern_list is self._custom_pattern_list
        prefix = "customPattern" if is_custom else "regexPattern"
        options = [("Exclude", EXCLUDE_ROLE, "excluding matches", f"{prefix}ExcludeButton")]
        if is_custom:
            options.append(
                ("Case", MATCH_CASE_ROLE, "matching case", "customPatternMatchCaseButton")
            )
        for text, role, action, object_name in options:
            item.setData(role, False)
            button = SearchOptionButton(text, pattern, action, object_name)
            button.toggled.connect(
                lambda checked, list_item=item, data_role=role:
                list_item.setData(data_role, checked)
            )
            item_layout.addWidget(button)

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
        self._update_summary()

    def remove_custom_pattern(self, item: QListWidgetItem) -> None:
        """Remove one committed custom pattern from the filter list."""

        self._remove_search_list_item(self._custom_pattern_list, item)

    def remove_regex_pattern(self, item: QListWidgetItem) -> None:
        """Remove one committed regex from the filter list."""

        self._remove_search_list_item(self._regex_pattern_list, item)

    def _remove_search_list_item(
        self,
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
        self._update_summary()

    def toggle_all_patterns(self) -> None:
        """Toggle text error presets while preserving manual HTTP selections."""

        self.toggle_patterns(PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS)

    def toggle_patterns(self, pattern_keys: tuple[str, ...]) -> None:
        """Toggle every checkbox in one pattern category as a unit."""

        enable_all = not all(
            self._pattern_checkboxes[key].isChecked() for key in pattern_keys
        )
        for key in pattern_keys:
            self._pattern_checkboxes[key].setChecked(enable_all)
