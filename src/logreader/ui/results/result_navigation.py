from collections import deque
from dataclasses import dataclass
from PySide6.QtCore import QObject, QTimer, Signal
from .result_coordinates import TextPoint


@dataclass(frozen=True, slots=True)
class NavigationRequest:
    result_set_id: object
    sequence: int
    point: TextPoint
    move_caret: bool
    anchor: TextPoint | None
    reveal_column: bool
    started: float


class ProgressiveNavigation(QObject):
    changed = Signal()
    needs_loading = Signal()
    completed = Signal(object)

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.result_set_id = object()
        self.pending = None
        self.measurements = deque(maxlen=256)
        self._sequence = 0
        self._ready = None
        self._applying = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._finish_ready)

    def cancel(self):
        self.timer.stop()
        self._ready = None
        if self.pending is not None:
            self.pending = None
            self.changed.emit()

    def invalidate(self):
        self.result_set_id = None
        self.cancel()

    def reset(self):
        self.invalidate()
        self.result_set_id = object()
        self.measurements.clear()


    def _finish_ready(self):
        ready = self._ready
        if ready is not None:
            self._finish(*ready)
