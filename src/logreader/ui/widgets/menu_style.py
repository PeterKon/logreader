from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from ..theme import THEME_COLORS, paint_checkmark
from ..title_bar import TITLE_MENU_STYLE_SHEET, TitleMenu
from ..window_frame import apply_menu_corners


CONTEXT_MENU_STYLE_SHEET = TITLE_MENU_STYLE_SHEET + """
    QMenu { min-width: 0; }
    QMenu::item { min-width: 160px; }
"""

_TEXT_ACTIONS = {"edit-undo", "edit-redo", "edit-cut", "edit-copy", "edit-paste",
                 "edit-delete", "select-all"}


def _tint_text_action_icons(menu: QMenu) -> None:
    for action in menu.actions():
        original = action.icon()
        if action.objectName() not in _TEXT_ACTIONS or original.isNull():
            continue
        icon = QIcon()
        for size in original.availableSizes():
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected,
                         QIcon.Mode.Disabled):
                pixmap = original.pixmap(size, 1.0, QIcon.Mode.Normal)
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                color = THEME_COLORS["ui_muted"] if mode == QIcon.Mode.Disabled else "#ffffff"
                painter.fillRect(pixmap.rect(), QColor(color))
                painter.end()
                icon.addPixmap(pixmap, mode)
        if not icon.isNull():
            action.setIcon(icon)


def style_menu(menu: QMenu) -> None:
    if menu.property("contextMenuStyled") or isinstance(menu, TitleMenu):
        return
    menu.setProperty("contextMenuStyled", True)
    menu.setStyleSheet(CONTEXT_MENU_STYLE_SHEET + (
        "QMenu { menu-scrollable: 1; }" if menu.objectName() == "regexPresetMenu" else ""
    ))
    menu.installEventFilter(_MenuAppearance(menu))


class _MenuAppearance(QObject):
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show:
            _tint_text_action_icons(watched)
            apply_menu_corners(watched)
        return False


class MenuTheme(QObject):
    """Include menus created internally by Qt editors, labels and scrollbars."""

    def __init__(self, root) -> None:
        super().__init__(root)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Polish and isinstance(watched, QMenu):
            # QWidget.isAncestorOf stops at popup windows. Follow QObject
            # ownership so Qt-generated menus retain their editor's scope.
            owner = watched.parent()
            while owner is not None:
                if owner is self.parent():
                    style_menu(watched)
                    break
                owner = owner.parent()
        return False


def style_checkbox_menu(menu: QMenu, action) -> None:
    style_menu(menu)
    menu.setStyleSheet(CONTEXT_MENU_STYLE_SHEET + """
        QMenu::item { padding: 5px 34px 5px 10px; }
        QMenu::indicator { width: 0; height: 0; }
    """)
    _MenuCheckbox(menu, action)


class _MenuCheckbox(QWidget):
    """Draw the trailing checkbox without reserving Qt's leading icon column."""

    def __init__(self, menu, action):
        super().__init__(menu)
        self.action = action
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        action.changed.connect(self.update)
        menu.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest,
                            QEvent.Type.ActionChanged):
            bounds = watched.actionGeometry(self.action)
            self.setGeometry(bounds.right() - 25, bounds.center().y() - 7, 16, 16)
            self.setVisible(self.action.isVisible() and not bounds.isEmpty())
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        enabled = self.action.isEnabled()
        color = THEME_COLORS["ui_disabled_text" if not enabled else
                             "ui_accent" if self.action.isChecked() else "ui_muted"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(1, 1)
        painter.setPen(QPen(QColor(color), 1.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 12, 12), 2, 2)
        if self.action.isChecked():
            paint_checkmark(painter, QRectF(0, 0, 14, 14), enabled=enabled)
