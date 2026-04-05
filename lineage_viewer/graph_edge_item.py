"""Visual representation of an edge (parent -> child arrow) in the graph scene."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..lineage_retrieval.graph_builder import LineageEdge
    from .graph_layout import LayoutConfig, NodePosition

_EDGE_COLOR = "#666666"
_ARROWHEAD_SIZE = 8.0
_DEFAULT_NODE_WIDTH = 180.0
_DEFAULT_NODE_HEIGHT = 60.0


class GraphEdgeItem:
    """Bezier curve arrow from parent node to child node.

    Inherits from QGraphicsPathItem at runtime. Declared without
    Qt base class at module level so the module can be imported
    in T1 tests (no QApplication needed for import).
    """

    def __new__(cls, *args, **kwargs):
        from qgis.PyQt.QtWidgets import QGraphicsPathItem

        if not issubclass(cls, QGraphicsPathItem):
            cls.__bases__ = (QGraphicsPathItem,)
        return super().__new__(cls)

    def __init__(
        self,
        edge: LineageEdge,
        parent_pos: NodePosition,
        child_pos: NodePosition,
        config: LayoutConfig,
    ) -> None:
        import math

        from qgis.PyQt.QtCore import QPointF
        from qgis.PyQt.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
        from qgis.PyQt.QtWidgets import QGraphicsPathItem, QGraphicsPolygonItem

        QGraphicsPathItem.__init__(self)

        self._edge = edge

        node_w = config.node_width
        node_h = config.node_height

        # Start: bottom-center of parent
        start = QPointF(
            parent_pos.x + node_w / 2,
            parent_pos.y + node_h,
        )
        # End: top-center of child
        end = QPointF(
            child_pos.x + node_w / 2,
            child_pos.y,
        )

        # Control points offset vertically by 50% of vertical_gap
        ctrl_offset = config.vertical_gap * 0.5
        ctrl1 = QPointF(start.x(), start.y() + ctrl_offset)
        ctrl2 = QPointF(end.x(), end.y() - ctrl_offset)

        # Build bezier path
        path = QPainterPath()
        path.moveTo(start)
        path.cubicTo(ctrl1, ctrl2, end)
        self.setPath(path)

        pen = QPen(QColor(_EDGE_COLOR), 1.5)
        self.setPen(pen)

        # Arrowhead at child end (small filled triangle)
        angle = math.atan2(end.y() - ctrl2.y(), end.x() - ctrl2.x())
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
