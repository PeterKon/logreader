"""Qt presentation adapter for logical results and non-text decorations."""

from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QMouseEvent, QPainter, QTextBlockUserData,
    QTextCharFormat, QTextCursor, QTextFormat, QTextLayout, QTextLine,
)
from PySide6.QtWidgets import QApplication, QWidget

from ..widgets.line_number_editor import GUTTER_LEFT_PADDING
from ..theme import THEME_COLORS

SUMMARY_PATTERN_PROPERTY = QTextFormat.Property.UserProperty


class StructuralBlock(QTextBlockUserData):
    """Summary/heading metadata that follows its native Qt block when it moves."""


class ExcerptGapBlock(StructuralBlock):
    """A blank separator whose height is four pixels less than a text line."""


def size_excerpt_gap(block, font) -> None:
    # QPlainTextEdit ignores block line-height settings; size the empty block's
    # font instead, leaving all source text and block positions intact.
    target = max(1, QFontMetricsF(font).height() - 4)
    gap_font = QFont(font)
    size = max(1, round(target))
    gap_font.setPixelSize(size)
    while size > 1 and QFontMetricsF(gap_font).height() > target:
        size -= 1
        gap_font.setPixelSize(size)
    text_format = QTextCharFormat()
    text_format.setFont(gap_font)
    QTextCursor(block).setBlockCharFormat(text_format)


class SummaryBlock(StructuralBlock):
    def __init__(self, *, first=False, last=False) -> None:
        super().__init__()
        self.first = first
        self.last = last


@dataclass(slots=True)
class _SummaryPress:
    key: str
    result_set_id: object
    surface: QWidget
    event: QMouseEvent

