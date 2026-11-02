"""File menu actions for saving and opening sessions."""

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem,
)

from ..recent_files import recent_files
from ..session_snapshot import SESSION_EXTENSION
from ..sessions import SessionExistsError, SessionStore
from .dialogs import CompactDialog, NameDialog, show_warning
from .file_labels import file_label
from .menu_icons import FOLDER_PATH, SAVE_PATH, menu_icon
from .theme import THEME_COLORS as C


Button = QDialogButtonBox.StandardButton


def _confirm_session_action(parent, title, question, action):
    prompt = CompactDialog(title, parent)
    prompt.setFixedWidth(420)
    message = QLabel(question)
    message.setTextFormat(Qt.TextFormat.PlainText)
    message.setWordWrap(True)
    prompt.body_layout.addWidget(message)
    prompt.set_buttons(Button.Yes | Button.Cancel, default=Button.Cancel, destructive=Button.Yes)
    prompt.buttons.button(Button.Yes).setText(action)
    prompt.buttons.button(Button.Cancel).setFocus()
    prompt.fit_content()
    try:
        return prompt.exec() == QDialog.DialogCode.Accepted
    finally:
        prompt.deleteLater()


class SaveSessionDialog(NameDialog):
    def __init__(self, parent, store, tabs, selected_tab):
        self.store = store
        self.tabs = tabs
        self.selected_tab = selected_tab
        self.saved_at = datetime.now(timezone.utc)
        self.suggestion = store.default_name(self.saved_at)
        super().__init__(parent, "Save session", "session", self._write, initial_name=self.suggestion)

    def _write(self, name: str) -> bool:
        try:
            self.store.save(self.tabs, self.selected_tab, name=None if name == self.suggestion else name,
                            saved_at=self.saved_at)
        except SessionExistsError:
            if not _confirm_session_action(self, "Overwrite session", f'Overwrite “{name}” with the current tabs?',
                                           "Overwrite"):
                return False
            self.store.save(self.tabs, self.selected_tab, name=name, saved_at=self.saved_at, overwrite=True)
        return True


class OpenSessionDialog(CompactDialog):
    def __init__(self, window):
        super().__init__("Open session", window, resizable=True)
        self.selected_session = None
        self.directory = None
        self.setMinimumSize(480, 265)
        self.resize(610, 355)
        self.list = QTreeWidget()
        self.list.setAccessibleName("Saved sessions")
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setHeaderLabels(["Session", "Saved", "Tabs"])
        self.list.header().setStretchLastSection(False)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.list.setStyleSheet(f"""
            QTreeWidget {{ background: {C['ui_caption']}; color: {C['ui_text']};
                border: 1px solid {C['ui_border']}; outline: none; }}
            QTreeWidget::item {{ padding: 5px 8px; }}
            QTreeWidget::item:selected {{ background: {C['selection']}; color: {C['ui_text']}; }}
            QHeaderView::section {{ background: {C['ui_island']}; color: {C['ui_text']};
                border: none; padding: 5px 8px; }}
        """)
        self.body_layout.addWidget(self.list)
        self.set_buttons(Button.Open | Button.Cancel, default=Button.Open)
        self.buttons.setStyleSheet(f"""
            QPushButton:disabled {{ color: {C['ui_disabled_text']}; background: {C['ui_disabled']};
                border-color: {C['ui_border']}; }}
        """)
        self.delete_button = self.buttons.addButton("Delete…", QDialogButtonBox.ButtonRole.ResetRole)
        self.delete_button.setAutoDefault(False)
        self.delete_button.clicked.connect(self._delete_selected)
        browse = self.buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemActivated.connect(self.accept)
        self._fill_list()
        self._update_buttons()
        self.list.setFocus()

    def _fill_list(self, selected_row=0):
        self.list.clear()
        try:
            store = SessionStore()
            self.directory = store.directory
            result = store.load_all()
        except (OSError, ValueError) as error:
            message = QLabel(str(error))
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setWordWrap(True)
            self.body_layout.insertWidget(0, message)
            return
        for entry in result.sessions:
            session = entry.session
            try:
                saved = session.saved_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                saved = session.saved_at.isoformat()
            item = QTreeWidgetItem(self.list, [session.name, saved, str(len(session.tabs))])
            item.setData(0, Qt.ItemDataRole.UserRole, str(entry.path))
            item.setToolTip(0, str(entry.path))
        for error in result.errors:
            item = QTreeWidgetItem(self.list, [error.path.name, "Could not load"])
            item.setData(0, Qt.ItemDataRole.UserRole, str(error.path))
            item.setToolTip(0, error.message)
        if self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(min(selected_row, self.list.topLevelItemCount() - 1)))
        else:
            QTreeWidgetItem(self.list, ["No saved sessions"]).setDisabled(True)

    def _update_buttons(self):
        enabled = bool(self.list.selectedItems())
        self.buttons.button(Button.Open).setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _delete_selected(self):
        items = self.list.selectedItems()
        if not items:
            return
        item = items[0]
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if not _confirm_session_action(self, "Delete session", f'Delete saved session “{item.text(0)}”?', "Delete"):
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            show_warning(self, "Could not delete session", str(error))
            return
        self._fill_list(self.list.indexOfTopLevelItem(item))
        self.list.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is not None and (path := item.data(0, Qt.ItemDataRole.UserRole)):
            self._open(Path(path))

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", str(self.directory or Path.home()), f"Logreader sessions (*{SESSION_EXTENSION})",
        )
        if path:
            self._open(Path(path))

    def _open(self, path: Path):
        try:
            # Re-read the selected file in case it changed while the list was open.
            self.selected_session = self.parentWidget().validate_session(SessionStore.load(path))
        except (OSError, ValueError) as error:
            show_warning(self, "Could not open session", str(error))
            return
        super().accept()


