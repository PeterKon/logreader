"""Session bookmarks identified by source location, with a shared navigation strip."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLineEdit, QMenu, QPushButton,
    QStyle, QTabBar, QToolTip, QWidget,
)

from .results_model import ResultLocation, SourceLocation
from .theme import THEME_COLORS, configure_action_button

if TYPE_CHECKING:
    from .results_view import ResultsView


@dataclass(slots=True)
class Bookmark:
    location: ResultLocation | SourceLocation
    name: str
    converted: bool = False
    convert_when_shown: bool = False

    @property
    def source_only(self) -> bool:
        return isinstance(self.location, SourceLocation) or self.converted


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
        menu.addAction("Rename bookmark…", lambda: self.rename_requested.emit(source))
        menu.addAction("Remove bookmark", lambda: self.remove_requested.emit(source))
        self.menu_requested.emit(menu, source)
        menu.exec(self.mapToGlobal(point))
        menu.deleteLater()


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
            f" color: {THEME_COLORS['bookmark_marker']}; background: {THEME_COLORS['background']};"
            " border: 0; border-radius: 0; min-height: 0; padding: 4px 10px 3px;"
            f" border-left: 1px solid {THEME_COLORS['bookmark_divider']};"
            f" border-bottom: 1px solid {THEME_COLORS['bookmark_border']}; }}"
            "QPushButton#reorderBookmarks:hover {"
            f" background: {THEME_COLORS['bookmark_hover']}; }}"
            "QPushButton#reorderBookmarks:pressed {"
            f" background: {THEME_COLORS['bookmark_pressed']}; }}"
            "QPushButton#reorderBookmarks:disabled {"
            f" color: {THEME_COLORS['muted']}; }}"
        )
        self.reorder_button.clicked.connect(self.reorder)
        layout.addWidget(self.reorder_button)
        self.bar.hide()
        self.strip.activated.connect(self.activate)
        self.strip.rename_requested.connect(self.rename)
        self.strip.remove_requested.connect(self.remove)
        self.strip.menu_requested.connect(self._add_conversion_action)

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

    def prompt(self, location: ResultLocation | SourceLocation) -> None:
        source = location.source if isinstance(location, ResultLocation) else location
        if source in self.items:
            self.rename(source)
            return
        name, accepted = QInputDialog.getText(
            self.view, "Add bookmark", "Name:", QLineEdit.EchoMode.Normal,
            f"Line {source.line:,}",
        )
        if accepted:
            # A modal dialog can process a completed load/render in the meantime.
            self.add(location, name)

    def rename(self, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None:
            return
        name, accepted = QInputDialog.getText(
            self.view, "Rename bookmark", "Name:", QLineEdit.EchoMode.Normal, bookmark.name,
        )
        if accepted and self.items.get(source) is bookmark:
            bookmark.name = self._name(name, source)
            self.refresh()

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
            menu.addAction("Rename bookmark…", lambda: self.rename(source))
            menu.addAction("Remove bookmark", lambda: self.remove(source))
            self._add_conversion_action(menu, source)
        else:
            menu.addAction("Add bookmark…", lambda: self.prompt(location))

    def _add_conversion_action(self, menu: QMenu, source: SourceLocation) -> None:
        bookmark = self.items.get(source)
        if bookmark is None or not isinstance(bookmark.location, SourceLocation):
            return
        menu.setStyleSheet(
            "QMenu { background: #ffffff; color: #000000; border: 1px solid #a0a0a0; }"
            "QMenu::item { padding: 4px 4px 4px 14px; }"
            "QMenu::item:selected { background: #e5f3ff; color: #000000; }"
            "QMenu::separator { height: 1px; background: #cccccc; margin: 3px 0; }"
            "QMenu::indicator { width: 12px; height: 12px; left: 6px; }"
            "QMenu::indicator:unchecked { border: 1px solid #606060; background: #ffffff; }"
        )
        menu.addSeparator()
        action = menu.addAction("Convert when shown in results")
        action.setCheckable(True)
        action.setChecked(bookmark.convert_when_shown)
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
                "bookmark_source_text" if bookmark.source_only else "bookmark_marker"
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
            self.strip.setTabToolTip(index, tooltip)
            self.strip.setTabEnabled(index, bookmark.source_only or not self.view.is_rendering
                                     or self.view.source_active)
        self._select(selected)
        self.strip.setVisible(bool(self.items))
        self.bar.setVisible(bool(self.items))
        self.reorder_button.setEnabled(len(self.items) > 1)
        self.view.editor.set_bookmarked_blocks(blocks)
        self.view.source_view.set_bookmarks({s.line for s in self.items if self._retained(s)})
