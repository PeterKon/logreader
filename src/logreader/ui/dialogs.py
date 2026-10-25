from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizeGrip, QVBoxLayout, QWidget,
)

from .app_icon import application_icon
from .theme import THEME_COLORS as C


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


class CompactDialog(QDialog):
    def __init__(self, title, parent=None, *, resizable=False):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setWindowIcon(application_icon())
        font = self.font()
        font.setPointSizeF(max(10, font.pointSizeF()))
        self.setFont(font)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(COMPACT_DIALOG_STYLE)
        self._resizable = resizable
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
        self.caption.setFixedHeight(36)
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
        self.close_button.setFixedSize(46, 35)
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
        self.grip = QSizeGrip(self) if resizable else None
        for widget in (self, self.frame, self.caption):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

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
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = Qt.Edge(0)
            if self._resizable:
                if point.x() < 5:
                    edges |= Qt.Edge.LeftEdge
                elif point.x() >= self.width() - 5:
                    edges |= Qt.Edge.RightEdge
                if point.y() < 5:
                    edges |= Qt.Edge.TopEdge
                elif point.y() >= self.height() - 5:
                    edges |= Qt.Edge.BottomEdge
            horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
            vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
            cursor = Qt.CursorShape.ArrowCursor
            if horizontal and vertical:
                cursor = (Qt.CursorShape.SizeFDiagCursor if edges in (
                    Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
                ) else Qt.CursorShape.SizeBDiagCursor)
            elif horizontal:
                cursor = Qt.CursorShape.SizeHorCursor
            elif vertical:
                cursor = Qt.CursorShape.SizeVerCursor
            watched.setCursor(cursor)
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                handle = self.windowHandle()
                if handle is not None:
                    if edges:
                        return handle.startSystemResize(edges)
                    if watched is self.caption:
                        return handle.startSystemMove()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.grip is not None:
            self.grip.setGeometry(self.width() - 13, self.height() - 13, 12, 12)
            self.grip.raise_()


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
