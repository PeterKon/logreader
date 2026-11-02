"""File menu actions for saving and opening sessions."""

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem,
)

from ..session_snapshot import SESSION_EXTENSION
from ..sessions import SessionExistsError, SessionStore
from .dialogs import CompactDialog, NameDialog, show_warning
from .theme import THEME_COLORS as C


Button = QDialogButtonBox.StandardButton


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
            prompt = CompactDialog("Overwrite session", self)
            prompt.setFixedWidth(420)
            message = QLabel(f'Overwrite “{name}” with the current tabs?')
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setWordWrap(True)
            prompt.body_layout.addWidget(message)
            prompt.set_buttons(Button.Yes | Button.Cancel, default=Button.Cancel, destructive=Button.Yes)
            prompt.buttons.button(Button.Yes).setText("Overwrite")
            prompt.buttons.button(Button.Cancel).setFocus()
            prompt.fit_content()
            try:
                if prompt.exec() != QDialog.DialogCode.Accepted:
                    return False
            finally:
                prompt.deleteLater()
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
        browse = self.buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        self.list.currentItemChanged.connect(self._update_open_button)
        self.list.itemActivated.connect(self.accept)
        self._fill_list()
        self._update_open_button()
        self.list.setFocus()

    def _fill_list(self):
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
            self.list.setCurrentItem(self.list.topLevelItem(0))
        else:
            QTreeWidgetItem(self.list, ["No saved sessions"]).setDisabled(True)

    def _update_open_button(self):
        item = self.list.currentItem()
        self.buttons.button(Button.Open).setEnabled(bool(item and item.data(0, Qt.ItemDataRole.UserRole)))

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
        menu.clear()
        self.save_action = menu.addAction("Save session…")
        self.save_action.triggered.connect(self.save_session)
        menu.addAction("Open session…").triggered.connect(self.open_session)
        menu.aboutToShow.connect(self.update_state)
        self.update_state()

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
