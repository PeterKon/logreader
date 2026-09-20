"""Session bookmarks identified by source location, with a shared navigation strip."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QHoverEvent, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QPlainTextEdit, QProxyStyle, QPushButton, QStyle, QStyleFactory,
    QStyleOptionMenuItem, QTabBar, QToolTip,
    QVBoxLayout, QWidget,
)

from .input_menus import InputContextMenu
from .results_model import ResultLocation, SourceLocation
from .theme import THEME_COLORS, configure_action_button

if TYPE_CHECKING:
    from .results_view import ResultsView


BOOKMARK_MENU_HOVER_COLOR = "#b8d8f5"


def _conversion_toggle_icon() -> QIcon:
    icon = QIcon()
    for checked in (False, True):
        border = "#404040" if checked else "#707070"
        background = "#f0f0f0" if checked else "#ffffff"
        for scale in (1, 2, 3):
            pixmap = QPixmap(16 * scale, 16 * scale)
            pixmap.setDevicePixelRatio(scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(border), 1))
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 15, 15), 3, 3)
            if checked:
                painter.setPen(QPen(QColor("#202b38"), 2, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(QPointF(3.5, 8), QPointF(6.5, 11.5))
                painter.drawLine(QPointF(6.5, 11.5), QPointF(12, 3.5))
            painter.end()
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active):
                icon.addPixmap(pixmap, mode, QIcon.State.On if checked else QIcon.State.Off)
    return icon


class BookmarkMenuStyle(QProxyStyle):
    def sizeFromContents(self, content_type, option, size, widget=None):  # noqa: N802
        size = super().sizeFromContents(content_type, option, size, widget)
        if (content_type == QStyle.ContentsType.CT_MenuItem
                and option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator):
            size.setHeight(7)
        return size

    def drawControl(self, element, option, painter, widget=None) -> None:  # noqa: N802
        if (element == QStyle.ControlElement.CE_MenuItem
                and option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator):
            painter.fillRect(option.rect.left(), option.rect.center().y(),
                             option.rect.width(), 1, QColor("#cccccc"))
            return
        if (element == QStyle.ControlElement.CE_MenuItem
                and option.state & QStyle.StateFlag.State_Selected):
            # Replace the hover fill while retaining native text and spacing.
            option = QStyleOptionMenuItem(option)
            option.state &= ~QStyle.StateFlag.State_Selected
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BOOKMARK_MENU_HOVER_COLOR))
            painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 4, 4)
            painter.restore()
        super().drawControl(element, option, painter, widget)


BOOKMARK_DIALOG_STYLE_SHEET = (
    f"QDialog {{ background: {THEME_COLORS['ui_surface']}; }}"
    f"QLabel {{ color: {THEME_COLORS['ui_text']}; }}"
    "QPlainTextEdit#bookmarkNoteEditor {"
    f" color: {THEME_COLORS['ui_text']}; background: {THEME_COLORS['background']};"
    f" border: 1px solid {THEME_COLORS['ui_border_strong']}; border-radius: 4px; padding: 6px;"
    f" selection-background-color: {THEME_COLORS['selection']}; }}"
    "QPlainTextEdit#bookmarkNoteEditor:focus {"
    f" border-color: {THEME_COLORS['ui_accent']}; }}"
    "QPushButton {"
    f" color: {THEME_COLORS['ui_text']}; background: {THEME_COLORS['ui_button']};"
    f" border: 1px solid {THEME_COLORS['ui_border_strong']}; border-radius: 5px;"
    " min-width: 64px; padding: 4px 10px; }"
    f"QPushButton:hover {{ background: {THEME_COLORS['ui_button_hover']}; }}"
    f"QPushButton:focus {{ border-color: {THEME_COLORS['ui_accent']}; }}"
    f"QPushButton:pressed {{ background: {THEME_COLORS['ui_button_pressed']}; }}"
)


@dataclass(slots=True)
class Bookmark:
    location: ResultLocation | SourceLocation
    name: str
    converted: bool = False
    convert_when_shown: bool = False
    note: str = ""

    @property
    def source_only(self) -> bool:
        return isinstance(self.location, SourceLocation) or self.converted

    @property
    def note_preview(self) -> str:
        preview = " ".join(self.note.split())
        if len(preview) <= 160:
            return preview
        shortened = preview[:159]
        if not (shortened[-1].isspace() or preview[159].isspace()):
            boundary = shortened.rfind(" ")
            if boundary >= 80:
                shortened = shortened[:boundary]
        return shortened.rstrip() + "…"


class BookmarkNoteIcon(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(17, 12)
        self.setAccessibleName("Has note")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.color = QColor(THEME_COLORS["bookmark_note"])

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        note = QPainterPath()
        note.setFillRule(Qt.FillRule.OddEvenFill)
        note.moveTo(2.5, 0)
        note.lineTo(10.5, 0)
        note.quadTo(12, 0, 12, 1.5)
        note.lineTo(12, 7)
        note.lineTo(8, 7)
        note.lineTo(8, 11)
        note.lineTo(2.5, 11)
        note.quadTo(1, 11, 1, 9.5)
        note.lineTo(1, 1.5)
        note.quadTo(1, 0, 2.5, 0)
        note.closeSubpath()
        note.moveTo(9, 8)
        note.lineTo(12, 8)
        note.lineTo(9, 11)
        note.closeSubpath()
        for y, width in ((3, 7), (5, 5)):
            note.addRect(QRectF(3, y, width, 1))
        painter.fillPath(note, self.color)
        painter.end()


class BookmarkNotesDialog(QDialog):
    def __init__(self, bookmark: Bookmark, source: SourceLocation, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("bookmarkNotesDialog")
        self.setWindowTitle("Bookmark note")
        self.resize(480, 320)
        self.setMinimumSize(360, 240)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(BOOKMARK_DIALOG_STYLE_SHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        line = f"Line {source.line:,}"
        heading = QLabel(line if bookmark.name == line else f"{bookmark.name}\n{line}")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName("bookmarkNoteEditor")
        self.editor.setAccessibleName("Bookmark note")
        self.editor.setPlaceholderText("Write a note…")
        self.editor.setTabChangesFocus(True)
        self.editor.setPlainText(bookmark.note)
        layout.addWidget(self.editor, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.editor.setFocus()


class BookmarkDeletionDialog(QDialog):
    def __init__(self, bookmark: Bookmark, source: SourceLocation, parent=None, *, note_only=False) -> None:
        super().__init__(parent)
        title = "Delete note" if note_only else "Delete bookmark"
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self.setStyleSheet(BOOKMARK_DIALOG_STYLE_SHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.heading = QLabel(f"{title}?", self)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)

        line = f"Line {source.line:,}"
        target = line if bookmark.name == line else f"{bookmark.name} ({line})"
        self.target = QLabel(target, self)
        self.target.setStyleSheet(f"color: {THEME_COLORS['ui_muted']};")
        layout.addWidget(self.target)

        message = "This will delete the note." if note_only else (
            "This will remove the bookmark and delete its note." if bookmark.note
            else "This will remove the bookmark.")
        self.message = QLabel(message, self)
        layout.addWidget(self.message)
        for label in (self.heading, self.target, self.message):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setWordWrap(True)

        layout.addSpacing(6)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No, self)
        self.buttons.button(QDialogButtonBox.StandardButton.Yes).clicked.connect(self.accept)
        no = self.buttons.button(QDialogButtonBox.StandardButton.No)
        no.clicked.connect(self.reject)
        no.setDefault(True)
        no.setFocus()
        layout.addWidget(self.buttons)
        self.ensurePolished()
        self.resize(self.width(), layout.totalHeightForWidth(self.width()))


class BookmarkStrip(QTabBar):
    activated = Signal(object)
    rename_requested = Signal(object)
    remove_requested = Signal(object)
    menu_requested = Signal(object, object)

    def __init__(self, parent=None) -> None:
        self._pressed_index = -1
        self._tooltip_source = None
        super().__init__(parent)
        self.setObjectName("bookmarkStrip")
        self.setAccessibleName("Bookmarks")
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setDrawBase(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(
            f"QTabBar#bookmarkStrip {{ background: {THEME_COLORS['background']}; }}"
            "QTabBar#bookmarkStrip::tab {"
            f" background: {THEME_COLORS['background']};"
            f" border: 1px solid {THEME_COLORS['bookmark_border']};"
            " border-top: 0; border-left: 0; border-radius: 0;"
            " padding: 4px 10px 3px; margin: 0; max-width: 200px; }"
            "QTabBar#bookmarkStrip::tab:hover {"
            f" background: {THEME_COLORS['bookmark_hover']}; }}"
            "QTabBar#bookmarkStrip::tab:pressed {"
            f" background: {THEME_COLORS['bookmark_pressed']}; }}"
            "QTabBar#bookmarkStrip::tab:disabled {"
            f" color: {THEME_COLORS['muted']}; }}"
            "QTabBar#bookmarkStrip QToolButton {"
            f" color: {THEME_COLORS['bookmark_marker']};"
            f" background: {THEME_COLORS['background']};"
            f" border: 1px solid {THEME_COLORS['bookmark_border']};"
            " border-top: 0; border-left: 0; border-radius: 0; }"
            "QTabBar#bookmarkStrip QToolButton:hover {"
            f" background: {THEME_COLORS['bookmark_hover']}; }}"
            "QTabBar#bookmarkStrip QToolButton:pressed {"
            f" background: {THEME_COLORS['bookmark_pressed']}; }}"
        )
        # currentChanged alone would not navigate when clicking the same tab again.
        self.tabBarClicked.connect(self._activate)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        visible_tabs = [index for index in range(self.count()) if self.isTabVisible(index)]
        # Stop dividers and the right edge above the bottom border instead of
        # letting Qt blend the colors into diagonal joins at their feet.
        for index in visible_tabs:
            rect = self.tabRect(index)
            painter.fillRect(rect.right(), rect.top(), 1, rect.height() - 1,
                             QColor(THEME_COLORS['bookmark_divider']))
        painter.end()

    def initStyleOption(self, option, index: int) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        # Keep the current tab for keyboard navigation, without a sticky highlight.
        option.state &= ~QStyle.StateFlag.State_Selected
        if (index == self._pressed_index and self.isTabEnabled(index)
                and option.state & QStyle.StateFlag.State_MouseOver
                and QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            option.state |= QStyle.StateFlag.State_Sunken

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # QTabBar emits tabBarClicked for right-clicks as well as left-clicks.
        # Let context-menu events handle other buttons without activating a tab.
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return
        self._pressed_index = self.tabAt(event.position().toPoint())
        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed_index = -1
        super().mouseReleaseEvent(event)
        self.update()
        source = self._tooltip_source
        self._tooltip_source = None
        if source is not None and self.tabData(self.tabAt(event.position().toPoint())) == source:
            self.show_tooltip(source)

    def show_tooltip(self, source: SourceLocation) -> None:
        # Qt dismisses tooltips on mouse release, so wait until the click ends.
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self._tooltip_source = source
            return
        for index in range(self.count()):
            if self.tabData(index) == source:
                rect = self.tabRect(index)
                QToolTip.showText(self.mapToGlobal(rect.bottomLeft()), self.tabToolTip(index), self, rect)
                break

    def _activate(self, index: int) -> None:
        if index >= 0 and self.isTabEnabled(index):
            self.activated.emit(self.tabData(index))

    def set_note_icon(self, index: int, has_note: bool) -> None:
        icon = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if has_note:
            if icon is None:
                icon = BookmarkNoteIcon(self)
                self.setTabButton(index, QTabBar.ButtonPosition.RightSide, icon)
            icon.color = QColor(THEME_COLORS["bookmark_note"] if self.isTabEnabled(index)
                                else THEME_COLORS["muted"])
            icon.update()
        elif icon is not None:
            self.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
            icon.deleteLater()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)

    def _context_menu(self, point) -> None:
        index = self.tabAt(point)
        if index < 0:
            return
        source = self.tabData(index)
        menu = QMenu(self)
        menu.addAction("Rename bookmark", lambda: self.rename_requested.emit(source))
        menu.addAction("Delete bookmark", lambda: self.remove_requested.emit(source))
        self.menu_requested.emit(menu, source)
        menu.exec(self.mapToGlobal(point))
        menu.deleteLater()
        # Popup menus can swallow hover-leave events while the pointer moves away.
        position = self.mapFromGlobal(QCursor.pos())
        event_type = QEvent.Type.HoverMove if self.rect().contains(position) else QEvent.Type.HoverLeave
        QApplication.sendEvent(self, QHoverEvent(event_type, QPointF(position),
                                                QPointF(QCursor.pos()), QPointF(point)))
        self._pressed_index = -1
        self.update()


class ResultsBookmarks(QObject):
    def __init__(self, view: ResultsView) -> None:
        super().__init__(view)
        self.view = view
        self.items: dict[SourceLocation, Bookmark] = {}
        self.bar = QWidget(view)
        self.bar.setObjectName("bookmarkBar")
        self.bar.setStyleSheet(f"QWidget#bookmarkBar {{ background: {THEME_COLORS['background']}; }}")
        layout = QHBoxLayout(self.bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.strip = BookmarkStrip(self.bar)
        layout.addWidget(self.strip, 1)
        self.reorder_button = QPushButton("Reorder", self.bar)
        self.reorder_button.setObjectName("reorderBookmarks")
        self.reorder_button.setToolTip("Sort bookmarks by the order they appear in source.")
        configure_action_button(self.reorder_button)
        self.reorder_button.setStyleSheet(
            "QPushButton#reorderBookmarks {"
            f" color: {THEME_COLORS['bookmark_text']}; background: {THEME_COLORS['background']};"
            f" border: 1px solid {THEME_COLORS['bookmark_border']};"
            " border-radius: 5px; min-height: 0; padding: 1px 8px; margin: 2px 4px 2px 6px; }"
            "QPushButton#reorderBookmarks:hover {"
            f" background: {THEME_COLORS['bookmark_hover']}; }}"
            "QPushButton#reorderBookmarks:focus {"
            f" border-color: {THEME_COLORS['bookmark_text']}; }}"
            "QPushButton#reorderBookmarks:pressed {"
            f" background: {THEME_COLORS['bookmark_pressed']}; }}"
            "QPushButton#reorderBookmarks:disabled {"
            f" color: {THEME_COLORS['ui_disabled_text']}; background: {THEME_COLORS['background']};"
            f" border-color: {THEME_COLORS['ui_border']}; }}"
        )
        self.reorder_button.clicked.connect(self.reorder)
        layout.addWidget(self.reorder_button)
        self.bar.hide()
        self.strip.activated.connect(self.activate)
        self.strip.rename_requested.connect(self.rename)
        self.strip.remove_requested.connect(self.request_remove)
        self.strip.menu_requested.connect(self._add_extra_menu_actions)

    def _retained(self, source: SourceLocation) -> bool:
        source_view = self.view.source_view
        return (source.snapshot_id == self.view._snapshot_id and
                source_view.first_line <= source.line <= source_view.total_line_count)

    @staticmethod
    def _name(name: str, source: SourceLocation) -> str:
        return name.strip() or f"Line {source.line:,}"

    def add(self, location: ResultLocation | SourceLocation, name: str) -> bool:
        source = location.source if isinstance(location, ResultLocation) else location
        model = self.view.model
        if not self._retained(source) or source in self.items:
            return False
        if isinstance(location, ResultLocation) and (
                self.view.is_rendering or model is None or model.resolve(location) is None):
            return False
        self.items[source] = Bookmark(location, self._name(name, source))
        self.refresh()
        self._select(source)
        return True

    def _prompt_name(self, title: str, name: str) -> tuple[str, bool]:
        dialog = QInputDialog(self.view)
        dialog.setWindowTitle(title)
        dialog.setLabelText("Name:")
        dialog.setTextValue(name)
        editor = dialog.findChild(QLineEdit)
        InputContextMenu(editor, undo=True)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.textValue(), accepted
        finally:
            dialog.deleteLater()

    def prompt(self, location: ResultLocation | SourceLocation) -> None:
        source = location.source if isinstance(location, ResultLocation) else location
        if source in self.items:
            self.rename(source)
            return
        name, accepted = self._prompt_name("Add bookmark", f"Line {source.line:,}")
        if accepted:
            # A modal dialog can process a completed load/render in the meantime.
            self.add(location, name)

    def rename(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None:
            return
        name, accepted = self._prompt_name("Rename bookmark", bookmark.name)
        if accepted and self.items.get(source) is bookmark:
            bookmark.name = self._name(name, source)
            self.refresh()

    def edit_notes(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None:
            return
        dialog = BookmarkNotesDialog(bookmark, source, self.view)
        if dialog.exec() == QDialog.DialogCode.Accepted and self.items.get(source) is bookmark:
            note = dialog.editor.toPlainText()
            if not note.strip() and bookmark.note:
                self.delete_note(source)
            else:
                bookmark.note = note if note.strip() else ""
                self.refresh()
        dialog.deleteLater()

    def delete_note(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if (bookmark is not None and bookmark.note
                and self._confirm_deletion(source, bookmark, note_only=True)
                and self.items.get(source) is bookmark):
            bookmark.note = ""
            self.refresh()

    def request_remove(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if (bookmark is not None and self._confirm_deletion(source, bookmark)
                and self.items.get(source) is bookmark):
            self.remove(source)

    def _confirm_deletion(self, source: SourceLocation, bookmark: Bookmark, *, note_only=False) -> bool:
        dialog = BookmarkDeletionDialog(bookmark, source, self.view, note_only=note_only)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return accepted

    def remove(self, source: SourceLocation) -> None:
        if self.items.pop(source, None) is not None:
            self.refresh()

    def clear(self) -> None:
        had_bookmarks = bool(self.items)
        self.items.clear()
        self.refresh()
        if had_bookmarks:
            self.view.bookmarks_cleared.emit()

    def add_menu_actions(self, menu: QMenu, location: ResultLocation | SourceLocation) -> None:
        source = location.source if isinstance(location, ResultLocation) else location
        if source in self.items:
            menu.addAction("Rename bookmark", lambda: self.rename(source))
            menu.addAction("Delete bookmark", lambda: self.request_remove(source))
            self._add_extra_menu_actions(menu, source)
        else:
            menu.addAction("Add bookmark", lambda: self.prompt(location))

    def _add_extra_menu_actions(self, menu: QMenu, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None:
            return
        before = menu.actions()[-2]
        notes = QAction("Open note" if bookmark.note else "Add note", menu)
        notes.triggered.connect(lambda: self.edit_notes(source))
        menu.insertAction(before, notes)
        if bookmark.note:
            delete = QAction("Delete note", menu)
            delete.triggered.connect(lambda: self.delete_note(source))
            menu.insertAction(before, delete)
        menu.insertSeparator(before)
        self._add_conversion_action(menu, source)
        if not isinstance(bookmark.location, SourceLocation):
            style = BookmarkMenuStyle(QStyleFactory.create(QApplication.style().objectName()))
            style.setParent(menu)
            menu.setStyle(style)

    def _add_conversion_action(self, menu: QMenu, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None or not isinstance(bookmark.location, SourceLocation):
            return
        disabled_text = menu.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name()
        menu.setStyleSheet(
            "QMenu { background: #ffffff; color: #000000; border: 1px solid #a0a0a0; }"
            "QMenu::item { padding: 4px 4px 4px 8px; }"
            f"QMenu::item:disabled {{ color: {disabled_text}; }}"
            f"QMenu::item:selected {{ background: {BOOKMARK_MENU_HOVER_COLOR}; color: #000000; }}"
            "QMenu::separator { height: 1px; background: #cccccc; margin: 3px 0; }"
            "QMenu::icon { width: 16px; height: 16px; left: 6px; }"
        )
        menu.addSeparator()
        action = menu.addAction("Convert when shown in results")
        action.setCheckable(True)
        action.setChecked(bookmark.convert_when_shown)
        action.setIcon(_conversion_toggle_icon())
        action.setProperty("keepMenuOpen", True)
        action.toggled.connect(lambda enabled: self._set_convert_when_shown(source, bookmark, enabled))
        menu.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if isinstance(watched, QMenu):
            action = None
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                action = watched.actionAt(event.position().toPoint())
            elif event.type() == QEvent.Type.KeyPress and event.key() in (
                    Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                action = watched.activeAction()
            if action is not None and action.isEnabled() and action.property("keepMenuOpen"):
                action.trigger()
                return True
        return super().eventFilter(watched, event)

    def _set_convert_when_shown(self, source: SourceLocation, bookmark: Bookmark, enabled: bool) -> None:
        if self.items.get(source) is bookmark and isinstance(bookmark.location, SourceLocation):
            bookmark.convert_when_shown = enabled
            self.refresh()

    def reorder(self) -> None:
        self.items = dict(sorted(self.items.items(), key=lambda item: item[0].line))
        for destination, source in enumerate(self.items):
            current = next(index for index in range(self.strip.count())
                           if self.strip.tabData(index) == source)
            if current != destination:
                self.strip.moveTab(current, destination)
        self.refresh()

    def _select(self, source: SourceLocation) -> None:
        for index in range(self.strip.count()):
            if self.strip.tabData(index) == source:
                self.strip.setCurrentIndex(index)
                break

    def activate(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None or not self._retained(source):
            return
        if self.view.source_active:
            self.view.source_view.target_line = None
            self.view.source_view.go_to_line(source.line, highlight=False, center_page=True)
        elif bookmark.source_only:
            self.strip.show_tooltip(source)
            return
        elif self.view.is_rendering:
            return
        elif not self.view.show_result_location(bookmark.location):
            self.refresh()
            self.strip.show_tooltip(source)
            return
        if self.view.source_active:
            self.view.source_view._use_viewport_anchor()
        self._select(source)
        self.view.focus_editor()

    def refresh(self) -> None:
        model = self.view.model
        if self.view.is_rendering or model is None or not model.ready:
            model = None
        blocks = {}
        selected = self.strip.tabData(self.strip.currentIndex())
        sources = set(self.items)
        # Keep existing tab objects/scroll position where possible.
        for index in range(self.strip.count() - 1, -1, -1):
            if self.strip.tabData(index) not in sources:
                self.strip.removeTab(index)
        for index, (source, bookmark) in enumerate(self.items.items()):
            rows = model.rows_for_source(source) if model is not None else ()
            if isinstance(bookmark.location, SourceLocation):
                if bookmark.convert_when_shown and rows:
                    preferred = next((row for row in rows if model.line(row).is_match), rows[0])
                    bookmark.location = model.location(preferred)
                    bookmark.convert_when_shown = False
                else:
                    rows = ()
            preferred = model.resolve(bookmark.location) if rows else None
            if not self.view.is_rendering:
                bookmark.converted = isinstance(bookmark.location, ResultLocation) and not rows
            for row in rows:
                blocks[self.view._source_map.block(row)] = row == preferred
            label = ("(c) " if bookmark.converted else "") + bookmark.name.replace("&", "&&")
            if index == self.strip.count():
                self.strip.addTab(label)
                self.strip.setTabData(index, source)
            else:
                self.strip.setTabText(index, label)
            self.strip.setTabTextColor(index, QColor(THEME_COLORS[
                "bookmark_source_text" if bookmark.source_only else "bookmark_text"
            ]))
            if bookmark.source_only:
                tooltip = f"Source-only bookmark\nLine {source.line:,}"
                if bookmark.converted:
                    tooltip += ("\nConverted to source bookmark. Match no longer appears on results. "
                                "Re-analysis needed.")
            elif self.view.is_rendering and not self.view.source_active:
                destination = "Results are updating. Open the original file to use this bookmark."
            elif self.view.source_active:
                destination = "Open this line in the original file."
            else:
                destination = "Open this line in results."
                if model.location(preferred).category != bookmark.location.category:
                    destination = "Open this line in results under another category."
            if not bookmark.source_only:
                title = "" if bookmark.name == f"Line {source.line:,}" else f"{bookmark.name}\n"
                tooltip = f"{title}Line {source.line:,}\n{destination}"
            if bookmark.note:
                tooltip += f"\n\nNote: {bookmark.note_preview}"
            self.strip.setTabToolTip(index, tooltip)
            self.strip.setTabEnabled(index, bookmark.source_only or not self.view.is_rendering
                                     or self.view.source_active)
            self.strip.set_note_icon(index, bool(bookmark.note))
        self._select(selected)
        self.strip.setVisible(bool(self.items))
        self.bar.setVisible(bool(self.items))
        self.reorder_button.setEnabled(len(self.items) > 1)
        self.view.editor.set_bookmarked_blocks(blocks)
        self.view.editor.verticalScrollBar().set_bookmark_blocks(blocks, self.view.editor.document())
        self.view.source_view.set_bookmarks({s.line for s in self.items if self._retained(s)})
