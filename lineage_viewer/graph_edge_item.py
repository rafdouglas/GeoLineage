"""Visual representation of an edge (parent -> child arrow) in the graph scene."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..lineage_retrieval.graph_builder import LineageEdge
    from .graph_layout import LayoutConfig

_EDGE_COLOR = "#666666"
_ARROWHEAD_SIZE = 8.0


def _interpolate_waypoints(
    source_pos: tuple[float, float],
    target_pos: tuple[float, float],
    original_waypoints: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Interpolate intermediate waypoint positions between endpoints.

    For a 2-point edge (no intermediates), returns [source_pos, target_pos].
    For multi-rank edges, each intermediate waypoint gets an interpolated
    x-coordinate (uniform spacing) and a proportionally interpolated
    y-coordinate that preserves the waypoint's relative position within the
    original y-span.  When the original y-span is zero, falls back to
    uniform y-interpolation.
    """
    if len(original_waypoints) <= 2:
        return [source_pos, target_pos]

    orig_src_y = original_waypoints[0][1]
    orig_tgt_y = original_waypoints[-1][1]
    orig_span_y = orig_tgt_y - orig_src_y

    result: list[tuple[float, float]] = [source_pos]
    n_intermediates = len(original_waypoints) - 2
    for i, wp in enumerate(original_waypoints[1:-1], start=1):
        t = i / (n_intermediates + 1)
        interp_x = source_pos[0] + (target_pos[0] - source_pos[0]) * t
        if orig_span_y != 0:
            t_y = (wp[1] - orig_src_y) / orig_span_y
            interp_y = source_pos[1] + (target_pos[1] - source_pos[1]) * t_y
        else:
            interp_y = source_pos[1] + (target_pos[1] - source_pos[1]) * t
        result.append((interp_x, interp_y))
    result.append(target_pos)
    return result


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
        from qgis.PyQt.QtGui import QColor, QPen

        super().__init__()

        self._edge = edge
        self._config = config
        self._waypoints: list[tuple[float, float]] = list(waypoints)
        self._source_node_item = None
        self._target_node_item = None
        self._arrow_item = None

        pen = QPen(QColor(_EDGE_COLOR), 1.5)
        self.setPen(pen)

        self._rebuild_path(
            source_pos=waypoints[0],
            target_pos=waypoints[-1],
            waypoints=waypoints,
        )

    def edge(self) -> LineageEdge:
        """Return the associated LineageEdge."""
        return self._edge

    def set_node_items(self, source_item, target_item) -> None:
        """Register source and target node items for live position tracking."""
        self._source_node_item = source_item
        self._target_node_item = target_item

    def set_waypoints(self, waypoints: Sequence[tuple[float, float]]) -> None:
        """Replace all waypoints and rebuild the path + arrowhead.

        Called by reset_layout() to restore original edge routing.
        """
        self._waypoints = list(waypoints)
        self._rebuild_path(
            source_pos=waypoints[0],
            target_pos=waypoints[-1],
            waypoints=waypoints,
        )

    def update_path(self) -> None:
        """Recalculate path from current node positions.

        For multi-rank edges, interpolates intermediate waypoint x-coordinates
        uniformly and y-coordinates proportionally between source and target.
        """
        if self._source_node_item is None or self._target_node_item is None:
            return

        src_rect = self._source_node_item.boundingRect()
        src_scene = self._source_node_item.scenePos()
        source_pos = (
            src_scene.x() + src_rect.width() / 2,
            src_scene.y() + src_rect.height(),
        )

        tgt_rect = self._target_node_item.boundingRect()
        tgt_scene = self._target_node_item.scenePos()
        target_pos = (
            tgt_scene.x() + tgt_rect.width() / 2,
            tgt_scene.y(),
        )

        new_waypoints = _interpolate_waypoints(source_pos, target_pos, self._waypoints)
        self._rebuild_path(source_pos, target_pos, new_waypoints)

    def _rebuild_path(
        self,
        source_pos: tuple[float, float],
        target_pos: tuple[float, float],
        waypoints: Sequence[tuple[float, float]],
    ) -> None:
        """Build QPainterPath + arrowhead from explicit positions."""
        import math

        from qgis.PyQt.QtCore import QPointF
        from qgis.PyQt.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
        from qgis.PyQt.QtWidgets import QGraphicsPolygonItem

        points = [QPointF(x, y) for x, y in waypoints]

        path = QPainterPath()
        path.moveTo(points[0])

        if len(points) == 2:
            ctrl_offset = self._config.vertical_gap * 0.5
            ctrl1 = QPointF(points[0].x(), points[0].y() + ctrl_offset)
            ctrl2 = QPointF(points[1].x(), points[1].y() - ctrl_offset)
            path.cubicTo(ctrl1, ctrl2, points[1])
        else:
            for i in range(len(points) - 1):
                p0 = points[i]
                p1 = points[i + 1]
                seg_height = abs(p1.y() - p0.y())
                ctrl_offset = seg_height * 0.5
                ctrl1 = QPointF(p0.x(), p0.y() + ctrl_offset)
                ctrl2 = QPointF(p1.x(), p1.y() - ctrl_offset)
                path.cubicTo(ctrl1, ctrl2, p1)

        self.setPath(path)

        # Remove old arrowhead if it exists
        if self._arrow_item is not None:
            self._arrow_item.setParentItem(None)
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self._arrow_item)
            self._arrow_item = None

        # Arrowhead at target end
        end = points[-1]
        angle = math.pi / 2
        arrow_p1 = QPointF(
            end.x() - _ARROWHEAD_SIZE * math.cos(angle - math.pi / 6),
            end.y() - _ARROWHEAD_SIZE * math.sin(angle - math.pi / 6),
        )
        arrow_p2 = QPointF(
            end.x() - _ARROWHEAD_SIZE * math.cos(angle + math.pi / 6),
            end.y() - _ARROWHEAD_SIZE * math.sin(angle + math.pi / 6),
        )
        arrow_polygon = QPolygonF([end, arrow_p1, arrow_p2])
        self._arrow_item = QGraphicsPolygonItem(arrow_polygon, self)
        self._arrow_item.setBrush(QBrush(QColor(_EDGE_COLOR)))
        self._arrow_item.setPen(QPen(QColor(_EDGE_COLOR), 1.0))
