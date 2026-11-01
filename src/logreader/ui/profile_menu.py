"""Profile menu actions and the save-name dialog."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QMenu, QWidget

from ..filter_snapshot import FilterSnapshot
from ..profiles import Profile, ProfileError, ProfileStore
from .dialogs import CompactDialog, show_warning
from .document_page import DocumentPage
from .theme import THEME_COLORS
from .title_bar import TitleMenu
from .widgets.input_menus import InputContextMenu


class ProfileNameDialog(CompactDialog):
    def __init__(
        self, parent: QWidget, save: Callable[[str], None], *, initial_name: str = "",
    ) -> None:
        super().__init__("Rename profile" if initial_name else "Save as new profile", parent)
        self._save = save
        self.setObjectName("profileNameDialog")
        self.setFixedWidth(420)
        self.body_layout.setContentsMargins(14, 12, 14, 12)
        self.buttons.setContentsMargins(14, 0, 14, 12)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("profileNameInput")
        self.name_input.setAccessibleName("Profile name")
        InputContextMenu(self.name_input, undo=True, redo=True, cut=True)
        label = QLabel("Name")
        label.setBuddy(self.name_input)
        self.body_layout.addWidget(label)
        self.body_layout.addWidget(self.name_input)
        self.error_label = QLabel()
        self.error_label.setObjectName("profileNameError")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {THEME_COLORS['ui_excluded']};")
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
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Rename")
        self.name_input.setFocus()

    def accept(self) -> None:
        try:
            name = self.name_input.text().strip()
            if not name:
                raise ProfileError("Enter a profile name.")
            self._save(name)
        except (ValueError, OSError) as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            self.fit_content()
            self.name_input.setFocus()
            return
        super().accept()


class ProfileDeletionDialog(CompactDialog):
    def __init__(self, parent: QWidget, name: str) -> None:
        super().__init__("Delete profile", parent)
        self.setFixedWidth(420)
        self.body_layout.setContentsMargins(14, 12, 14, 12)
        self.buttons.setContentsMargins(14, 0, 14, 12)
        self.target = QLabel(name)
        self.target.setStyleSheet("font-weight: 600;")
        self.message = QLabel("Delete this saved profile? Settings already applied to open tabs will be kept.")
        for label in (self.target, self.message):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            self.body_layout.addWidget(label)
        self.set_buttons(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No,
            default=QDialogButtonBox.StandardButton.No,
            destructive=QDialogButtonBox.StandardButton.Yes,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.No)
        cancel.setText("Cancel")
        cancel.setFocus()
        self.fit_content()


class ProfileMenuController(QObject):
    def __init__(
        self, window: QWidget, menu: QMenu, current_page: Callable[[], DocumentPage | None],
        all_pages: Callable[[], tuple[DocumentPage, ...]],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.menu = menu
        self.current_page = current_page
        self.all_pages = all_pages
        self._store: ProfileStore | None = None
        self._profiles: tuple[Profile, ...] = ()
        self._load_errors = ""
        self._folder_available = True
        self._profile_actions = []
        self._management_menus = []
        self._rebuild_menu()
        self.menu.aboutToShow.connect(self.refresh)

    @property
    def store(self) -> ProfileStore:
        if self._store is None:
            self._store = ProfileStore()
        return self._store

    def refresh(self) -> None:
        try:
            result = self.store.load_all()
            self._profiles = result.profiles
            self._load_errors = "\n\n".join(error.message for error in result.errors)
            self._folder_available = True
        except (ValueError, OSError) as error:
            self._profiles = ()
            self._load_errors = str(error)
            self._folder_available = False
        saved = {profile.profile_id: profile for profile in self._profiles}
        for page in self.all_pages():
            if page.applied_profile is not None:
                page.sync_saved_profile(saved.get(page.applied_profile.profile_id))
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        for menu in self._management_menus:
            menu.deleteLater()
        self._management_menus = []
        self._save_action = self.menu.addAction("Save as new profile…")
        self._save_action.triggered.connect(self.save_new)
        self._update_action = self.menu.addAction("Update profile")
        self._update_action.triggered.connect(self.update_profile)
        self.menu.addSeparator()
        self._profile_actions = []
        for profile in self._profiles:
            action = self.menu.addAction(profile.name.replace("&", "&&"))
            action.setData(profile.profile_id)
            action.setProperty("profileName", profile.name)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, saved=profile: self.apply(saved))
            self._profile_actions.append(action)
        if not self._profiles:
            self.menu.addAction(
                "No saved profiles" if self._folder_available else "Profiles unavailable"
            ).setEnabled(False)
        if self._load_errors:
            self.menu.addAction("Show load errors…").triggered.connect(self.show_load_errors)
        self.menu.addSeparator()
        for title, handler in (("Rename", self.rename), ("Delete", self.delete)):
            submenu = TitleMenu(title, self.menu)
            submenu.setEnabled(bool(self._profiles))
            self.menu.addMenu(submenu)
            self._management_menus.append(submenu)
            for profile in self._profiles:
                action = submenu.addAction(profile.name.replace("&", "&&"))
                action.setData(profile.profile_id)
                action.triggered.connect(lambda _checked=False, saved=profile, callback=handler: callback(saved))
        self.menu.addSeparator()
        self.menu.addAction("Open profiles folder").triggered.connect(self.open_folder)
        self.update_state()

    def update_state(self) -> None:
        page = self.current_page()
        available = page is not None and not page._disposed and not page.session.is_busy
        self._save_action.setEnabled(available and self._folder_available)
        self._update_action.setEnabled(available and self._folder_available
                                       and page.profile_available and page.profile_modified)
        for action in self._profile_actions:
            action.setEnabled(available)
            selected = (page is not None and page.applied_profile is not None
                        and page.applied_profile.profile_id == action.data())
            action.setChecked(selected)
            name = action.property("profileName")
            action.setText(name.replace("&", "&&") + (" (modified)" if selected and page.profile_modified else ""))

    def _editable_page(self) -> DocumentPage | None:
        page = self.current_page()
        if page is None or page._disposed or page.session.is_busy:
            self.update_state()
            return None
        return page

    def save_new(self) -> None:
        page = self._editable_page()
        if page is None:
            return
        try:
            snapshot = page.filter_panel.capture_snapshot()
            # Validate filters before asking for a name.
            Profile("New profile", snapshot)
        except ValueError as error:
            show_warning(self.window, "Could not save profile", str(error))
            return
        dialog = ProfileNameDialog(
            self.window, lambda name: self._save_named(page, snapshot, name),
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh()
        finally:
            dialog.deleteLater()

    def _save_named(self, page: DocumentPage, snapshot: FilterSnapshot, name: str) -> None:
        if page is not self._editable_page():
            raise ProfileError("The tab is no longer available. Close this dialog and try again.")
        profile = Profile(name, snapshot)
        self.store.create(profile)
        page.applied_profile = profile
        page._set_status(f"Profile saved: {profile.name}")

    def update_profile(self) -> None:
        page = self._editable_page()
        if page is None or page.applied_profile is None or not page.profile_available:
            return
        try:
            snapshot = page.filter_panel.capture_snapshot()
            updated = self.store.update(page.applied_profile, snapshot)
            page.applied_profile = updated
            page._set_status(f"Profile updated: {updated.name}")
            self.refresh()
        except (ValueError, OSError) as error:
            show_warning(self.window, "Could not update profile", str(error))

    def rename(self, selected: Profile) -> None:
        try:
            current = self.store.get(selected.profile_id)
        except (ValueError, OSError) as error:
            show_warning(self.window, "Could not rename profile", str(error))
            return
        dialog = ProfileNameDialog(
            self.window, lambda name: self.store.rename(current, name), initial_name=current.name,
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh()
        finally:
            dialog.deleteLater()

    def delete(self, selected: Profile) -> None:
        try:
            current = self.store.get(selected.profile_id)
            dialog = ProfileDeletionDialog(self.window, current.name)
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
            finally:
                dialog.deleteLater()
            self.store.delete(current)
            for page in self.all_pages():
                if page.applied_profile is not None and page.applied_profile.profile_id == current.profile_id:
                    page.applied_profile = None
                    page._set_status(f"Profile deleted: {current.name}")
            self.refresh()
        except (ValueError, OSError) as error:
            show_warning(self.window, "Could not delete profile", str(error))

    def apply(self, selected: Profile) -> None:
        page = self._editable_page()
        if page is None:
            return
        try:
            # Read again so a file edited or deleted since opening the menu
            # cannot silently apply the old in-memory copy.
            result = self.store.load_all()
            profile = next((item for item in result.profiles
                            if item.profile_id == selected.profile_id), None)
            if profile is None:
                details = "\n\n".join(error.message for error in result.errors)
                raise ProfileError(f"Profile '{selected.name}' is no longer available."
                                   + (f"\n\n{details}" if details else ""))
            page.apply_profile(profile)
        except (ValueError, OSError) as error:
            show_warning(self.window, "Could not apply profile", str(error))
        finally:
            self.update_state()

    def show_load_errors(self) -> None:
        show_warning(self.window, "Could not load profiles", self._load_errors)

    def open_folder(self) -> None:
        try:
            directory = self.store.directory
            directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                raise ProfileError(f"Could not open profiles folder: {directory}")
        except (ValueError, OSError) as error:
            show_warning(self.window, "Could not open profiles folder", str(error))
