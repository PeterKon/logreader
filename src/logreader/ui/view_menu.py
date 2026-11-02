from PySide6.QtCore import QRectF
from PySide6.QtGui import QIcon, QPainterPath

from .menu_icons import menu_icon, stroke


def view_menu_icons() -> dict[str, QIcon]:
    paths = {}

    source = paths["source"] = QPainterPath()
    stroke(source, (8, 1), (2, 1), (2, 13), (12, 13), (12, 5), (8, 1), (8, 5), (12, 5))
    stroke(source, (4.5, 8), (9.5, 8))
    stroke(source, (4.5, 10.5), (9.5, 10.5))
    results = paths["results"] = QPainterPath()
    for y, left, right in ((3, 1, 13), (7, 3, 11), (11, 5, 9)):
        stroke(results, (left, y), (right, y))

    for name, top_tip, top_tail, bottom_tip, bottom_tail in (
        ("expand", 0.5, 4.5, 13.5, 9.5),
        ("restore", 4.5, 0.5, 9.5, 13.5),
    ):
        path = paths[name] = QPainterPath()
        stroke(path, (1, 7), (13, 7))
        for tip, tail in ((top_tip, top_tail), (bottom_tip, bottom_tail)):
            wing = tip + (2 if tail > tip else -2)
            stroke(path, (7, tail), (7, tip))
            stroke(path, (5, wing), (7, tip), (9, wing))

    for name in ("zoom", "zoom_in", "zoom_out"):
        path = paths[name] = QPainterPath()
        path.addEllipse(QRectF(1, 1, 8.5, 8.5))
        stroke(path, (8.4, 8.4), (12.5, 12.5))
        if name != "zoom":
            stroke(path, (3.25, 5.25), (7.25, 5.25))
        if name == "zoom_in":
            stroke(path, (5.25, 3.25), (5.25, 7.25))
    reset = paths["reset"] = QPainterPath()
    circle = QRectF(1.5, 1.5, 11, 11)
    reset.arcMoveTo(circle, 150)
    reset.arcTo(circle, 150, -300)
    stroke(reset, (1.5, 1), (1.5, 4.5), (5, 4.5))

    return {name: menu_icon(path) for name, path in paths.items()}