class ReplaceTabsDialog(CompactDialog):
    def __init__(self, parent, session_name, tab_count):
        super().__init__("Open session", parent)
        self.replace_tabs = False
        self.setFixedWidth(480)
        tabs = "the open tab" if tab_count == 1 else f"the {tab_count} open tabs"
        message = QLabel(f'Opening “{session_name}” will replace {tabs}.')
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        self.body_layout.addWidget(message)
        self.set_buttons(Button.Save | Button.Discard | Button.Cancel,
                         default=Button.Cancel, destructive=Button.Discard)
        self.buttons.button(Button.Save).setText("Save current session")
        discard = self.buttons.button(Button.Discard)
        discard.setText("Replace tabs")
        discard.clicked.connect(self._replace)
        self.buttons.button(Button.Cancel).setFocus()
        self.fit_content()

    def _replace(self):
        self.replace_tabs = True
        self.accept()


class SessionMenuController(QObject):
    def __init__(self, window, menu):
        super().__init__(window)
        self.window = window
        self.menu = menu
        self._recent_actions = []
        menu.clear()
        menu.setToolTipsVisible(True)
        menu.setStyleSheet("QMenu::icon { left: 6px; }")
        self.save_action = menu.addAction(menu_icon(SAVE_PATH), "Save session…")
        self.save_action.triggered.connect(self.save_session)
        menu.addAction(menu_icon(FOLDER_PATH), "Open session…").triggered.connect(self.open_session)
        menu.aboutToShow.connect(self.update_state)
        menu.aboutToShow.connect(self._refresh_recent_files)
        self.update_state()

    def _refresh_recent_files(self):
        for action in self._recent_actions:
            self.menu.removeAction(action)
            action.deleteLater()
        self._recent_actions.clear()
        paths = recent_files()
        if not paths:
            return
        self._recent_actions.append(self.menu.addSeparator())
        heading = self.menu.addAction("Recent files")
        heading.setEnabled(False)
        self._recent_actions.append(heading)
        for number, path in enumerate(paths, 1):
            label = file_label(path, paths).replace("&", "&&")
            action = self.menu.addAction(f"{number}. {label}")
            action.setToolTip(str(path))
            action.triggered.connect(lambda checked=False, path=path: self.window.load_file(path))
            self._recent_actions.append(action)

    def update_state(self):
        self.save_action.setEnabled(self.window._tabs.count() > 0)

    def save_session(self) -> bool:
        try:
            dialog = SaveSessionDialog(self.window, SessionStore(), *self.window.capture_session())
            try:
                return dialog.exec() == QDialog.DialogCode.Accepted
            finally:
                dialog.deleteLater()
        except (OSError, ValueError) as error:
            show_warning(self.window, "Could not save session", str(error))
            return False

    def open_session(self):
        dialog = OpenSessionDialog(self.window)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            session = dialog.selected_session
        finally:
            dialog.deleteLater()

        count = self.window._tabs.count()
        if count:
            prompt = ReplaceTabsDialog(self.window, session.name, count)
            try:
                if prompt.exec() != QDialog.DialogCode.Accepted:
                    return
                save_current = not prompt.replace_tabs
            finally:
                prompt.deleteLater()
            if save_current and not self.save_session():
                return
        try:
            self.window.restore_session(session)
        except (OSError, ValueError, RuntimeError) as error:
            show_warning(self.window, "Could not open session", str(error))
