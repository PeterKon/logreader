from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QContextMenuEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QSpinBox


class InputContextMenu(QObject):
    def __init__(
        self, editor: QLineEdit, *, undo: bool = False, redo: bool = False,
        cut: bool = False, spin_box: QSpinBox | None = None,
    ) -> None:
        super().__init__(editor)
        self.editor = editor
        self.spin_box = spin_box
        self.history = tuple(name for name, enabled in (("undo", undo), ("redo", redo)) if enabled)
        self.editing = (("cut",) if cut else ()) + ("copy", "paste", "selectAll")
        editor.installEventFilter(self)
        if spin_box is not None:
            spin_box.installEventFilter(self)

    def create_menu(self) -> QMenu:
        editor = self.editor
        editable = not editor.isReadOnly()
        selected = editor.hasSelectedText()
        clipboard = QApplication.clipboard().mimeData()
        actions = {
            "undo": ("Undo", QKeySequence.StandardKey.Undo, editable and editor.isUndoAvailable()),
            "redo": ("Redo", QKeySequence.StandardKey.Redo, editable and editor.isRedoAvailable()),
            "cut": ("Cut", QKeySequence.StandardKey.Cut, editable and selected),
            "copy": ("Copy", QKeySequence.StandardKey.Copy, selected),
            "paste": ("Paste", QKeySequence.StandardKey.Paste,
                      editable and clipboard is not None and clipboard.hasText()),
            "selectAll": ("Select all", QKeySequence.StandardKey.SelectAll,
                          bool(editor.text()) and editor.selectedText() != editor.text()),
        }
        menu = QMenu(editor)
        for group in (self.history, self.editing):
            if group and menu.actions():
                menu.addSeparator()
            for name in group:
                label, key, enabled = actions[name]
                shortcut = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
                action = menu.addAction(f"{label}\t{shortcut}")
                action.setObjectName(name)
                action.setEnabled(enabled)
                action.triggered.connect(getattr(editor, name))
        return menu

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.ContextMenu:
            return False
        if (watched is self.spin_box
                and event.reason() != QContextMenuEvent.Reason.Keyboard
                and not self.editor.geometry().contains(event.pos())):
            event.accept()
            return True
        menu = self.create_menu()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
        event.accept()
        return True
