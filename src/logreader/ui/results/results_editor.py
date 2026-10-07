"""Qt presentation adapter for logical results and non-text decorations."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QTextBlockUserData, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QWidget

from ..widgets.line_number_editor import GUTTER_LEFT_PADDING
from ..theme import THEME_COLORS


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




class ResultsStructureArea(QWidget):
    """Present structural rows across both the gutter and the text column."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event) -> None:  # noqa: N802
        editor = self.parent()
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setPen(QColor(THEME_COLORS["body"]))
        offset = editor.contentOffset()
        offset.setY(offset.y() + editor.viewport().y())
        x = (editor.gutter.x() + offset.x() + GUTTER_LEFT_PADDING
             - editor.document().documentMargin())
        block = editor.firstVisibleBlock()
        while block.isValid():
            rect = editor.blockBoundingGeometry(block).translated(offset)
            if rect.top() > event.rect().bottom():
                break
            if block.isVisible() and isinstance(block.userData(), StructuralBlock):
                summary = block.userData() if isinstance(block.userData(), SummaryBlock) else None
                background_top = min(0, rect.top()) if summary and summary.first and block.blockNumber() == 0 else rect.top()
                painter.fillRect(
                    QRectF(0, background_top, self.width(), rect.bottom() - background_top),
                    QColor(THEME_COLORS["summary_background" if summary else "background"]),
                )
                # Reuse the document's shaped text, formatting and wrapped line
                # heights. This layer owns no duplicate text document or layout.
                block.layout().draw(painter, QPointF(x + (6 if summary else 0), rect.top()))
                previous = block.previous()
                previous_summary = previous.userData() if previous.isValid() else None
                if isinstance(previous_summary, SummaryBlock) and previous_summary.last:
                    # Extend the summary into the blank separator below it.
                    padding = min(6, rect.height())
                    painter.fillRect(QRectF(0, rect.top(), self.width(), padding),
                                     QColor(THEME_COLORS["summary_background"]))
            block = block.next()
