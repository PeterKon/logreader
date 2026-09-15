"""Qt presentation adapter for logical results and non-text decorations."""

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QTextBlockUserData
from PySide6.QtWidgets import QWidget

from .line_number_editor import GUTTER_LEFT_PADDING, LineNumberEditor
from .result_source_map import ResultSourceMap
from .results_model import ResultsModel
from .theme import THEME_COLORS


class StructuralBlock(QTextBlockUserData):
    """Summary/heading metadata that follows its native Qt block when it moves."""


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
                painter.fillRect(
                    QRectF(0, rect.top(), self.width(), rect.height()),
                    QColor(THEME_COLORS["background"]),
                )
                # Reuse the document's shaped text, formatting and wrapped line
                # heights. This layer owns no duplicate text document or layout.
                block.layout().draw(painter, QPointF(x, rect.top()))
            block = block.next()


class ResultsEditor(LineNumberEditor):
    def __init__(self, parent=None) -> None:
        self.model: ResultsModel | None = None
        self.projection = ResultSourceMap()
        super().__init__(parent)
        self.structure_area = ResultsStructureArea(self)
        self.updateRequest.connect(self._update_structure_area)
        self.update_gutter()

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
