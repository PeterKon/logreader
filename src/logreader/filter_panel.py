"""Qt filter controls and configuration generation for Logreader."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
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
    QStyle,
    QStyleOptionButton,
    QStyleOptionSpinBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from .config import (
    DEFAULT_ENABLED_PATTERNS,
    HTTP_STATUS_PATTERN_KEYS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    PATTERN_PRESETS_BY_KEY,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
from .theme import THEME_COLORS, configure_clear_button


FILTER_ALIGNMENT_EXTRA_WIDTH = 115


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


class FilterPanel(QGroupBox):
    """Own all filter controls and build their shared configuration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Filters", parent)
        self.setObjectName("filterGroup")
        self._pattern_checkboxes: dict[str, QCheckBox] = {}
        self._build_interface()

    def _build_interface(self) -> None:
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(10, 18, 10, 10)
        outer_layout.setSpacing(0)

        self._filter_alignment_container = QWidget(self)
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

        toggle_all_button = UnclippedPushButton("Global toggle all")
        toggle_all_button.setObjectName("toggleAllButton")
        toggle_all_button.setToolTip(
            "Enable every pattern, or disable every pattern when all are enabled."
        )
        toggle_all_button.clicked.connect(self.toggle_all_patterns)
        top_layout.addWidget(toggle_all_button)

        self._separate_entries = VisibleCheckBox("Line-separator")
        self._separate_entries.setObjectName("separateEntriesCheck")
        self._separate_entries.setProperty("islandIndicator", True)
        self._separate_entries.setChecked(False)
        self._separate_entries.setToolTip(
            "Draw a horizontal rule between non-contiguous result excerpts."
        )
        top_layout.addStretch(1)
        layout.addWidget(top_controls)

        text_groups = QWidget(self._filter_alignment_container)
        text_groups.setObjectName("textPatternGroupsRow")
        text_groups_layout = QHBoxLayout(text_groups)
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
        text_pattern_group = self._build_pattern_group(
            "Other errors",
            TEXT_PATTERN_KEYS,
            object_name="textPatternGroup",
            columns=4,
            toggle_object_name="toggleTextButton",
        )
        text_pattern_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        text_groups_layout.addWidget(text_pattern_group, 1)
        layout.addWidget(text_groups)

        http_row = QWidget(self._filter_alignment_container)
        http_row.setObjectName("httpStatusRow")
        http_layout = QHBoxLayout(http_row)
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
        http_status_group = self._build_pattern_group(
            "HTTP codes",
            HTTP_STATUS_PATTERN_KEYS,
            object_name="httpStatusGroup",
            columns=1,
        )
        http_options = QWidget(http_row)
        http_options.setObjectName("httpOptionsColumn")
        http_options.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        http_options_layout = QVBoxLayout(http_options)
        http_options_layout.setContentsMargins(0, 0, 0, 0)
        http_options_layout.setSpacing(9)
        http_status_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        http_options_layout.addWidget(http_status_group)
        http_options_layout.addWidget(
            self._separate_entries,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        http_layout.addWidget(http_options, 1, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(http_row)
        self._filter_alignment_container.setMaximumWidth(
            top_controls.sizeHint().width() + FILTER_ALIGNMENT_EXTRA_WIDTH
        )

    def _build_custom_pattern_group(self) -> QGroupBox:
        (
            group,
            self._custom_pattern,
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
    ) -> tuple[QGroupBox, QLineEdit, QListWidget]:
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
            custom_patterns=self._list_values(self._custom_pattern_list),
            regex_patterns=self._list_values(self._regex_pattern_list),
            separate_entries=self._separate_entries.isChecked(),
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

    def toggle_patterns(self, pattern_keys: tuple[str, ...]) -> None:
        """Toggle every checkbox in one pattern category as a unit."""

        enable_all = not all(
            self._pattern_checkboxes[key].isChecked() for key in pattern_keys
        )
        for key in pattern_keys:
            self._pattern_checkboxes[key].setChecked(enable_all)
