"""Visual representation of a single lineage node in the graph scene."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.PyQt.QtWidgets import QGraphicsItem

    from ..lineage_retrieval.graph_builder import LineageNode
    from .graph_layout import NodePosition


# Status -> color mapping (module-level constant)
STATUS_COLORS: dict[str, str] = {
    "present": "#4CAF50",
    "modified": "#FFC107",
    "missing": "#F44336",
    "raw_input": "#2196F3",
    "busy": "#FF9800",
}

_HIGHLIGHT_COLOR = "#FFEB3B"
_SELECTED_COLOR = "#FF6F00"
_DEFAULT_NODE_WIDTH = 180.0
_DEFAULT_NODE_HEIGHT = 60.0
_HORIZONTAL_PADDING = 16.0
_VERTICAL_PADDING = 16.0
_MIN_NODE_WIDTH = 120.0
_MIN_NODE_HEIGHT = 50.0


def _get_operation_text(node: LineageNode) -> str:
    """Get operation tool text from node entries."""
    if not node.entries:
        return ""
    tools = {e.get("operation_tool", "") for e in node.entries if e.get("operation_tool")}
    if len(tools) == 1:
        return tools.pop()
    if len(tools) > 1:
        return "Multiple operations"
    return ""


def compute_node_display_width(node: LineageNode) -> float:
    """Compute the display width for a node using Qt font metrics.

    This is the single source of truth for node width, used by both
    the layout engine (for spacing) and ``GraphNodeItem`` (for rendering).
    Requires a running QApplication.
    """
    from qgis.PyQt.QtGui import QFont
    from qgis.PyQt.QtWidgets import QGraphicsSimpleTextItem

    font_bold = QFont("Sans", 9)
    font_bold.setBold(True)

    display_name = node.filename.removesuffix(".gpkg")
    temp_text = QGraphicsSimpleTextItem(display_name)
    temp_text.setFont(font_bold)
    filename_width = temp_text.boundingRect().width()

    op_text = _get_operation_text(node)
    op_width = 0.0
    if op_text:
        font_small = QFont("Sans", 7)
        temp_op = QGraphicsSimpleTextItem(op_text)
        temp_op.setFont(font_small)
        op_width = temp_op.boundingRect().width()

    needed_width = max(filename_width, op_width) + _HORIZONTAL_PADDING
    return max(needed_width, _MIN_NODE_WIDTH)


def _get_base_class():
    """Return QGraphicsPathItem at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QGraphicsPathItem

        return QGraphicsPathItem
    except ImportError:
        return object


