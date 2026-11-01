"""Profile menu actions and the save-name dialog."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QContextMenuEvent, QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QMenu, QWidget

from ..filter_snapshot import FilterSnapshot
from ..profiles import Profile, ProfileError, ProfileStore
from .dialogs import CompactDialog, show_warning
from .document_page import DocumentPage
from .theme import THEME_COLORS
from .title_bar import TitleMenu
from .widgets.input_menus import InputContextMenu
from .widgets.menu_style import CONTEXT_MENU_STYLE_SHEET
from .widgets.row_menu_button import RowMenuButton


class _ProfileRowOptions(QObject):
    requested = Signal(object, QPoint)

    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self.menu = menu
        self.actions = []
        self._action = None
        self._context_target = False
        self.button = RowMenuButton(menu, hover_color=THEME_COLORS['ui_button_hover_on_selected'])
        self.button.setObjectName("profileMenuButton")
        self.button.clicked.connect(self._request_from_button)
        self.button.installEventFilter(self)
        self.outline = QWidget(menu)
        self.outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.outline.setStyleSheet(f"background: transparent; border: 1px solid {THEME_COLORS['ui_accent']};")
        self.outline.hide()
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._refresh)
        menu.installEventFilter(self)
        menu.hovered.connect(self.show_for)
        # Reserve the button's space even while hidden, keeping names stationary.
        menu.setStyleSheet("QMenu#profilesMenu::item { padding-right: 40px; }")

    def set_actions(self, actions) -> None:
        self.show_for(None)
        self.actions = actions

    def show_for(self, action) -> None:
        if not self._context_target:
            self._action = action if action in self.actions else None
        self._refresh()

    def _refresh(self) -> None:
        action = self._action
        visible = self.menu.isVisible() and action in self.actions and action is not None
        self.button.setVisible(visible and not self._context_target)
        self.outline.setVisible(visible and self._context_target)
        if not visible:
            return
        bounds = self.menu.actionGeometry(action)
        self.button.move(bounds.right() - self.button.width() - 6,
                         bounds.center().y() - self.button.height() // 2)
        self.button.setAccessibleName(f"Options for {action.property('profileName')}")
        self.outline.setGeometry(bounds)
        self.outline.raise_()
        self.button.raise_()

    def set_context_target(self, active: bool) -> None:
        self._context_target = active
        self._refresh()

    def _request_from_button(self) -> None:
        if self._action in self.actions:
            self.requested.emit(self._action, self.button.mapToGlobal(self.button.rect().bottomLeft()))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease) and (
            event.button() == Qt.MouseButton.RightButton
        ):
            if kind == QEvent.Type.MouseButtonRelease:
                action = self._action if watched is self.button else self.menu.actionAt(event.position().toPoint())
                if action in self.actions:
                    self.show_for(action)
                    self.requested.emit(action, event.globalPosition().toPoint())
            return True
        if kind == QEvent.Type.ContextMenu:
            # Mouse releases above also work on platforms that do not synthesize
            # context-menu events. Consume the subsequent native event once.
            if event.reason() == QContextMenuEvent.Reason.Keyboard:
                self.show_for(self.menu.activeAction())
                self._request_from_button()
            return True
        if watched is not self.menu:
            return False
        if kind == QEvent.Type.KeyPress and (
            event.key() in (Qt.Key.Key_Menu, Qt.Key.Key_Right)
            or (event.key() == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ) and self.menu.activeAction() in self.actions:
            self.show_for(self.menu.activeAction())
            self._request_from_button()
            return True
        if kind == QEvent.Type.MouseMove:
            self.show_for(self.menu.actionAt(event.position().toPoint()))
        elif kind in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.ActionChanged):
            self._layout_timer.start(0)
        elif kind == QEvent.Type.Hide:
            self._layout_timer.stop()
            self.button.hide()
            self.outline.hide()
        return False


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
        self._row_options = _ProfileRowOptions(menu)
        self._row_options.requested.connect(self._show_profile_options)
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
        self._row_options.set_actions([])
        self.menu.clear()
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
        self._row_options.set_actions(self._profile_actions)
        if not self._profiles:
            self.menu.addAction(
                "No saved profiles" if self._folder_available else "Profiles unavailable"
            ).setEnabled(False)
        if self._load_errors:
            self.menu.addAction("Show load errors…").triggered.connect(self.show_load_errors)
        self.menu.addSeparator()
        self.menu.addAction("Open profiles folder").triggered.connect(self.open_folder)
        self.update_state()

    def _show_profile_options(self, action, position: QPoint) -> None:
        profile = next((profile for profile in self._profiles if profile.profile_id == action.data()), None)
        if profile is None:
            return
        options = TitleMenu(self.window)
        options.setObjectName("profileOptionsMenu")
        options.setStyleSheet(CONTEXT_MENU_STYLE_SHEET)
        rename = options.addAction("Rename…")
        delete = options.addAction("Delete…")
        self.menu.setActiveAction(action)
        self._row_options.show_for(action)
        self._row_options.set_context_target(True)
        try:
            selected = options.exec(position)
        finally:
            self._row_options.set_context_target(False)
            options.deleteLater()
        if selected is not None:
            self.menu.close()
            if selected is rename:
                self.rename(profile)
            elif selected is delete:
                self.delete(profile)

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
