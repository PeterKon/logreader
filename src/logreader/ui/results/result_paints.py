from PySide6.QtCore import QCoreApplication, QEvent

def flush_view_paints(editor):
    # Flush Qt's dirty regions, including the header, without forcing another
    # full repaint of unchanged long lines. Do not dispatch input or timers
    # recursively inside a batch.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QCoreApplication.sendPostedEvents(editor.window(), QEvent.Type.UpdateRequest)