class ResultsStructureArea(QWidget):
    """Present structural rows across both the gutter and the text column."""

    pattern_clicked = Signal(str, object)

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._pressed: _SummaryPress | None = None
        self._replaying_press = False
        self._mouse_surface = self._hand_surface = None
        self._original_cursor = None
        self._mouse_position = None
        self._hovered_key = self._active_key = None

    def enable_pattern_links(self):
        editor = self.parent()
        for surface in (editor, editor.gutter, editor.viewport()):
            surface.setMouseTracking(True)
            surface.installEventFilter(self)

    def _structural_rows(self, bottom, *, stop_at_source=False):
        editor = self.parent()
        offset = editor.contentOffset()
        offset.setY(offset.y() + editor.viewport().y())
        x = (editor.gutter.x() + offset.x() + GUTTER_LEFT_PADDING
             - editor.document().documentMargin())
        block = editor.firstVisibleBlock()
        while block.isValid():
            data = block.userData()
            if stop_at_source and not isinstance(data, StructuralBlock):
                break  # The entire summary precedes the first source row.
            rect = editor.blockBoundingGeometry(block).translated(offset)
            if rect.top() > bottom:
                break
            if block.isVisible() and isinstance(data, StructuralBlock):
                summary = data if isinstance(data, SummaryBlock) else None
                yield block, summary, rect, QPointF(x + (6 if summary else 0), rect.top())
            block = block.next()

    def _pattern_at(self, point):
        if not self.isEnabled() or not QRectF(self.rect()).contains(point):
            return None
        for block, summary, rect, origin in self._structural_rows(point.y(), stop_at_source=True):
            if not summary or not rect.top() <= point.y() < rect.bottom():
                continue
            layout = block.layout()
            local = QPointF(point) - origin
            index = bisect_right(range(layout.lineCount()), local.y(), key=lambda i: layout.lineAt(i).y()) - 1
            if index < 0:
                return None
            line = layout.lineAt(index)
            bounds = line.naturalTextRect()
            if not (bounds.left() <= local.x() < bounds.right() and bounds.top() <= local.y() < bounds.bottom()):
                return None
            column = line.xToCursor(local.x(), QTextLine.CursorPosition.CursorOnCharacter)
            if column < line.textStart() + line.textLength():
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + column + 1)
                return cursor.charFormat().property(SUMMARY_PATTERN_PROPERTY)
        return None

    def _show_hand(self, surface):
        if self._hand_surface is surface:
            return
        if self._hand_surface is not None:
            if self._original_cursor is None:
                self._hand_surface.unsetCursor()
            else:
                self._hand_surface.setCursor(self._original_cursor)
        self._hand_surface = surface
        if surface is not None:
            self._original_cursor = surface.cursor() if surface.testAttribute(Qt.WidgetAttribute.WA_SetCursor) else None
            surface.setCursor(Qt.CursorShape.PointingHandCursor)

    def _update_hover(self, surface, position=None):
        self._mouse_surface, self._mouse_position = surface, position
        key = self._pattern_at(self.mapFromGlobal(position)) if position is not None else None
        self._show_hand(surface if key is not None else None)
        if key != self._hovered_key:
            self._hovered_key = key
            self.update()

    def set_active_pattern(self, key):
        if key != self._active_key:
            self._active_key = key
            self.update()

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._pressed = None
            self._update_hover(None)
            self.update()

    def eventFilter(self, surface, event):  # noqa: N802
        if self._replaying_press:
            return False
        kind = event.type()
        if kind in (QEvent.Type.Leave, QEvent.Type.Hide):
            if surface is self._mouse_surface:
                self._update_hover(None)
            if kind == QEvent.Type.Hide and self._pressed is not None:
                self._pressed = None
                self.update()
            return False
        if kind not in (QEvent.Type.Enter, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                        QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return False
        point = self.mapFromGlobal(event.globalPosition())
        editor = self.parent()
        press = self._pressed
        if (surface is editor and not (press and press.surface is editor)
                and editor.childAt(self.mapToParent(point).toPoint()) is not None):
            return False  # A gutter or viewport event propagated to its parent.
        key = self._pattern_at(point)
        if kind == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton and press is None:
            self._update_hover(None)
        else:
            self._update_hover(surface, event.globalPosition())
        if kind == QEvent.Type.Enter:
            return False
        if press is not None:
            distance = (event.globalPosition() - press.event.globalPosition()).manhattanLength()
            click = distance < QApplication.startDragDistance() and not event.modifiers()
            if kind == QEvent.Type.MouseMove and click and event.buttons() == Qt.MouseButton.LeftButton:
                return True
            self._pressed = None
            self.update()
            if kind == QEvent.Type.MouseMove and not event.buttons() & Qt.MouseButton.LeftButton:
                return False
            if press.result_set_id is editor.result_set_id and self.isEnabled():
                if (kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                        and click and key == press.key):
                    self.pattern_clicked.emit(key, press.result_set_id)
                    return True
                # Hand the original press back before Qt handles the drag or modified release.
                self._update_hover(None)
                self._replaying_press = True
                try:
                    QApplication.sendEvent(press.surface, press.event)
                finally:
                    self._replaying_press = False
        if (kind == QEvent.Type.MouseButtonPress and event.buttons() == Qt.MouseButton.LeftButton
                and not event.modifiers() and key is not None):
            self._pressed = _SummaryPress(key, editor.result_set_id, surface, event.clone())
            self.update()
            return True
        return False

    def _summary_formats(self, block):
        if not self.isEnabled() or (self._hovered_key is None and self._active_key is None):
            return []
        formats = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            key = fragment.charFormat().property(SUMMARY_PATTERN_PROPERTY)
            if key is not None and key in (self._hovered_key, self._active_key):
                hovered, active = key == self._hovered_key, key == self._active_key
                pressed = (hovered and self._pressed is not None and self._pressed.key == key
                           and self._pressed.result_set_id is self.parent().result_set_id)
                color = "summary_pressed" if pressed else "summary_hover" if hovered else "summary_active"
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(THEME_COLORS[color]))
                if active:
                    fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
                    fmt.setUnderlineColor(QColor(THEME_COLORS["ui_accent"]))
                selection = QTextLayout.FormatRange()
                selection.start = fragment.position() - block.position()
                selection.length = fragment.length()
                selection.format = fmt
                formats.append(selection)
            iterator += 1
        return formats

    def paintEvent(self, event) -> None:  # noqa: N802
        # Re-hit-test the last pointer position when scrolling, zooming or renaming
        # moves the text underneath it. Formatting stays local to this paint.
        if self._mouse_surface is not None:
            self._update_hover(self._mouse_surface, self._mouse_position)
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setPen(QColor(THEME_COLORS["body"]))
        for block, summary, rect, origin in self._structural_rows(event.rect().bottom()):
            background_top = min(0, rect.top()) if summary and summary.first and block.blockNumber() == 0 else rect.top()
            painter.fillRect(
                QRectF(0, background_top, self.width(), rect.bottom() - background_top),
                QColor(THEME_COLORS["summary_background" if summary else "background"]),
            )
            block.layout().draw(painter, origin, self._summary_formats(block) if summary else [])
            previous = block.previous()
            previous_summary = previous.userData() if previous.isValid() else None
            if isinstance(previous_summary, SummaryBlock) and previous_summary.last:
                # Extend the summary into the blank separator below it.
                painter.fillRect(QRectF(0, rect.top(), self.width(), min(6, rect.height())),
                                 QColor(THEME_COLORS["summary_background"]))
