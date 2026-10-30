"""Qt filter controls and configuration generation for Logreader."""

from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QCursor, QFont, QFontDatabase, QMouseEvent, QPainter, QPainterPath, QPalette, QPen, QRegion, QValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSpinBox,
    QTabBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..config import (
    ADVANCED_PATTERN_KEYS,
    APPLICATION_PATTERN_KEYS,
    DATABASE_PATTERN_KEYS,
    DEFAULT_CONTEXT,
    DEFAULT_ENABLED_PATTERNS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    PATTERN_PRESETS_BY_KEY,
    SYSTEM_RUNTIME_PATTERN_KEYS,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
from .theme import THEME_COLORS, configure_action_button, configure_clear_button, paint_checkmark
from .dialogs import CompactDialog
from .title_bar import TITLE_MENU_STYLE_SHEET, TitleMenu
from ..file_loader import DEFAULT_MAX_LINES_SCANNED
from ..regex_presets import REGEX_PRESET_NAMES, REGEX_PRESETS
from .widgets.input_menus import InputContextMenu, ScrollbarContextMenu


MATCH_CASE_ROLE = Qt.ItemDataRole.UserRole + 1
EXCLUDE_ROLE = Qt.ItemDataRole.UserRole + 2
EXCLUSIVE_ROLE = Qt.ItemDataRole.UserRole + 3
DISABLED_ROLE = Qt.ItemDataRole.UserRole + 4
EXCLUSIVE_TOOLTIP = 'Only lines that match an "exclusive" item will qualify.'
EXCLUDE_TOOLTIP = "Lines that match this item will not qualify."


class PatternEditor(QPlainTextEdit):
    @staticmethod
    def has_line_break(text: str) -> bool:
        return any(character in text for character in "\r\n\u2028\u2029")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802
        return not self.has_line_break(source.text()) and super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        if self.canInsertFromMimeData(source):
            super().insertFromMimeData(source)


class PatternEditDialog(CompactDialog):
    def __init__(self, pattern: str, *, is_regex: bool, parent: QWidget) -> None:
        super().__init__("Edit regex" if is_regex else "Edit pattern", parent, resizable=True)
        self._is_regex = is_regex
        self.setObjectName("patternEditDialog")
        self.resize(620, 300)
        self.setMinimumSize(400, 240)
        layout = self.body_layout
        self.editor = PatternEditor(pattern)
        self.editor.setAccessibleName("Regex" if is_regex else "Pattern")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(self.font().pointSizeF())
        self.editor.setFont(font)
        self.editor.setTabChangesFocus(True)
        layout.addWidget(self.editor, 1)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setStyleSheet(f"color: {THEME_COLORS['ui_excluded']};")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.set_buttons(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            default=QDialogButtonBox.StandardButton.Save,
        )
        self.editor.setFocus()

    def pattern(self) -> str:
        return self.editor.toPlainText().strip()

    def accept(self) -> None:
        pattern = self.pattern()
        error = "Pattern cannot be empty." if not pattern else ""
        if self.editor.has_line_break(self.editor.toPlainText()):
            error = "Pattern must be on one line."
        if not error and self._is_regex:
            try:
                re.compile(pattern)
            except re.error as exc:
                error = f"Invalid regex: {exc}"
        if error:
            self.error_label.setText(error)
            self.error_label.show()
            self.editor.setFocus()
            return
        super().accept()


class SearchPatternMenu(TitleMenu):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            TITLE_MENU_STYLE_SHEET
            + "QMenu { min-width: 206px; padding: 0 5px; border-radius: 6px;"
            + f" border-color: {THEME_COLORS['ui_border_strong']}; }}"
            + "QMenu::item { padding: 3px 8px 4px 31px; border-radius: 0; }"
            + "QMenu::indicator { width: 0; height: 0; }"
            + "QMenu::separator { margin: 0 3px; }"
        )
        self.setToolTipsVisible(True)
        self.hovered.connect(lambda _action: self.update())
        heading = QLabel("Matching", self)
        heading.setContentsMargins(8, 5, 8, 1)
        heading.setStyleSheet(f"background: transparent; color: {THEME_COLORS['ui_muted']};")
        heading_font = heading.font()
        if heading_font.pointSizeF() > 0:
            heading_font.setPointSizeF(heading_font.pointSizeF() * 11 / 12)
        else:
            heading_font.setPixelSize(round(heading_font.pixelSize() * 11 / 12))
        heading.setFont(heading_font)
        section = QWidgetAction(self)
        section.setText("Matching")
        section.setEnabled(False)
        section.setDefaultWidget(heading)
        self.addAction(section)

    def event(self, event) -> bool:
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                            QEvent.Type.MouseButtonRelease):
            point = event.position().toPoint()
            for action in self.actions():
                if (action.isVisible() and not action.isSeparator()
                        and not isinstance(action, QWidgetAction)
                        and self._item_rect(action).contains(point)):
                    bounds = self.actionGeometry(action)
                    if not bounds.contains(point):
                        point = QPoint(max(bounds.left(), min(point.x(), bounds.right())),
                                       max(bounds.top(), min(point.y(), bounds.bottom())))
                        event = QMouseEvent(event.type(), QPointF(point), event.globalPosition(),
                                            event.button(), event.buttons(), event.modifiers(),
                                            event.pointingDevice())
                    break
            result = super().event(event)
            # Qt invalidates only its original item bounds when hover changes.
            self.update()
            return result
        if event.type() == QEvent.Type.Leave:
            self.update()
        if event.type() == QEvent.Type.ToolTip:
            action = self.actionAt(event.pos())
            if action is None or action.toolTip() == action.text():
                return True
        return super().event(event)

    def _item_rect(self, action):
        bounds = self.actionGeometry(action)
        bounds.setLeft(1)
        bounds.setRight(self.width() - 2)
        return bounds

    @staticmethod
    def _trigger_without_closing(action) -> bool:
        if action is not None and action.isEnabled() and (
            action.isCheckable() or action.objectName() == "enablePattern"
        ):
            action.trigger()
            return True
        return False

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._trigger_without_closing(
            self.actionAt(event.position().toPoint())
        ):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and (
            self._trigger_without_closing(self.activeAction())
        ):
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.activeAction()
        if active is not None and active.isEnabled() and not active.isSeparator():
            bounds = self.actionGeometry(active)
            highlight = self._item_rect(active)
            painter.save()
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
            painter.setClipPath(outline)
            painter.setClipRegion(QRegion(highlight).subtracted(QRegion(bounds)),
                                  Qt.ClipOperation.IntersectClip)
            painter.fillRect(highlight, QColor(THEME_COLORS['ui_button_hover']))
            painter.restore()
        for action in self.actions():
            if not action.isVisible() or action.isSeparator():
                continue
            bounds = self.actionGeometry(action)
            painter.save()
            icon_center = bounds.center().y() + 0.5
            painter.translate(bounds.left() + 8, icon_center - 7)
            color = QColor(THEME_COLORS[
                "ui_disabled_text" if not action.isEnabled()
                else "ui_accent" if action.isChecked() else "ui_muted"
            ])
            painter.setPen(QPen(color, 1.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if action.objectName() == "caseSensitive":
                painter.drawRoundedRect(QRectF(1, 1, 12, 12), 2, 2)
                if action.isChecked():
                    paint_checkmark(painter, QRectF(0, 0, 14, 14), enabled=action.isEnabled())
            elif action.isCheckable():
                painter.drawEllipse(QRectF(1, 1, 12, 12))
                if action.isChecked():
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    painter.drawEllipse(QPointF(7, 7), 2.5, 2.5)
            elif action.objectName() == "editPattern":
                pencil = QPainterPath(QPointF(2, 9.4))
                pencil.lineTo(1.4, 12.6)
                pencil.lineTo(4.6, 12)
                pencil.lineTo(12.1, 4.5)
                pencil.quadTo(13, 3.6, 12.1, 2.7)
                pencil.lineTo(11.3, 1.9)
                pencil.quadTo(10.4, 1, 9.5, 1.9)
                pencil.closeSubpath()
                painter.drawPath(pencil)
                painter.drawLine(QPointF(8.3, 3.1), QPointF(10.9, 5.7))
            elif action.objectName() in ("enablePattern", "disablePattern"):
                painter.drawEllipse(QRectF(1, 1, 12, 12))
                if action.objectName() == "enablePattern":
                    play = QPainterPath(QPointF(5.5, 4.5))
                    play.lineTo(9.5, 7)
                    play.lineTo(5.5, 9.5)
                    play.closeSubpath()
                    painter.drawPath(play)
                else:
                    for x in (5.5, 8.5):
                        painter.drawLine(QPointF(x, 4.5), QPointF(x, 9.5))
            painter.restore()


class SearchPatternRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._context_target = False
        self._hovered = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu_button = QPushButton("⋯", self)
        self.menu_button.setObjectName("patternMenuButton")
        self.menu_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu_button.setFixedSize(24, 16)
        self.menu_button.setToolTip("Exclusive matching or exclusion")
        policy = self.menu_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.menu_button.setSizePolicy(policy)
        self.menu_button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 3px;"
            f" color: {THEME_COLORS['ui_text']};"
            " font-size: 16px; padding: 0; min-height: 0; }"
            f"QPushButton:hover {{ background: {THEME_COLORS['ui_button_hover']}; }}"
            f"QPushButton:pressed {{ background: {THEME_COLORS['ui_button_pressed']}; }}"
        )
        self.menu_button.hide()
        self.remove_button = QPushButton("-", self)
        self.remove_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        policy = self.remove_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.remove_button.setSizePolicy(policy)
        self.remove_button.hide()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._update_hover()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._update_hover()
        super().leaveEvent(event)

    def _update_hover(self) -> None:
        active = self._hovered and not self._context_target
        self.menu_button.setVisible(active)
        self.remove_button.setVisible(active)
        self.update()

    def set_context_target(self, active: bool) -> None:
        self._context_target = active
        self._update_hover()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        if self._hovered or self._context_target:
            color = QColor(THEME_COLORS["ui_accent"])
            color.setAlpha(20)
            painter.fillRect(self.rect(), color)
        if self._context_target:
            painter.setPen(QPen(QColor(THEME_COLORS["ui_accent"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            bounds = self.rect().adjusted(0, 0, -1, -1)
            painter.drawRect(bounds)


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
        paint_checkmark(
            painter, indicator, enabled=self.isEnabled(),
            partial=self.checkState() == Qt.CheckState.PartiallyChecked,
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


class BorderTitleGroupBox(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._border_widgets: tuple[QWidget, ...] = ()

    def set_border_widgets(self, *widgets: QWidget) -> None:
        self._border_widgets = widgets
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._border_widgets:
            return
        heading = self._border_widgets[0]
        bounds = QRectF(self.rect()).adjusted(0.5, 0, -0.5, -0.5)
        bounds.setTop(heading.geometry().center().y() + 0.5)
        clip = QRegion(self.rect())
        for widget in self._border_widgets:
            clip -= QRegion(widget.geometry().adjusted(-4, 0, 4, 0))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME_COLORS["ui_button"]))
        painter.drawRoundedRect(bounds, 5, 5)
        painter.setClipRegion(clip)
        painter.setPen(QPen(QColor(THEME_COLORS["ui_border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bounds, 5, 5)


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
        active = self.underMouse() or self._drag_origin is not None
        center_y = self.height() / 2 + 0.5
        line_color = QColor(THEME_COLORS["ui_accent" if active else "ui_border"])
        if active:
            line_color.setAlpha(140)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line_color)
        painter.drawRect(QRectF(12, center_y - 0.5, self.width() - 24, 2))
        painter.setBrush(QColor(THEME_COLORS["ui_accent" if active else "ui_border_strong"]))
        painter.drawRoundedRect(QRectF((self.width() - 64) / 2, center_y - 1.5, 64, 4), 2, 2)


class DisplayControlsGroup(QFrame):
    def __init__(self, height_reference: QWidget, parent: QWidget) -> None:
        super().__init__(parent)
        self._height_reference = height_reference

    def sizeHint(self) -> QSize:  # noqa: N802
        size = super().sizeHint()
        size.setHeight(max(size.height(), self._height_reference.sizeHint().height()))
        return size


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
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        options = QWidget(self)
        options.setObjectName("optionsPage")
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(12, 4, 0, 4)
        options_layout.setSpacing(8)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        context_controls = QWidget(options)
        context_controls.setObjectName("contextControlsGroup")
        context_layout = QHBoxLayout(context_controls)
        context_layout.setContentsMargins(11, 0, 0, 0)
        context_layout.setSpacing(8)

        self._context_spin = ContextSpinBox()
        self._context_spin.setObjectName("contextSpin")
        self._context_spin.setFixedWidth(self.fontMetrics().horizontalAdvance("1 000") + 48)
        context_label = QLabel("Context around matches")
        context_label.setObjectName("contextLabel")
        context_layout.addWidget(context_label)
        context_layout.addWidget(self._context_spin)
        options_layout.addWidget(context_controls, 0, Qt.AlignmentFlag.AlignLeft)

        limit_controls = QWidget(options)
        limit_controls.setObjectName("limitControlsGroup")
        limit_layout = QHBoxLayout(limit_controls)
        limit_layout.setContentsMargins(11, 0, 0, 0)
        limit_layout.setSpacing(8)

        self._limit_spin = ScanLimitSpinBox()
        self._limit_spin.setObjectName("limitSpin")
        self._limit_spin.setFixedWidth(self.fontMetrics().horizontalAdvance("2 147 483 647") + 48)
        limit_label = QLabel("Max lines scanned")
        limit_label.setObjectName("limitLabel")
        limit_layout.addWidget(limit_label)
        limit_layout.addWidget(self._limit_spin)
        options_layout.addWidget(limit_controls, 0, Qt.AlignmentFlag.AlignLeft)

        display_controls = DisplayControlsGroup(self._context_spin, options)
        display_controls.setObjectName("displayControlsGroup")
        display_layout = QHBoxLayout(display_controls)
        display_layout.setContentsMargins(10, 4, 10, 4)
        display_layout.setSpacing(12)

        self._combined_view = VisibleCheckBox("Combined view")
        self._combined_view.setObjectName("combinedViewCheck")
        self._combined_view.setProperty("islandIndicator", True)
        self._combined_view.setChecked(True)
        self._combined_view.setToolTip(
            "Show all matches in one combined category on the results view."
        )
        display_layout.addWidget(self._combined_view)

        self._separate_entries = VisibleCheckBox("Line-spacing")
        self._separate_entries.setObjectName("separateEntriesCheck")
        self._separate_entries.setProperty("islandIndicator", True)
        self._separate_entries.setChecked(True)
        self._separate_entries.setToolTip(
            "Add a small gap as separation between mismatching context/errors in results."
        )
        display_layout.addWidget(self._separate_entries)
        options_layout.addWidget(display_controls, 0, Qt.AlignmentFlag.AlignLeft)

        self._filter_header = filter_header = QWidget(self)
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
        for title, total in (
            ("Common patterns", len(PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS)),
            ("Advanced patterns", len(ADVANCED_PATTERN_KEYS)),
            ("Text and Regex", None),
        ):
            index = self._tabs.addTab(title)
            count = QLabel(self._tabs)
            count.setObjectName("filterTabCount")
            count.setContentsMargins(0, 0, 8, 0)
            if total is not None:
                width = 0
                for selected in range(total + 1):
                    count.setText(f"({selected}/{total})")
                    width = max(width, count.sizeHint().width())
                count.setFixedWidth(width)
                count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, count)
            self._tab_counts.append(count)
        header_layout.addWidget(self._tabs)
        header_layout.addSpacing(5)
        self._tab_pattern_toggles = []
        for index, (keys, name, scope) in enumerate((
            (PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS, "toggleCommonButton", "common"),
            (ADVANCED_PATTERN_KEYS, "toggleAdvancedButton", "advanced"),
        )):
            button = self._build_pattern_toggle(keys, name)
            button.setToolTip(f"Select or clear all {scope} patterns.")
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance("Select all"))
            header_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            button.setVisible(index == self._tabs.currentIndex())
            self._tab_pattern_toggles.append(button)
        header_layout.addStretch(1)
        self._exclusions_label = QLabel()
        self._exclusions_label.setObjectName("filterExclusions")
        header_layout.addWidget(self._exclusions_label)
        actions = QWidget(filter_header)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(0)
        self._options_tab = QPushButton("Options", actions)
        self._options_tab.setObjectName("optionsTab")
        self._options_tab.setCheckable(True)
        configure_action_button(self._options_tab)
        self._options_tab.clicked.connect(lambda: self._select_editor(3))
        actions_layout.addWidget(self._options_tab)
        self._analyze_cell = QFrame(actions)
        self._analyze_cell.setObjectName("analyzeCell")
        analyze_layout = QHBoxLayout(self._analyze_cell)
        analyze_layout.setContentsMargins(0, 0, 0, 0)
        analyze_layout.setSpacing(0)
        actions_layout.addWidget(self._analyze_cell)
        header_layout.addWidget(actions)
        layout.addWidget(filter_header)
        layout.addSpacing(3)

        self._pages = FilterPages(self)
        self._pages.setObjectName("filterPages")
        self._pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        patterns = QWidget()
        patterns.setObjectName("commonPatternsPage")
        patterns_layout = QVBoxLayout(patterns)
        patterns_layout.setContentsMargins(12, 4, 0, 4)
        patterns_layout.setSpacing(10)
        pattern_groups = QHBoxLayout()
        pattern_groups.setSpacing(16)
        pattern_groups.addWidget(
            self._build_pattern_group(
                "Other matches",
                TEXT_PATTERN_KEYS,
                object_name="textPatternGroup",
                columns=4,
                toggle_object_name="toggleTextButton",
            ),
        )
        pattern_groups.addWidget(
            self._build_pattern_group(
                "Colon / regular matches",
                PAIRED_PATTERN_KEYS,
                object_name="pairedPatternGroup",
                columns=2,
                toggle_object_name="togglePairedButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        pattern_groups.addStretch(1)
        patterns_layout.addLayout(pattern_groups)
        self._pages.addWidget(patterns)
        advanced = QWidget()
        advanced.setObjectName("advancedPatternsPage")
        advanced_layout = QHBoxLayout(advanced)
        advanced_layout.setContentsMargins(12, 4, 0, 4)
        advanced_layout.setSpacing(12)
        advanced_layout.addWidget(
            self._build_pattern_group(
                "Network",
                ("connection_failures", "tls_certificates", "reachability_timeouts",
                 "http_4xx", "http_5xx"),
                object_name="networkPatternGroup",
                columns=1,
                toggle_object_name="toggleNetworkButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        advanced_layout.addWidget(
            self._build_pattern_group(
                "Application",
                APPLICATION_PATTERN_KEYS,
                object_name="applicationPatternGroup",
                columns=1,
                toggle_object_name="toggleApplicationButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        advanced_layout.addWidget(
            self._build_pattern_group(
                "Database",
                DATABASE_PATTERN_KEYS,
                object_name="databasePatternGroup",
                columns=1,
                toggle_object_name="toggleDatabaseButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        advanced_layout.addWidget(
            self._build_pattern_group(
                "System",
                SYSTEM_RUNTIME_PATTERN_KEYS,
                object_name="systemRuntimePatternGroup",
                columns=1,
                toggle_object_name="toggleSystemButton",
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        advanced_layout.addStretch(1)
        self._pages.addWidget(advanced)
        searches = QWidget()
        searches.setObjectName("customSearchesPage")
        searches_layout = QVBoxLayout(searches)
        searches_layout.setContentsMargins(12, 4, 0, 0)
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
        self._pages.addWidget(options)
        self._tabs.currentChanged.connect(self._select_editor)
        # The remembered pattern tab can be clicked again after visiting Options.
        self._tabs.tabBarClicked.connect(self._select_editor)
        pages_container = QWidget(self)
        pages_layout = QVBoxLayout(pages_container)
        pages_layout.setContentsMargins(0, 0, 12, 0)
        pages_layout.setSpacing(0)
        pages_layout.addWidget(self._pages)
        layout.addWidget(pages_container)
        layout.addStretch(1)

    def set_analysis_button(self, button: QPushButton) -> None:
        if button.parentWidget() is not self._analyze_cell:
            self._analyze_cell.layout().addWidget(button)
        button.show()

    def _select_editor(self, index: int) -> None:
        if index < 0:
            return
        self._pages.setCurrentIndex(index)
        options_active = index == 3
        self._options_tab.setChecked(options_active)
        if self._tabs.property("optionsActive") != options_active:
            self._tabs.setProperty("optionsActive", options_active)
            self._tabs.style().unpolish(self._tabs)
            self._tabs.style().polish(self._tabs)
            self._tabs.update()
        for tab_index, button in enumerate(self._tab_pattern_toggles):
            button.setVisible(tab_index == index)
        self._pages.updateGeometry()

    def _resize_search_lists(self, height: int) -> None:
        for pattern_list in (self._custom_pattern_list, self._regex_pattern_list):
            pattern_list.setFixedHeight(height)
        self._pages.updateGeometry()
        # Grow the containing layouts before another frame can paint compressed controls.
        layouts = []
        widget = self._pages.currentWidget()
        while widget is not None:
            if widget.layout() is not None:
                widget.layout().invalidate()
                layouts.append(widget.layout())
            widget = widget.parentWidget()
        for layout in reversed(layouts):
            layout.activate()

    def _update_summary(self) -> None:
        for index, keys in enumerate((PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS, ADVANCED_PATTERN_KEYS)):
            selected = sum(self._pattern_checkboxes[key].isChecked() for key in keys)
            self._set_tab_count(index, f"({selected}/{len(keys)})", f"{selected} of {len(keys)} selected")
        custom_count = self._custom_pattern_list.count()
        regex_count = self._regex_pattern_list.count()
        search_count = custom_count + regex_count
        enabled_items = (
            self._enabled_list_items(self._custom_pattern_list)
            + self._enabled_list_items(self._regex_pattern_list)
        )
        enabled_count = len(enabled_items)
        self._set_tab_count(2, f"({enabled_count}/{search_count})",
                            f"{enabled_count} of {search_count} searches enabled")
        excluded = sum(
            bool(item.data(EXCLUDE_ROLE)) for item in enabled_items
        )
        self._exclusions_label.setText(f"{excluded} exclusion{'s' if excluded != 1 else ''}")
        self._exclusions_label.setVisible(excluded > 0)
        for button, keys in self._bulk_buttons:
            verb = "Clear" if all(self._pattern_checkboxes[key].isChecked() for key in keys) else "Select"
            button.setText(verb + " all")

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
            presets=REGEX_PRESETS,
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
        presets: tuple[tuple[str, str], ...] = (),
    ) -> tuple[QGroupBox, QLineEdit, QListWidget]:
        group = BorderTitleGroupBox()
        group.setObjectName(group_object_name)
        group.setAccessibleName(title)
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 2, 12, 12)
        layout.setSpacing(8)
        # Keep controls anchored while a smaller list height propagates to its parents.
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        heading = QLabel(title)
        heading.setObjectName("filterSectionTitle")
        group.set_border_widgets(heading)
        header = QHBoxLayout()
        header.addWidget(heading, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        if presets:
            preset_button = QPushButton("Add preset")
            configure_action_button(preset_button)
            preset_button.setObjectName("regexPresetButton")
            preset_button.setProperty("patternGroupToggle", True)
            menu = QMenu(preset_button)
            menu.setObjectName("regexPresetMenu")
            for label, expression in presets:
                action = menu.addAction(label)
                action.setData(expression)
                action.triggered.connect(
                    lambda _checked=False, pattern=expression: self._add_regex_preset(pattern)
                )
            menu.aboutToShow.connect(lambda: self._update_regex_preset_menu(menu))
            preset_button.setMenu(menu)
            header.addWidget(preset_button, 0, Qt.AlignmentFlag.AlignVCenter)
            group.set_border_widgets(heading, preset_button)
        layout.addLayout(header)

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

    def _build_pattern_toggle(
        self, pattern_keys: tuple[str, ...], object_name: str,
    ) -> QPushButton:
        button = QPushButton("Select all")
        configure_action_button(button)
        button.setObjectName(object_name)
        button.setProperty("patternGroupToggle", True)
        button.clicked.connect(
            lambda _checked=False, keys=pattern_keys: self.toggle_patterns(keys)
        )
        self._bulk_buttons.append((button, pattern_keys))
        return button

    def _build_pattern_group(
        self,
        title: str,
        pattern_keys: tuple[str, ...],
        *,
        object_name: str,
        columns: int,
        toggle_object_name: str | None = None,
        rows_per_column: int | None = None,
    ) -> QGroupBox:
        group = BorderTitleGroupBox()
        group.setObjectName(object_name)
        group.setAccessibleName(title)
        group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        outer_layout = QVBoxLayout(group)
        outer_layout.setContentsMargins(12, 2, 12, 13)
        outer_layout.setSpacing(9)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        header = QHBoxLayout()
        header.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("filterSectionTitle")
        group.set_border_widgets(heading)
        header.addWidget(heading, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        if toggle_object_name is not None:
            toggle_button = self._build_pattern_toggle(pattern_keys, toggle_object_name)
            header.addWidget(toggle_button, 0, Qt.AlignmentFlag.AlignVCenter)
            group.set_border_widgets(heading, toggle_button)
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
            if rows_per_column is None:
                row, column = divmod(index, columns)
            else:
                column, row = divmod(index, rows_per_column)
            layout.addWidget(
                checkbox,
                row,
                column,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )

        for column in range(columns):
            column_checkboxes = (
                checkboxes if rows_per_column is None
                else checkboxes[column * rows_per_column:(column + 1) * rows_per_column]
            )
            layout.setColumnMinimumWidth(
                column, max((checkbox.sizeHint().width() for checkbox in column_checkboxes), default=0),
            )

        return group

    @staticmethod
    def _pattern_control_label(key: str) -> str:
        """Return a concise GUI label without changing result headings."""

        if key == "http_4xx":
            return "HTTP 4xx"
        if key == "http_5xx":
            return "HTTP 5xx"
        if key in ADVANCED_PATTERN_KEYS:
            return PATTERN_PRESETS_BY_KEY[key].label
        return PATTERN_PRESETS_BY_KEY[key].label.capitalize()

    def build_config(self) -> LogreaderConfig:
        """Build the shared configuration represented by the controls."""

        self._limit_spin.interpretText()
        custom_items = self._enabled_list_items(self._custom_pattern_list)
        regex_items = self._enabled_list_items(self._regex_pattern_list)
        return LogreaderConfig(
            context=self._context_spin.value(),
            max_lines_scanned=self._limit_spin.value(),
            enabled_patterns=tuple(
                key
                for key in PATTERN_KEYS
                if self._pattern_checkboxes[key].isChecked()
            ),
            custom_patterns=tuple(str(item.data(Qt.ItemDataRole.UserRole)) for item in custom_items),
            custom_pattern_match_case=tuple(
                bool(item.data(MATCH_CASE_ROLE)) for item in custom_items
            ),
            custom_pattern_exclude=tuple(
                bool(item.data(EXCLUDE_ROLE)) for item in custom_items
            ),
            custom_pattern_exclusive=tuple(
                bool(item.data(EXCLUSIVE_ROLE)) for item in custom_items
            ),
            regex_patterns=tuple(str(item.data(Qt.ItemDataRole.UserRole)) for item in regex_items),
            regex_pattern_match_case=tuple(
                bool(item.data(MATCH_CASE_ROLE)) for item in regex_items
            ),
            regex_pattern_exclude=tuple(
                bool(item.data(EXCLUDE_ROLE)) for item in regex_items
            ),
            regex_pattern_exclusive=tuple(
                bool(item.data(EXCLUSIVE_ROLE)) for item in regex_items
            ),
            separate_entries=self._separate_entries.isChecked(),
            combined_view=self._combined_view.isChecked(),
        )

    @staticmethod
    def _enabled_list_items(pattern_list: QListWidget) -> tuple[QListWidgetItem, ...]:
        return tuple(
            item for index in range(pattern_list.count())
            if not (item := pattern_list.item(index)).data(DISABLED_ROLE)
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
        *,
        pattern: str | None = None,
    ) -> None:
        from_draft = pattern is None
        if from_draft:
            pattern = input_box.text().strip()
        if not pattern:
            return

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, pattern)
        item.setData(EXCLUSIVE_ROLE, False)
        item.setData(EXCLUDE_ROLE, False)
        item.setData(MATCH_CASE_ROLE, False)
        item.setData(DISABLED_ROLE, False)
        item.setSizeHint(QSize(0, 18))
        pattern_list.addItem(item)
        self._set_search_list_item_widget(pattern_list, item, remove_button_object_name, remove_handler)

        if from_draft:
            input_box.clear()
        input_box.setFocus()
        self._update_summary()

    def _set_search_list_item_widget(
        self, pattern_list: QListWidget, item: QListWidgetItem,
        remove_button_object_name: str, remove_handler: Callable[[QListWidgetItem], None],
    ) -> None:
        pattern = str(item.data(Qt.ItemDataRole.UserRole))
        is_custom = pattern_list is self._custom_pattern_list
        preset_name = None if is_custom else REGEX_PRESET_NAMES.get(pattern)
        label = preset_name or pattern

        item_row = SearchPatternRow()
        item_row.setFixedHeight(18)
        item_layout = QHBoxLayout(item_row)
        item_layout.setContentsMargins(4, 0, 2, 0)
        item_layout.setSpacing(4)
        item_label = QLabel(label)
        item_label.setTextFormat(Qt.TextFormat.PlainText)
        item_label_font = item_label.font()
        item_label_font.setBold(False)
        item_label_font.setWeight(QFont.Weight.Normal)
        item_label.setFont(item_label_font)
        text_row = QWidget()
        text_layout = QHBoxLayout(text_row)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(item_label, 1)
        item_layout.addWidget(text_row)
        item_layout.addStretch(1)

        item_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        item_label.setMinimumWidth(1)
        item_label.setToolTip(pattern)
        if preset_name:
            preset_label = QLabel("(preset)")
            preset_label.setObjectName("regexPresetLabel")
            preset_label.setToolTip(pattern)
            text_layout.addWidget(preset_label)
        mode_label = QLabel()
        mode_label.setObjectName("patternModeLabel")
        text_layout.addWidget(mode_label)
        case_label = QLabel("(case)")
        case_label.setObjectName("patternCaseLabel")
        case_label.setStyleSheet(f"color: {THEME_COLORS['ui_muted']};")
        text_layout.addWidget(case_label)

        def update_mode(role: int | None, checked: bool) -> None:
            if role is None:
                item.setData(EXCLUSIVE_ROLE, False)
                role, checked = EXCLUDE_ROLE, False
            if checked and role in (EXCLUSIVE_ROLE, EXCLUDE_ROLE):
                item.setData(EXCLUDE_ROLE if role == EXCLUSIVE_ROLE else EXCLUSIVE_ROLE, False)
            item.setData(role, checked)
            disabled = bool(item.data(DISABLED_ROLE))
            exclusive = bool(item.data(EXCLUSIVE_ROLE))
            excluded = bool(item.data(EXCLUDE_ROLE))
            annotation = ("(disabled)" if disabled else "(exclusive)" if exclusive
                          else "(excluded)" if excluded else "")
            mode_label.setText(annotation)
            color = THEME_COLORS["ui_muted" if disabled else "ui_exclusive" if exclusive else "ui_excluded"]
            mode_label.setStyleSheet(f"color: {color};")
            mode_label.setToolTip("" if disabled else EXCLUSIVE_TOOLTIP if exclusive else EXCLUDE_TOOLTIP)
            mode_label.setVisible(bool(annotation))
            item_label.setStyleSheet(f"color: {THEME_COLORS['ui_muted']};" if disabled else "")
            if preset_name:
                preset_label.setVisible(not disabled)
            match_case = bool(item.data(MATCH_CASE_ROLE))
            case_label.setVisible(match_case)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, " ".join(
                part for part in (label, annotation, "(case)" if match_case else "") if part
            ))
            text_row.setMaximumWidth(
                item_label.sizeHint().width()
                + (preset_label.sizeHint().width() + 4 if preset_name and not disabled else 0)
                + (mode_label.sizeHint().width() + 4 if annotation else 0)
                + (case_label.sizeHint().width() + 4 if match_case else 0)
            )

        item_layout.addWidget(item_row.menu_button)

        def edit_pattern() -> None:
            dialog = PatternEditDialog(pattern, is_regex=not is_custom, parent=self)
            try:
                if dialog.exec() == QDialog.DialogCode.Accepted and dialog.pattern() != pattern:
                    item.setData(Qt.ItemDataRole.UserRole, dialog.pattern())
                    self._set_search_list_item_widget(
                        pattern_list, item, remove_button_object_name, remove_handler,
                    )
            finally:
                dialog.deleteLater()

        update_mode(EXCLUSIVE_ROLE, bool(item.data(EXCLUSIVE_ROLE)))
        item_row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        item_row.customContextMenuRequested.connect(
            lambda position: self._show_pattern_menu(item_row, item, position, update_mode, edit_pattern)
        )
        item_row.menu_button.setAccessibleName(f"Options for {label}")
        item_row.menu_button.clicked.connect(
            lambda: self._show_pattern_menu(
                item_row, item,
                item_row.menu_button.geometry().bottomLeft() + QPoint(0, 1), update_mode, edit_pattern,
            )
        )

        remove_button = item_row.remove_button
        remove_button.setObjectName(remove_button_object_name)
        remove_button.setAccessibleName(f"Remove {label}")
        remove_button.setToolTip(f"Remove {label}")
        remove_button.setFixedSize(24, 16)
        remove_button.clicked.connect(
            lambda _checked=False, list_item=item: remove_handler(list_item)
        )
        item_layout.addWidget(remove_button)
        pattern_list.setItemWidget(item, item_row)

    def _show_pattern_menu(
        self, row: SearchPatternRow, item: QListWidgetItem, position: QPoint,
        update_mode: Callable[[int | None, bool], None],
        edit_pattern: Callable[[], None],
    ) -> None:
        menu = SearchPatternMenu(row)
        disabled = bool(item.data(DISABLED_ROLE))
        modes = QActionGroup(menu)
        for label, role, tooltip in (
            ("Normal", None, ""),
            ("Exclusive", EXCLUSIVE_ROLE, EXCLUSIVE_TOOLTIP),
            ("Exclude", EXCLUDE_ROLE, EXCLUDE_TOOLTIP),
        ):
            action = menu.addAction(label)
            modes.addAction(action)
            action.setData(role)
            action.setCheckable(True)
            action.setChecked(bool(item.data(role)) if role is not None else not (
                item.data(EXCLUSIVE_ROLE) or item.data(EXCLUDE_ROLE)
            ))
            action.setEnabled(not disabled)
            action.setToolTip(tooltip)
        modes.triggered.connect(lambda action: update_mode(action.data(), True))
        menu.addSeparator()
        case_action = menu.addAction("Case sensitive")
        case_action.setObjectName("caseSensitive")
        case_action.setCheckable(True)
        case_action.setChecked(bool(item.data(MATCH_CASE_ROLE)))
        case_action.setEnabled(not disabled)
        case_action.toggled.connect(lambda checked: update_mode(MATCH_CASE_ROLE, checked))
        menu.addSeparator()
        edit_requested = False

        def request_edit() -> None:
            nonlocal edit_requested
            edit_requested = True

        edit_action = menu.addAction("Edit…")
        edit_action.setObjectName("editPattern")
        edit_action.triggered.connect(request_edit)
        enabled_action = menu.addAction("Enable" if disabled else "Disable")
        enabled_action.setObjectName("enablePattern" if disabled else "disablePattern")

        def toggle_enabled() -> None:
            disabled = not bool(item.data(DISABLED_ROLE))
            update_mode(DISABLED_ROLE, disabled)
            for action in (*modes.actions(), case_action):
                action.setEnabled(not disabled)
            enabled_action.setText("Enable" if disabled else "Disable")
            enabled_action.setObjectName("enablePattern" if disabled else "disablePattern")

        enabled_action.triggered.connect(toggle_enabled)
        row.set_context_target(True)
        try:
            menu.exec(row.mapToGlobal(position))
        finally:
            row.set_context_target(False)
            menu.deleteLater()
        if edit_requested:
            edit_pattern()

    def _update_regex_preset_menu(self, menu: QMenu) -> None:
        expressions = set(self._list_values(self._regex_pattern_list))
        for action in menu.actions():
            action.setEnabled(action.data() not in expressions)

    def _add_regex_preset(self, pattern: str) -> None:
        if pattern in self._list_values(self._regex_pattern_list):
            return
        self._add_search_list_item(
            self._regex_pattern,
            self._regex_pattern_list,
            "regexPatternRemoveButton",
            self.remove_regex_pattern,
            pattern=pattern,
        )

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
        QTimer.singleShot(0, pattern_list, lambda: self._refresh_search_list_hover(pattern_list))

    @staticmethod
    def _refresh_search_list_hover(pattern_list: QListWidget) -> None:
        # Deletion moves rows under a stationary pointer without a new enter event.
        pattern_list.doItemsLayout()
        position = QCursor.pos()
        target = QApplication.widgetAt(position)
        for index in range(pattern_list.count()):
            row = pattern_list.itemWidget(pattern_list.item(index))
            row._hovered = target is row or (target is not None and row.isAncestorOf(target))
            row._update_hover()
        # Newly revealed buttons also need their hit-test hover state refreshed.
        target = QApplication.widgetAt(position)
        if isinstance(target, QPushButton) and pattern_list.isAncestorOf(target):
            QApplication.sendEvent(target, QMouseEvent(
                QEvent.Type.MouseMove, QPointF(target.mapFromGlobal(position)),
                QPointF(target.window().mapFromGlobal(position)), QPointF(position),
                Qt.MouseButton.NoButton, QApplication.mouseButtons(), QApplication.keyboardModifiers(),
            ))

    def toggle_patterns(self, pattern_keys: tuple[str, ...]) -> None:
        """Toggle every checkbox in one pattern category as a unit."""

        enable_all = not all(
            self._pattern_checkboxes[key].isChecked() for key in pattern_keys
        )
        for key in pattern_keys:
            self._pattern_checkboxes[key].setChecked(enable_all)
