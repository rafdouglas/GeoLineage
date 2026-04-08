"""Scene managing all node and edge items for a lineage graph."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..lineage_retrieval.graph_builder import LineageGraph

from .graph_layout import LayoutConfig


def _get_base_class():
    """Return QGraphicsScene at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QGraphicsScene

        return QGraphicsScene
    except ImportError:
        return object


class LineageGraphScene(_get_base_class()):
    """QGraphicsScene subclass managing lineage graph visualization.

    Inherits from QGraphicsScene at runtime to keep module importable
    without QApplication for static analysis.

    Signals (pyqtSignal):
        node_selected(str)       — node path when a node is clicked
        node_double_clicked(str) — node path on double-click
        expand_requested(str)    — node path when truncated node expand triggered
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Callbacks instead of pyqtSignal: pyqtSignal requires class-level
        # declaration with a QApplication, which would break T1 importability.
        self._on_node_selected = None
        self._on_node_double_clicked = None
        self._on_expand_requested = None

        self._node_items: dict[str, object] = {}
        self._edge_items: list[object] = []
        self._current_graph: LineageGraph | None = None
        self._config = LayoutConfig()

    def set_callbacks(
        self,
        on_node_selected=None,
        on_node_double_clicked=None,
        on_expand_requested=None,
    ) -> None:
        """Set callback functions for node interaction events."""
        self._on_node_selected = on_node_selected
        self._on_node_double_clicked = on_node_double_clicked
        self._on_expand_requested = on_expand_requested

    def set_graph(self, graph: LineageGraph) -> None:
        """Clear scene, run layout, create node/edge items."""
        from .graph_edge_item import GraphEdgeItem
        from .graph_layout import compute_layout
        from .graph_node_item import GraphNodeItem, compute_node_display_width

        self.clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._current_graph = graph

        if not graph.nodes:
            return

        # Pre-compute per-node display widths so the layout engine can
        # space nodes according to their actual rendered size.
        node_widths = {
            path: compute_node_display_width(node)
            for path, node in graph.nodes.items()
        }

        result = compute_layout(graph, self._config, node_widths=node_widths)
        selected_node = graph.root_path

        # Create node items
        for path, node in graph.nodes.items():
            pos = result.node_positions.get(path)
            if pos is None:
                continue
            item = GraphNodeItem(node, pos)
            if path == selected_node:
                item.set_selected_highlight(True)
            self.addItem(item)
            self._node_items[path] = item

        # Create edge items from edge_paths
        for edge_path in result.edge_paths:
            matching_edge = next(
                (e for e in graph.edges if e.parent_path == edge_path.source and e.child_path == edge_path.target),
                None,
            )
            if matching_edge is None:
                continue
            item = GraphEdgeItem(matching_edge, edge_path.waypoints, self._config)
            self.addItem(item)
            self._edge_items.append(item)

    def highlight_nodes(self, filename_pattern: str) -> None:
        """Highlight nodes whose filename matches pattern (case-insensitive substring).

        Empty pattern clears all highlights.
        """
        self.clear_highlights()
        if not filename_pattern:
            return
        pattern_lower = filename_pattern.lower()
        for item in self._node_items.values():
            if pattern_lower in item.node().filename.lower():
                item.set_highlighted(True)

    def clear_highlights(self) -> None:
        """Remove all search highlights."""
        for item in self._node_items.values():
            item.set_highlighted(False)

    def get_node_item(self, path: str):
        """Retrieve the GraphNodeItem for a given node path, or None."""
        return self._node_items.get(path)

    def fit_in_view(self):
        """Return the bounding rect of all items."""
        return self.itemsBoundingRect()

    def mousePressEvent(self, event) -> None:
        """Detect which GraphNodeItem was clicked and notify."""
        from qgis.PyQt.QtWidgets import QGraphicsScene

        QGraphicsScene.mousePressEvent(self, event)
        item = self.itemAt(
            event.scenePos(),
            self.views()[0].transform()
            if self.views()
            else __import__("qgis.PyQt.QtGui", fromlist=["QTransform"]).QTransform(),
        )
        node_item = self._find_node_item(item)
        if node_item and self._on_node_selected:
            self._on_node_selected(node_item.node().path)

    def mouseDoubleClickEvent(self, event) -> None:
        """Detect double-click on GraphNodeItem."""
        from qgis.PyQt.QtWidgets import QGraphicsScene

        QGraphicsScene.mouseDoubleClickEvent(self, event)
        item = self.itemAt(
            event.scenePos(),
            self.views()[0].transform()
            if self.views()
            else __import__("qgis.PyQt.QtGui", fromlist=["QTransform"]).QTransform(),
        )
        node_item = self._find_node_item(item)
        if node_item and self._on_node_double_clicked:
            self._on_node_double_clicked(node_item.node().path)

    def contextMenuEvent(self, event) -> None:
        """Show context menu on right-click."""
        from qgis.PyQt.QtGui import QTransform
        from qgis.PyQt.QtWidgets import QMenu

        transform = self.views()[0].transform() if self.views() else QTransform()
        item = self.itemAt(event.scenePos(), transform)
        node_item = self._find_node_item(item)
        if not node_item:
            return

        menu = QMenu()
        node = node_item.node()

        copy_action = menu.addAction("Copy path to clipboard")
        open_action = menu.addAction("Open file location")
        load_action = menu.addAction("Load in QGIS")

        expand_action = None
        if node.truncated:
            menu.addSeparator()
            expand_action = menu.addAction("Expand")

        chosen = menu.exec_(event.screenPos())
        if chosen == copy_action:
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.clipboard().setText(node.path)
        elif chosen == open_action:
            import os

            from qgis.PyQt.QtCore import QUrl
            from qgis.PyQt.QtGui import QDesktopServices

            folder = os.path.dirname(node.path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif chosen == load_action:
            if self._on_node_double_clicked:
                self._on_node_double_clicked(node.path)
        elif chosen == expand_action and self._on_expand_requested:
            self._on_expand_requested(node.path)

    def _find_node_item(self, item):
        """Walk up parent chain to find a GraphNodeItem."""
        from .graph_node_item import GraphNodeItem

        while item is not None:
            if isinstance(item, GraphNodeItem):
                return item
            item = item.parentItem()
        return None
