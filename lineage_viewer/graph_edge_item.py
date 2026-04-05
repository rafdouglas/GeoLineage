"""Visual representation of an edge (parent -> child arrow) in the graph scene."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..lineage_retrieval.graph_builder import LineageEdge
    from .graph_layout import LayoutConfig

_EDGE_COLOR = "#666666"
_ARROWHEAD_SIZE = 8.0


def _get_base_class():
    """Return QGraphicsPathItem at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QGraphicsPathItem

        return QGraphicsPathItem
    except ImportError:
        return object


class GraphEdgeItem(_get_base_class()):
    """Bezier curve arrow from parent node to child node.

    Accepts an ordered sequence of waypoints (source bottom-center,
    optional dummy-node centers, target top-center) and renders
    smooth chained cubic Bezier curves through them.

    Inherits from QGraphicsPathItem at runtime. Declared without
    Qt base class at module level so the module can be imported
    in T1 tests (no QApplication needed for import).
    """

    def __init__(
        self,
        edge: LineageEdge,
        waypoints: Sequence[tuple[float, float]],
        config: LayoutConfig,
    ) -> None:
        import math

        from qgis.PyQt.QtCore import QPointF
        from qgis.PyQt.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
        from qgis.PyQt.QtWidgets import QGraphicsPolygonItem

        super().__init__()

        self._edge = edge

        points = [QPointF(x, y) for x, y in waypoints]

        path = QPainterPath()
        path.moveTo(points[0])

        if len(points) == 2:
            # Single-rank edge: one cubic Bezier (same as original behavior)
            ctrl_offset = config.vertical_gap * 0.5
            ctrl1 = QPointF(points[0].x(), points[0].y() + ctrl_offset)
            ctrl2 = QPointF(points[1].x(), points[1].y() - ctrl_offset)
            path.cubicTo(ctrl1, ctrl2, points[1])
        else:
            # Multi-rank edge: chained cubic Bezier segments
            for i in range(len(points) - 1):
                p0 = points[i]
                p1 = points[i + 1]
                seg_height = abs(p1.y() - p0.y())
                ctrl_offset = seg_height * 0.5
                ctrl1 = QPointF(p0.x(), p0.y() + ctrl_offset)
                ctrl2 = QPointF(p1.x(), p1.y() - ctrl_offset)
                path.cubicTo(ctrl1, ctrl2, p1)

        self.setPath(path)

        pen = QPen(QColor(_EDGE_COLOR), 1.5)
        self.setPen(pen)

        # Arrowhead at target end — always points downward into target top-center
        end = points[-1]
        angle = math.pi / 2  # straight down
        arrow_p1 = QPointF(
            end.x() - _ARROWHEAD_SIZE * math.cos(angle - math.pi / 6),
            end.y() - _ARROWHEAD_SIZE * math.sin(angle - math.pi / 6),
        )
        arrow_p2 = QPointF(
            end.x() - _ARROWHEAD_SIZE * math.cos(angle + math.pi / 6),
            end.y() - _ARROWHEAD_SIZE * math.sin(angle + math.pi / 6),
        )
        arrow_polygon = QPolygonF([end, arrow_p1, arrow_p2])
        arrow_item = QGraphicsPolygonItem(arrow_polygon, self)
        arrow_item.setBrush(QBrush(QColor(_EDGE_COLOR)))
        arrow_item.setPen(QPen(QColor(_EDGE_COLOR), 1.0))

    def edge(self) -> LineageEdge:
        """Return the associated LineageEdge."""
        return self._edge
