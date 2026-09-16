"""Session bookmarks identified by source location, with a shared navigation strip."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QStyle, QTabBar

from .results_model import ResultLocation, SourceLocation
from .theme import THEME_COLORS

if TYPE_CHECKING:
    from .results_view import ResultsView


@dataclass(slots=True)
class Bookmark:
    location: ResultLocation
    name: str


class BookmarkStrip(QTabBar):
    activated = Signal(object)
    rename_requested = Signal(object)
    remove_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        self._pressed_index = -1
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
            f" color: {THEME_COLORS['bookmark_marker']};"
            f" background: {THEME_COLORS['bookmark']};"
            " border: 0; border-radius: 0;"
            " padding: 4px 11px; margin: 0; max-width: 200px; }"
            "QTabBar#bookmarkStrip::tab:!last:!only-one {"
            f" border-right: 1px solid {THEME_COLORS['bookmark_divider']};"
            " padding-right: 10px; }"
            "QTabBar#bookmarkStrip::tab:hover {"
            f" background: {THEME_COLORS['bookmark_hover']}; }}"
            "QTabBar#bookmarkStrip::tab:pressed {"
            f" background: {THEME_COLORS['bookmark_pressed']}; }}"
            "QTabBar#bookmarkStrip::tab:disabled {"
            f" color: {THEME_COLORS['muted']}; }}"
        )
        # currentChanged alone would not navigate when clicking the same tab again.
        self.tabBarClicked.connect(self._activate)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.hide()

    def initStyleOption(self, option, index: int) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        # Keep the current tab for keyboard navigation, without a sticky highlight.
        option.state &= ~QStyle.StateFlag.State_Selected
        if (index == self._pressed_index and self.isTabEnabled(index)
                and option.state & QStyle.StateFlag.State_MouseOver
                and QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            option.state |= QStyle.StateFlag.State_Sunken

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_index = self.tabAt(event.position().toPoint())
        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed_index = -1
        super().mouseReleaseEvent(event)
        self.update()

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
        menu.exec(self.mapToGlobal(point))
        menu.deleteLater()


class ResultsBookmarks(QObject):
    def __init__(self, view: ResultsView) -> None:
        super().__init__(view)
        self.view = view
        self.items: dict[SourceLocation, Bookmark] = {}
        self.strip = BookmarkStrip(view)
        self.strip.activated.connect(self.activate)
        self.strip.rename_requested.connect(self.rename)
        self.strip.remove_requested.connect(self.remove)

    def _retained(self, source: SourceLocation) -> bool:
        source_view = self.view.source_view
        return (source.snapshot_id == self.view._snapshot_id and
                source_view.first_line <= source.line <= source_view.total_line_count)

    @staticmethod
    def _name(name: str, source: SourceLocation) -> str:
        return name.strip() or f"Line {source.line:,}"

    def add(self, location: ResultLocation, name: str) -> bool:
        model = self.view.model
        if (not self._retained(location.source) or self.view.is_rendering or
                model is None or model.resolve(location) is None or
                location.source in self.items):
            return False
        self.items[location.source] = Bookmark(location, self._name(name, location.source))
        self.refresh()
        self._select(location.source)
        return True

    def prompt(self, location: ResultLocation) -> None:
        if location.source in self.items:
            self.rename(location.source)
            return
        name, accepted = QInputDialog.getText(
            self.view, "Add bookmark", "Name:", QLineEdit.EchoMode.Normal,
            f"Line {location.source.line:,}",
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

    def add_menu_actions(self, menu: QMenu, location: ResultLocation) -> None:
        if location.source in self.items:
            menu.addAction("Rename bookmark…", lambda: self.rename(location.source))
            menu.addAction("Remove bookmark", lambda: self.remove(location.source))
        else:
            menu.addAction("Add bookmark…", lambda: self.prompt(location))

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
        elif self.view.is_rendering:
            return
        elif not self.view.show_result_location(bookmark.location):
            self.view.source_view.target_line = None
            self.view.show_source_line(source.line, highlight=False, center_page=True)
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
            preferred = model.resolve(bookmark.location) if rows else None
            for row in rows:
                blocks[self.view._source_map.block(row)] = row == preferred
            unavailable = not rows and not self.view.is_rendering
            label = bookmark.name.replace("&", "&&") + (" · source" if unavailable else "")
            if index == self.strip.count():
                self.strip.addTab(label)
                self.strip.setTabData(index, source)
            else:
                self.strip.setTabText(index, label)
            if self.view.is_rendering and not self.view.source_active:
                destination = "Results are updating. Switch to source to visit this bookmark."
            elif self.view.source_active or unavailable:
                destination = "Open this line in source."
                if unavailable:
                    destination += " This line is absent from the current results."
            else:
                destination = "Open this line in results."
                if model.location(preferred).category != bookmark.location.category:
                    destination += " Using another occurrence; the original category is absent."
            self.strip.setTabToolTip(index, f"{bookmark.name}\nSource line {source.line:,}\n{destination}")
            self.strip.setTabEnabled(index, not self.view.is_rendering or self.view.source_active)
        self._select(selected)
        self.strip.setVisible(bool(self.items))
        self.view.editor.set_bookmarked_blocks(blocks)
        self.view.source_view.set_bookmarks({s.line for s in self.items if self._retained(s)})
