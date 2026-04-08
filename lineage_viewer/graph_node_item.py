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

        # Build rounded rect path
        path = QPainterPath()
        path.addRoundedRect(0, 0, _DEFAULT_NODE_WIDTH, _DEFAULT_NODE_HEIGHT, 8.0, 8.0)
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
        font_bold = QFont("Sans", 9)
        font_bold.setBold(True)
        # Strip .gpkg extension for cleaner display
        display_name = node.filename.removesuffix(".gpkg")
        filename_item = QGraphicsSimpleTextItem(display_name, self)
        filename_item.setFont(font_bold)
        # Center horizontally
        text_width = filename_item.boundingRect().width()
        text_x = (_DEFAULT_NODE_WIDTH - text_width) / 2
        filename_item.setPos(max(4, text_x), 8)

        # Operation tool label (smaller, below filename)
        op_text = self._get_operation_text(node)
        if op_text:
            font_small = QFont("Sans", 7)
            op_item = QGraphicsSimpleTextItem(op_text, self)
            op_item.setFont(font_small)
            op_item.setBrush(QBrush(QColor("#555555")))
            op_width = op_item.boundingRect().width()
            op_x = (_DEFAULT_NODE_WIDTH - op_width) / 2
            op_item.setPos(max(4, op_x), 32)

        # Truncation indicator
        if node.truncated:
            trunc_item = QGraphicsSimpleTextItem("...", self)
            trunc_item.setFont(QFont("Sans", 10))
            trunc_item.setPos(_DEFAULT_NODE_WIDTH - 20, _DEFAULT_NODE_HEIGHT - 18)

        # Interaction flags
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)

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
        if not node.entries:
            return ""
        tools = {e.get("operation_tool", "") for e in node.entries if e.get("operation_tool")}
        if len(tools) == 1:
            return tools.pop()
        if len(tools) > 1:
            return "Multiple operations"
        return ""

    def node(self) -> LineageNode:
        """Return the associated LineageNode."""
        return self._node

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
