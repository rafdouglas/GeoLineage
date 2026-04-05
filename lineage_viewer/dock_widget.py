"""Top-level dock widget containing the lineage graph viewer."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ..lineage_core.settings import LOGGER_NAME

if TYPE_CHECKING:
    pass

logger = logging.getLogger(f"{LOGGER_NAME}.dock_widget")


class LineageDockWidget:
    """Dockable widget containing the lineage graph viewer.

    Inherits from QDockWidget at runtime.

    Layout:
        +-------------------------------------------+
        | ViewerToolbar                             |
        +-------------------------------------------+
        | QGraphicsView (scene) | DetailPanel       |
        | (left, ~70% width)   | (right, ~30%)     |
        +-------------------------------------------+
    """

    def __new__(cls, *args, **kwargs):
        from qgis.PyQt.QtWidgets import QDockWidget

        if not issubclass(cls, QDockWidget):
            cls.__bases__ = (QDockWidget,)
        return super().__new__(cls)

    def __init__(self, iface, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import (
            QDockWidget,
            QGraphicsView,
            QSplitter,
            QVBoxLayout,
            QWidget,
        )

        QDockWidget.__init__(self, "Lineage Graph Viewer", parent)
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
        )

        self._iface = iface
        self._current_graph = None
        self._project_dir = ""
        self._current_max_depth = 5

        # Create components
        from .detail_panel import DetailPanel
        from .graph_scene import LineageGraphScene
        from .toolbar import ViewerToolbar

        self._scene = LineageGraphScene()
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(self._view.renderHints())
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)

        self._detail_panel = DetailPanel()
        self._toolbar = ViewerToolbar()

        # Layout
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._view)
        splitter.addWidget(self._detail_panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter)

        self.setWidget(container)

        # Wire callbacks
        self._toolbar.set_callbacks(
            on_fit=self._on_fit_to_view,
            on_zoom_in=self._on_zoom_in,
            on_zoom_out=self._on_zoom_out,
            on_search_changed=self._scene.highlight_nodes,
            on_export=self._on_export,
        )

        self._scene.set_callbacks(
            on_node_selected=self._on_node_selected,
            on_node_double_clicked=self._on_load_layer,
            on_expand_requested=self.expand_node,
        )

        self._detail_panel.set_on_parent_clicked(self._on_parent_clicked)

    def show_lineage(self, gpkg_path: str, project_dir: str) -> None:
        """Build graph from path, display in scene."""
        from ..lineage_retrieval.graph_builder import build_graph

        gpkg_path = os.path.abspath(gpkg_path)
        self._project_dir = project_dir
        self._current_max_depth = 5

        if not os.path.isfile(gpkg_path):
            self._iface.messageBar().pushWarning("GeoLineage", f"File not found: {gpkg_path}")
            return

        try:
            graph = build_graph(gpkg_path, project_dir, max_depth=self._current_max_depth)
            self._current_graph = graph
            self._scene.set_graph(graph)
            self._on_fit_to_view()
        except Exception:
            logger.exception("Failed to build lineage graph")
            self._iface.messageBar().pushCritical("GeoLineage", f"Failed to build lineage graph for {gpkg_path}")

    def expand_node(self, node_path: str) -> None:
        """Expand a truncated node by merging deeper results."""
        from ..lineage_retrieval.graph_builder import build_graph

        if self._current_graph is None:
            return

        new_depth = self._current_max_depth + 5
        try:
            sub_graph = build_graph(node_path, self._project_dir, max_depth=new_depth)
        except Exception:
            logger.exception("Failed to expand node %s", node_path)
            return

        # Save view transform
        transform = self._view.transform()
        h_scroll = self._view.horizontalScrollBar().value()
        v_scroll = self._view.verticalScrollBar().value()

        merged = _merge_graphs(self._current_graph, sub_graph)
        self._current_graph = merged
        self._current_max_depth = new_depth
        self._scene.set_graph(merged)

        # Restore view transform
        self._view.setTransform(transform)
        self._view.horizontalScrollBar().setValue(h_scroll)
        self._view.verticalScrollBar().setValue(v_scroll)

        # Center on expanded node
        node_item = self._scene.get_node_item(node_path)
        if node_item:
            self._view.centerOn(node_item)

    def _on_fit_to_view(self) -> None:
        from qgis.PyQt.QtCore import Qt

        rect = self._scene.fit_in_view()
        if not rect.isNull():
            self._view.fitInView(rect, Qt.KeepAspectRatio)

    def _on_zoom_in(self) -> None:
        self._view.scale(1.2, 1.2)

    def _on_zoom_out(self) -> None:
        self._view.scale(1 / 1.2, 1 / 1.2)

    def _on_node_selected(self, path: str) -> None:
        if self._current_graph and path in self._current_graph.nodes:
            self._detail_panel.set_node(self._current_graph.nodes[path])

    def _on_load_layer(self, path: str) -> None:
        """Load a GeoPackage file as a layer in QGIS."""
        from qgis.core import QgsVectorLayer

        if not os.path.isfile(path):
            self._iface.messageBar().pushWarning("GeoLineage", f"File not found: {path}")
            return

        layer = QgsVectorLayer(path, os.path.basename(path), "ogr")
        if layer.isValid():
            from qgis.core import QgsProject

            QgsProject.instance().addMapLayer(layer)
        else:
            self._iface.messageBar().pushWarning("GeoLineage", f"Could not load layer: {path}")

    def _on_parent_clicked(self, parent_path: str) -> None:
        """Handle click on a parent in the detail panel."""
        node_item = self._scene.get_node_item(parent_path)
        if node_item:
            node_item.setSelected(True)
            self._view.centerOn(node_item)
            self._on_node_selected(parent_path)
        else:
            self._iface.messageBar().pushInfo(
                "GeoLineage",
                f"Parent '{os.path.basename(parent_path)}' is not in the current graph. Try expanding truncated nodes.",
            )

    def _on_export(self, fmt: str) -> None:
        """Handle export request."""
        from qgis.PyQt.QtWidgets import QFileDialog

        if self._current_graph is None:
            return

        if fmt == "dot":
            from .export import export_dot

            path, _ = QFileDialog.getSaveFileName(self, "Export DOT", "", "DOT files (*.dot)")
            if path:
                dot_content = export_dot(self._current_graph)
                with open(path, "w") as f:
                    f.write(dot_content)
        elif fmt == "svg":
            from .export import export_svg

            path, _ = QFileDialog.getSaveFileName(self, "Export SVG", "", "SVG files (*.svg)")
            if path:
                export_svg(self._scene, path)
        elif fmt == "png":
            from .export import export_png

            path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "", "PNG files (*.png)")
            if path:
                export_png(self._scene, path)


def _merge_graphs(base, extension):
    """Merge two LineageGraphs for expand_node.

    Union of nodes: for duplicates, keep the node with the shallower depth;
    update truncated=False if the extension resolves it.
    Union of edges: deduplicate by (parent_path, child_path, entry_id).
    Keep the original root_path.
    """
    from ..lineage_retrieval.graph_builder import LineageGraph

    merged_nodes = dict(base.nodes)
    for path, node in extension.nodes.items():
        if path in merged_nodes:
            existing = merged_nodes[path]
            if node.depth < existing.depth:
                merged_nodes[path] = node
            elif not node.truncated and existing.truncated:
                # Replace with non-truncated version at same depth
                merged_nodes[path] = node
        else:
            merged_nodes[path] = node

    # Deduplicate edges
    seen_edges: set[tuple[str, str, int]] = set()
    merged_edges = []
    for edge in list(base.edges) + list(extension.edges):
        key = (edge.parent_path, edge.child_path, edge.entry_id)
        if key not in seen_edges:
            seen_edges.add(key)
            merged_edges.append(edge)

    return LineageGraph(
        nodes=merged_nodes,
        edges=tuple(merged_edges),
        root_path=base.root_path,
    )
