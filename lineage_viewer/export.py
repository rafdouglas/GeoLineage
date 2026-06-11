"""Export lineage graph to DOT, SVG, and PNG formats.

export_dot is pure Python (T1-testable, no Qt).
export_svg and export_png require Qt (T2).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ..lineage_retrieval.graph_builder import LineageGraph

if TYPE_CHECKING:
    from qgis.PyQt.QtWidgets import QGraphicsScene

# Status -> Graphviz color name mapping
_DOT_COLORS: dict[str, str] = {
    "present": "green",
    "modified": "gold",
    "missing": "red",
    "raw_input": "deepskyblue",
    "busy": "orange",
}


def export_dot(graph: LineageGraph) -> str:
    """Export graph as Graphviz DOT format string.

    Node attributes: label=filename, color=status_color, shape=box.
    Edge attributes: from parent to child.
    """
    lines = ["digraph lineage {", "    rankdir=BT;", "    node [shape=box, style=filled];"]

    for path, node in graph.nodes.items():
        color = _DOT_COLORS.get(node.status, "gray")
        label = node.filename.replace('"', '\\"')
        node_id = _path_to_id(path)
        lines.append(f'    {node_id} [label="{label}", fillcolor={color}];')

    for edge in graph.edges:
        parent_id = _path_to_id(edge.parent_path)
        child_id = _path_to_id(edge.child_path)
        lines.append(f"    {parent_id} -> {child_id};")

    lines.append("}")
    return "\n".join(lines)


def _path_to_id(path: str) -> str:
    """Convert a file path to a collision-free DOT node ID.

    A char-substitution scheme collapsed distinct paths (e.g. 'a/b.gpkg' and
    'a_b.gpkg') to the same ID. A short hash of the full path is unique; the
    human-readable filename is kept separately in the node label.
    """
    digest = hashlib.md5(path.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"n_{digest[:12]}"


def export_svg(scene: QGraphicsScene, path: str) -> None:
    """Render the scene to an SVG file using QSvgGenerator."""
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QPainter
    from qgis.PyQt.QtSvg import QSvgGenerator

    rect = scene.sceneRect()
    generator = QSvgGenerator()
    generator.setFileName(path)
    generator.setSize(rect.size().toSize())
    generator.setViewBox(QRectF(0, 0, rect.width(), rect.height()))

    painter = QPainter(generator)
    if not painter.isActive():
        raise OSError(f"Cannot write SVG to {path} (painter failed to initialize)")
    scene.render(painter)
    painter.end()


def export_png(scene: QGraphicsScene, path: str, dpi: int = 150) -> None:
    """Render the scene to a PNG file using QImage.

    Caps output at 4096x4096 pixels to prevent memory issues.
    """
    from qgis.PyQt.QtCore import QRectF, Qt
    from qgis.PyQt.QtGui import QImage, QPainter

    rect = scene.sceneRect()
    scale = dpi / 96.0
    width = int(rect.width() * scale)
    height = int(rect.height() * scale)

    # Cap at 4096px
    max_dim = 4096
    if width > max_dim or height > max_dim:
        ratio = min(max_dim / width, max_dim / height)
        width = int(width * ratio)
        height = int(height * ratio)

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.white)

    painter = QPainter(image)
    if not painter.isActive():
        raise OSError(f"Cannot render PNG for {path} (painter failed to initialize)")
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, width, height), rect)
    painter.end()

    if not image.save(path, "PNG"):
        raise OSError(f"Failed to write PNG to {path}")
