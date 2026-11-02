"""Profile menu actions and the save-name dialog."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QDesktopServices, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMenu, QWidget

from ..filter_snapshot import FilterSnapshot
from ..profiles import Profile, ProfileError, ProfileStore
from .dialogs import CompactDialog, NameDialog, show_warning
from .document_page import DocumentPage
from .menu_icons import FOLDER_PATH, SAVE_PATH
from .theme import THEME_COLORS
from .title_bar import TitleMenu
from .widgets.menu_style import CONTEXT_MENU_STYLE_SHEET
from .widgets.row_menu_button import RowMenuButton


class _ProfileMenuSymbols(QWidget):
    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        menu.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest,
                            QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved, QEvent.Type.ActionChanged):
            self.setGeometry(watched.rect())
            self.update()
        return False

    @staticmethod
    def check_rect(bounds) -> QRectF:
        return QRectF(bounds.right() - 52, bounds.center().y() - 6.5, 14, 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        menu = self.parentWidget()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for action in menu.actions():
            symbol = action.property("profileSymbol")
            if not symbol or not action.isVisible():
                continue
            bounds = menu.actionGeometry(action)
            muted_profile = symbol == "profile" and action is not menu.activeAction()
            color = THEME_COLORS["ui_disabled_text" if not action.isEnabled() or muted_profile else
                                 "ui_accent" if action.isChecked() else "ui_muted"]
            painter.setPen(QPen(QColor(color), 1.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.save()
            if muted_profile:
                painter.setOpacity(0.20)
            painter.translate(bounds.left() + 8, bounds.center().y() - 6.5)
            _paint_profile_symbol(painter, symbol)
            painter.restore()
            if symbol == "profile" and action.isChecked():
                painter.save()
                pen = painter.pen()
                pen.setColor(QColor(THEME_COLORS["ui_accent" if action.isEnabled() else "ui_disabled_text"]))
                painter.setPen(pen)
                painter.translate(self.check_rect(bounds).topLeft())
                path = QPainterPath(QPointF(2, 7))
                path.lineTo(5.3, 10.3)
                path.lineTo(12, 3.6)
                painter.drawPath(path)
                painter.restore()


def _paint_profile_symbol(painter: QPainter, symbol: str) -> None:
    def stroke(*points) -> None:
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
        painter.drawPath(path)

    if symbol == "save":
        painter.drawPath(SAVE_PATH)
    elif symbol == "profile":
        for y, x in ((3, 9), (7, 4), (11, 8)):
            stroke((1, y), (x - 1.5, y))
            stroke((x + 1.5, y), (13, y))
            painter.drawEllipse(QPointF(x, y), 1.5, 1.5)
    elif symbol == "folder":
        painter.drawPath(FOLDER_PATH)
    elif symbol == "overwrite":
        painter.drawArc(QRectF(1.5, 1.5, 11, 11), 30 * 16, 150 * 16)
        painter.drawArc(QRectF(1.5, 1.5, 11, 11), 210 * 16, 150 * 16)
        stroke((9, 4.3), (12, 4.3), (12, 1.3))
        stroke((5, 9.7), (2, 9.7), (2, 12.7))
    elif symbol == "rename":
        path = QPainterPath(QPointF(2, 9.4))
        path.lineTo(1.4, 12.6)
        path.lineTo(4.6, 12)
        path.lineTo(12.1, 4.5)
        path.quadTo(13, 3.6, 12.1, 2.7)
        path.lineTo(11.3, 1.9)
        path.quadTo(10.4, 1, 9.5, 1.9)
        path.closeSubpath()
        painter.drawPath(path)
        stroke((8.3, 3.1), (10.9, 5.7))
    elif symbol == "delete":
        stroke((1.5, 3.5), (12.5, 3.5))
        stroke((5, 3.5), (5, 1.5), (9, 1.5), (9, 3.5))
        stroke((3, 3.5), (3.5, 12.5), (10.5, 12.5), (11, 3.5))
        stroke((5.5, 6), (5.5, 10))
        stroke((8.5, 6), (8.5, 10))


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
        # Reserve the icons, checkmark and button even while hidden.
        menu.setStyleSheet("""
            QMenu#profilesMenu::item { padding-left: 30px; padding-right: 62px; }
            QMenu#profilesMenu::indicator { width: 0; height: 0; }
        """)

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


class ProfileNameDialog(NameDialog):
    def __init__(
        self, parent: QWidget, save: Callable[[str], None], *, initial_name: str = "",
    ) -> None:
        super().__init__(parent, "Rename profile" if initial_name else "Save as new profile",
                         "profile", save, initial_name=initial_name)
        if initial_name:
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Rename")


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
        self._symbols = _ProfileMenuSymbols(menu)
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
        self._save_action.setProperty("profileSymbol", "save")
        self._save_action.triggered.connect(self.save_new)
        self.menu.addSeparator()
        self._profile_actions = []
        for profile in self._profiles:
            action = self.menu.addAction(profile.name.replace("&", "&&"))
            action.setData(profile.profile_id)
            action.setProperty("profileName", profile.name)
            action.setProperty("profileSymbol", "profile")
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
        folder = self.menu.addAction("Open profiles folder")
        folder.setProperty("profileSymbol", "folder")
        folder.triggered.connect(self.open_folder)
        self.update_state()

    def _show_profile_options(self, action, position: QPoint) -> None:
        profile = next((profile for profile in self._profiles if profile.profile_id == action.data()), None)
        if profile is None:
            return
        options = TitleMenu(self.window)
        options.setObjectName("profileOptionsMenu")
        options.setStyleSheet(CONTEXT_MENU_STYLE_SHEET + """
            QMenu#profileOptionsMenu::item { padding-left: 30px; }
        """)
        _ProfileMenuSymbols(options)
        overwrite = options.addAction("Overwrite with current settings")
        overwrite.setProperty("profileSymbol", "overwrite")
        overwrite.setEnabled(self._editable_page() is not None and self._folder_available)
        rename = options.addAction("Rename…")
        rename.setProperty("profileSymbol", "rename")
        delete = options.addAction("Delete…")
        delete.setProperty("profileSymbol", "delete")
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
            if selected is overwrite:
                self.update_profile(profile)
            elif selected is rename:
                self.rename(profile)
            elif selected is delete:
                self.delete(profile)

    def update_state(self) -> None:
        page = self.current_page()
        available = page is not None and not page._disposed and not page.session.is_busy
        self._save_action.setEnabled(available and self._folder_available)
        for action in self._profile_actions:
            action.setEnabled(available)
            selected = (page is not None and page.applied_profile is not None
                        and page.applied_profile.profile_id == action.data())
            action.setChecked(selected and not page.profile_modified)

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

    def update_profile(self, selected: Profile) -> None:
        page = self._editable_page()
        if page is None:
            return
        try:
            snapshot = page.filter_panel.capture_snapshot()
            updated = self.store.update(selected, snapshot)
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