class GraphNodeItem(_get_base_class()):
    """Rounded rectangle representing a lineage node.

    Inherits from QGraphicsPathItem at runtime. Declared without
    Qt base class at module level so the module can be imported
    in T1 tests (no QApplication needed for import).
    """

    def __init__(
        self,
        node: LineageNode,
        position: NodePosition,
        parent_item: QGraphicsItem | None = None,
    ) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
        from qgis.PyQt.QtWidgets import QGraphicsSimpleTextItem

        super().__init__(parent_item)

        self._node = node
        self._position = position
        self._highlighted = False
        self._selected = False

        # Use the width assigned by the layout engine (single source of truth)
        node_width = position.width
        node_height = _DEFAULT_NODE_HEIGHT

        # Strip .gpkg extension for cleaner display
        display_name = node.filename.removesuffix(".gpkg")

        # Font for filename label
        font_bold = QFont("Sans", 9)
        font_bold.setBold(True)

        # Measure filename width for centering
        temp_text = QGraphicsSimpleTextItem(display_name)
        temp_text.setFont(font_bold)
        filename_width = temp_text.boundingRect().width()

        # Measure operation text width for centering
        op_text = _get_operation_text(node)
        op_width = 0.0
        if op_text:
            font_small = QFont("Sans", 7)
            temp_op = QGraphicsSimpleTextItem(op_text)
            temp_op.setFont(font_small)
            op_width = temp_op.boundingRect().width()

        # Build rounded rect path with calculated size
        path = QPainterPath()
        path.addRoundedRect(0, 0, node_width, node_height, 8.0, 8.0)
        self.setPath(path)

        # Position
        self.setPos(position.x, position.y)

        # Fill color by status
        color = STATUS_COLORS.get(node.status, "#9E9E9E")
        self.setBrush(QBrush(QColor(color)))

        # Border
        pen = QPen(QColor("#333333"), 1.5)
        if node.truncated:
            pen.setStyle(Qt.DashLine)
        self.setPen(pen)
        self._default_pen = QPen(pen)

        # Filename label (bold, centered)
        filename_item = QGraphicsSimpleTextItem(display_name, self)
        filename_item.setFont(font_bold)
        # Center horizontally
        text_x = (node_width - filename_width) / 2
        filename_item.setPos(max(4, text_x), 8)

        # Operation tool label (smaller, below filename)
        if op_text:
            font_small = QFont("Sans", 7)
            op_item = QGraphicsSimpleTextItem(op_text, self)
            op_item.setFont(font_small)
            op_item.setBrush(QBrush(QColor("#555555")))
            op_x = (node_width - op_width) / 2
            op_item.setPos(max(4, op_x), 32)

        # Truncation indicator
        if node.truncated:
            trunc_item = QGraphicsSimpleTextItem("...", self)
            trunc_item.setFont(QFont("Sans", 10))
            trunc_item.setPos(node_width - 20, node_height - 18)

        # Interaction flags
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, True)
        self.setFlag(self.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        # Drag state
        self._connected_edges: list = []
        self._drag_started = False
        self._original_z = 0.0
        self._shift_axis: str | None = None
        self._drag_origin: tuple[float, float] | None = None

        # Tooltip
        tooltip_lines = [
            f"Path: {node.path}",
            f"Status: {node.status}",
            f"Entries: {len(node.entries)}",
        ]
        if node.entries:
            first = node.entries[0]
            crs = first.get("crs", "")
            if crs:
                tooltip_lines.append(f"CRS: {crs}")
        self.setToolTip("\n".join(tooltip_lines))

    @staticmethod
    def _get_operation_text(node: LineageNode) -> str:
        """Get operation tool text from node entries."""
        return _get_operation_text(node)

    def node(self) -> LineageNode:
        """Return the associated LineageNode."""
        return self._node

    def add_connected_edge(self, edge_item) -> None:
        """Register an edge that should update when this node moves."""
        self._connected_edges.append(edge_item)

    def itemChange(self, change, value):
        """Handle position changes for drag: z-ordering, Shift-constrain, edge updates."""
        if change == self.ItemPositionChange:
            if not self._drag_started:
                self._drag_started = True
                self._original_z = self.zValue()
                self.setZValue(self._original_z + 1)
                self._drag_origin = (self.pos().x(), self.pos().y())
                self._shift_axis = None

            from qgis.PyQt.QtCore import Qt
            from qgis.PyQt.QtWidgets import QApplication

            if QApplication.queryKeyboardModifiers() & Qt.ShiftModifier:
                if self._drag_origin is not None:
                    dx = abs(value.x() - self._drag_origin[0])
                    dy = abs(value.y() - self._drag_origin[1])
                    if self._shift_axis is None and (dx > 4 or dy > 4):
                        self._shift_axis = "h" if dx >= dy else "v"
                    if self._shift_axis == "h":
                        value.setY(self._drag_origin[1])
                    elif self._shift_axis == "v":
                        value.setX(self._drag_origin[0])
            else:
                self._shift_axis = None

        elif change == self.ItemPositionHasChanged:
            for edge in self._connected_edges:
                edge.update_path()

        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        """Restore z-order and reset drag state after drag ends."""
        if self._drag_started:
            self._drag_started = False
            self.setZValue(self._original_z)
            self._shift_axis = None
            self._drag_origin = None
        super().mouseReleaseEvent(event)

    def set_highlighted(self, highlighted: bool) -> None:
        """Toggle search-highlight border (thick blue outline)."""
        self._highlighted = highlighted
        self._update_pen()

    def set_selected_highlight(self, selected: bool) -> None:
        """Toggle selected-node highlight (thick amber outline)."""
        self._selected = selected
        self._update_pen()

    def _update_pen(self) -> None:
        """Apply pen based on precedence: selected > highlighted > default."""
        from qgis.PyQt.QtGui import QColor, QPen

        if self._selected:
            self.setPen(QPen(QColor(_SELECTED_COLOR), 3.0))
        elif self._highlighted:
            self.setPen(QPen(QColor(_HIGHLIGHT_COLOR), 3.0))
        else:
            self.setPen(self._default_pen)
