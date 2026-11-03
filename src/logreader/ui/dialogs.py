from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSizeGrip, QStyle, QVBoxLayout, QWidget,
)

from .app_icon import application_icon
from .theme import THEME_COLORS as C
from .widgets.input_menus import InputContextMenu
from .widgets.menu_style import MenuTheme


COMPACT_DIALOG_STYLE = f"""
QDialog {{ background: transparent; color: {C['ui_text']}; }}
QFrame#compactDialogFrame {{
    background: {C['ui_canvas']}; border: 1px solid {C['ui_border_strong']};
    border-radius: 5px;
}}
QWidget#compactDialogCaption {{
    background: {C['ui_caption']}; border-bottom: 1px solid {C['ui_border']};
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}}
QLabel {{ color: {C['ui_text']}; background: transparent; border: none; }}
QLabel#compactDialogTitle {{ font-weight: 600; }}
QLabel[secondary="true"] {{ color: {C['ui_muted']}; }}
QLineEdit, QPlainTextEdit {{
    color: {C['ui_text']}; background: #131c26;
    border: 1px solid {C['ui_border_strong']}; border-radius: 4px;
    padding: 8px 10px; selection-background-color: {C['selection']};
    selection-color: {C['ui_text']};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {C['ui_border_strong']}; }}
QPushButton {{
    color: {C['ui_text']}; background: {C['ui_button']};
    border: 1px solid {C['ui_border_strong']}; border-radius: 5px;
    min-width: 58px; min-height: 18px; padding: 7px 10px;
}}
QPushButton:hover {{ background: {C['ui_button_hover']}; }}
QPushButton:pressed {{ background: {C['ui_button_pressed']}; }}
QPushButton:focus {{ border-color: {C['ui_border_strong']}; }}
QPushButton[primary="true"] {{ background: {C['ui_primary']}; border-color: {C['ui_primary']}; color: #ffffff; }}
QPushButton[primary="true"]:hover {{ background: {C['ui_primary_hover']}; }}
QPushButton[destructive="true"] {{ background: #a52e35; border-color: #a52e35; color: #ffffff; }}
QPushButton[destructive="true"]:hover {{ background: #bd353b; }}
QPushButton[primary="true"]:focus {{ border-color: {C['ui_primary']}; }}
QPushButton[destructive="true"]:focus {{ border-color: #a52e35; }}
QPushButton#compactDialogClose {{
    background: transparent; border: none; border-radius: 0;
    border-top-right-radius: 4px; min-width: 0; min-height: 0; padding: 0;
}}
QPushButton#compactDialogClose:hover {{ background: #bd353b; }}
QPushButton#compactDialogClose:focus {{ border: none; }}
QDialogButtonBox {{ button-layout: 3; }}
QScrollBar:vertical {{ background: #19232f; width: 12px; margin: 2px; border: none; }}
QScrollBar::handle:vertical {{ background: #718297; min-height: 24px; border-radius: 3px; }}
QScrollBar::handle:vertical:hover {{ background: #98a8ba; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


class DialogCloseButton(QPushButton):
    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().buttonText().color(), 1.2))
        center = self.rect().center()
        painter.drawLine(center.x() - 4, center.y() - 4, center.x() + 4, center.y() + 4)
        painter.drawLine(center.x() + 4, center.y() - 4, center.x() - 4, center.y() + 4)


class _ResizeHandle(QWidget):
    def __init__(self, dialog, edges, cursor):
        super().__init__(dialog)
        self.edges = edges
        self.setCursor(cursor)

    def fit_border(self, width, height):
        border = 5
        x, w = border, width - 2 * border
        y, h = border, height - 2 * border
        if self.edges & Qt.Edge.LeftEdge:
            x, w = 0, border
        elif self.edges & Qt.Edge.RightEdge:
            x, w = width - border, border
        if self.edges & Qt.Edge.TopEdge:
            y, h = 0, border
        elif self.edges & Qt.Edge.BottomEdge:
            y, h = height - border, border
        self.setGeometry(x, y, w, h)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle().startSystemResize(self.edges):
            event.accept()
            return
        super().mousePressEvent(event)


class CompactDialog(QDialog):
    def __init__(self, title, parent=None, *, resizable=False):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._menu_theme = MenuTheme(self)
        self.setWindowTitle(title)
        self.setWindowIcon(application_icon())
        font = self.font()
        font.setPointSizeF(max(10, font.pointSizeF()))
        self.setFont(font)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(COMPACT_DIALOG_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(self)
        self.frame.setObjectName("compactDialogFrame")
        root.addWidget(self.frame)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(1, 1, 1, 1)
        frame_layout.setSpacing(0)
        self.caption = QWidget(self.frame)
        self.caption.setObjectName("compactDialogCaption")
        self.caption.setFixedHeight(self.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight, None, self))
        caption_layout = QHBoxLayout(self.caption)
        caption_layout.setContentsMargins(12, 0, 0, 0)
        caption_layout.setSpacing(8)
        icon = QLabel(self.caption)
        icon.setPixmap(self.windowIcon().pixmap(16, 16))
        caption_layout.addWidget(icon)
        self.title_label = QLabel(title, self.caption)
        self.title_label.setObjectName("compactDialogTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        caption_layout.addWidget(self.title_label, 1)
        self.windowTitleChanged.connect(self.title_label.setText)
        for label in (icon, self.title_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.close_button = DialogCloseButton(self.caption)
        self.close_button.setObjectName("compactDialogClose")
        self.close_button.setAccessibleName("Close")
        self.close_button.setFixedSize(46, self.caption.height() - 1)
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        caption_layout.addWidget(self.close_button)
        frame_layout.addWidget(self.caption)
        body = QWidget(self.frame)
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(14, 14, 14, 14)
        self.body_layout.setSpacing(12)
        frame_layout.addWidget(body, 1)
        self.buttons = QDialogButtonBox(self.frame)
        self.buttons.setContentsMargins(14, 0, 14, 14)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        frame_layout.addWidget(self.buttons)
        self._resize_handles = []
        if resizable:
            left, right = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
            top, bottom = Qt.Edge.TopEdge, Qt.Edge.BottomEdge
            shape = Qt.CursorShape
            self._resize_handles = [_ResizeHandle(self, edges, cursor) for edges, cursor in (
                (left, shape.SizeHorCursor), (right, shape.SizeHorCursor),
                (top, shape.SizeVerCursor), (bottom, shape.SizeVerCursor),
                (top | left, shape.SizeFDiagCursor), (bottom | right, shape.SizeFDiagCursor),
                (top | right, shape.SizeBDiagCursor), (bottom | left, shape.SizeBDiagCursor),
            )]
        self.grip = QSizeGrip(self) if resizable else None
        self.caption.installEventFilter(self)

    def set_buttons(self, buttons, *, default, destructive=None):
        self.buttons.setStandardButtons(buttons)
        for button in self.buttons.buttons():
            button.setAutoDefault(False)
            standard = self.buttons.standardButton(button)
            button.setProperty("primary", standard == default and destructive is None)
            button.setProperty("destructive", standard == destructive)
            button.style().unpolish(button)
            button.style().polish(button)
        self.buttons.button(default).setDefault(True)

    def fit_content(self):
        self.ensurePolished()
        layout = self.layout()
        height = layout.totalHeightForWidth(self.width())
        self.resize(self.width(), height if height >= 0 else layout.sizeHint().height())

    def eventFilter(self, watched, event):  # noqa: N802
        if (watched is self.caption and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            handle = self.windowHandle()
            if handle is not None:
                return handle.startSystemMove()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        for handle in self._resize_handles:
            handle.fit_border(self.width(), self.height())
        if self.grip is not None:
            self.grip.setGeometry(self.width() - 13, self.height() - 13, 12, 12)
            self.grip.raise_()


class NameDialog(CompactDialog):
    def __init__(
        self, parent: QWidget, title: str, subject: str, save: Callable[[str], bool | None], *, initial_name: str = "",
        allow_empty: bool = False,
    ) -> None:
        super().__init__(title, parent)
        self._subject = subject
        self._save = save
        self._allow_empty = allow_empty
        self.setObjectName(f"{subject}NameDialog")
        self.setFixedWidth(420)
        self.body_layout.setContentsMargins(14, 12, 14, 12)
        self.buttons.setContentsMargins(14, 0, 14, 12)
        self.name_input = QLineEdit()
        self.name_input.setObjectName(f"{subject}NameInput")
        self.name_input.setAccessibleName(f"{subject.capitalize()} name")
        InputContextMenu(self.name_input, undo=True, redo=True, cut=True)
        label = QLabel("Name")
        label.setBuddy(self.name_input)
        self.body_layout.addWidget(label)
        self.body_layout.addWidget(self.name_input)
        self.error_label = QLabel()
        self.error_label.setObjectName(f"{subject}NameError")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {C['ui_excluded']};")
        self.error_label.hide()
        self.body_layout.addWidget(self.error_label)
        self.set_buttons(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            default=QDialogButtonBox.StandardButton.Save,
        )
        self.fit_content()
        if initial_name:
            self.name_input.setText(initial_name)
            self.name_input.selectAll()
        self.name_input.setFocus()

    def accept(self) -> None:
        try:
            name = self.name_input.text().strip()
            if not name and not self._allow_empty:
                raise ValueError(f"Enter a {self._subject} name.")
            if self._save(name) is False:
                return
        except (ValueError, OSError) as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            self.fit_content()
            self.name_input.setFocus()
            return
        super().accept()


def show_warning(parent, title, message):
    dialog = CompactDialog(title, parent)
    dialog.setFixedWidth(480)
    dialog.body_layout.setContentsMargins(14, 12, 14, 12)
    dialog.buttons.setContentsMargins(14, 0, 14, 12)
    label = QLabel(message, dialog)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    dialog.body_layout.addWidget(label)
    dialog.set_buttons(QDialogButtonBox.StandardButton.Ok, default=QDialogButtonBox.StandardButton.Ok)
    dialog.fit_content()
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
