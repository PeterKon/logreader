"""Qt presentation adapter for logical results and non-text decorations."""

from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QTextBlockUserData, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QWidget

from .line_number_editor import GUTTER_LEFT_PADDING, LineNumberEditor
from .result_source_map import ResultSourceMap
from .results_model import ResultsModel
from .theme import THEME_COLORS


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


def mark_summary(cursor) -> None:
    """Decorate the completed summary without changing text or row positions."""
    block = cursor.document().firstBlock()
    last = cursor.block().previous()
    while block.isValid() and block.blockNumber() <= last.blockNumber():
        block.setUserData(SummaryBlock(first=block.blockNumber() == 0, last=block == last))
        block = block.next()


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
        x = offset.x() + GUTTER_LEFT_PADDING - editor.document().documentMargin()
        block = editor.firstVisibleBlock()
        while block.isValid():
            rect = editor.blockBoundingGeometry(block).translated(offset)
            if rect.top() > event.rect().bottom():
                break
            if block.isVisible() and isinstance(block.userData(), StructuralBlock):
                summary = block.userData() if isinstance(block.userData(), SummaryBlock) else None
                painter.fillRect(
                    QRectF(0, rect.top(), self.width(), rect.height()),
                    QColor(THEME_COLORS["summary_background" if summary else "background"]),
                )
                # Reuse the document's shaped text, formatting and wrapped line
                # heights. This layer owns no duplicate text document or layout.
                block.layout().draw(painter, QPointF(x + (6 if summary else 0), rect.top()))
                if summary:
                    border = QColor(THEME_COLORS["summary_border"])
                    painter.fillRect(QRectF(0, rect.top(), 1, rect.height()), border)
                    painter.fillRect(QRectF(self.width() - 1, rect.top(), 1, rect.height()), border)
                    if summary.first:
                        painter.fillRect(QRectF(0, rect.top(), self.width(), 1), border)
                    if summary.last:
                        painter.fillRect(QRectF(0, rect.bottom() - 1, self.width(), 1), border)
            block = block.next()


class ResultsEditor(LineNumberEditor):
    def __init__(self, parent=None) -> None:
        self.model: ResultsModel | None = None
        self.projection = ResultSourceMap()
        super().__init__(parent)
        self.structure_area = ResultsStructureArea(self)
        self.updateRequest.connect(self._update_structure_area)
        self.update_gutter()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            block = self.document().firstBlock()
            while block.isValid():
                if isinstance(block.userData(), ExcerptGapBlock):
                    size_excerpt_gap(block, self.font())
                block = block.next()

    def update_gutter(self, *_args) -> None:
        super().update_gutter()
        if hasattr(self, "structure_area"):
            viewport = self.viewport().geometry()
            left = self.gutter.geometry().left()
            self.structure_area.setGeometry(
                left, viewport.top(), viewport.right() - left + 1, viewport.height(),
            )
            self.structure_area.raise_()
            self.structure_area.update()

    def _update_structure_area(self, *_args) -> None:
        self.structure_area.update()

    def set_model(self, model: ResultsModel | None) -> None:
        self.model = model
        self.update_gutter()
        self.viewport().update()

    def clear(self) -> None:
        self.model = None
        self.projection.clear()
        super().clear()
        self.update_gutter()

    def setPlainText(self, text: str) -> None:  # noqa: N802
        self.model = None
        self.projection.clear()
        super().setPlainText(text)
        self.update_gutter()

    def source_number(self, block: int) -> int | None:
        return self.projection.source_line(block)

    def largest_source_number(self) -> int:
        return self.model.max_source_line if self.model is not None else 0

    def createMimeDataFromSelection(self) -> QMimeData:  # noqa: N802
        """Copy source text only, preserving selected whitespace and line breaks.

        Structural blocks never contribute clipboard text. Use model strings so
        Qt's selectedText normalization cannot change non-breaking spaces.
        Columns are UTF-16 units, matching QTextCursor (including emoji).
        """
        if self.model is None:
            return super().createMimeDataFromSelection()
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        block = self.document().findBlock(start)
        fragments = []
        while block.isValid() and block.position() < end:
            row = self.projection.row(block.blockNumber())
            if row is not None:
                text = self.model.line(row).text
                left = max(0, start - block.position())
                right = min(block.length() - 1, end - block.position())
                if left == 0 and right == block.length() - 1:
                    fragments.append(text)
                else:
                    fragments.append(text.encode("utf-16-le", errors="surrogatepass")[
                        left * 2:right * 2
                    ].decode("utf-16-le", errors="surrogatepass"))
                if block.position() + block.length() - 1 < end:
                    fragments.append("\n")
            block = block.next()
        mime = QMimeData()
        mime.setText("".join(fragments))
        return mime
