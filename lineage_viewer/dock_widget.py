"""Top-level dock widget containing the lineage graph viewer."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ..lineage_core.settings import LOGGER_NAME

if TYPE_CHECKING:
    pass

logger = logging.getLogger(f"{LOGGER_NAME}.dock_widget")


def _get_dock_base():
    """Return QDockWidget at runtime to avoid import at module level."""
    from qgis.PyQt.QtWidgets import QDockWidget

    return QDockWidget


class LineageDockWidget(_get_dock_base()):
    """Dockable widget containing the lineage graph viewer.

    Layout:
        +-------------------------------------------+
        | ViewerToolbar                             |
        +-------------------------------------------+
        | QGraphicsView (scene) | DetailPanel       |
        | (left, ~70% width)   | (right, ~30%)     |
        +-------------------------------------------+
    """

    def __init__(self, iface, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import (
            QDockWidget,
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
        self._current_gpkg_path: str | None = None
        self._project_dir = ""
        self._current_max_depth = 5

        # Create components
        from .detail_panel import DetailPanel
        from .graph_scene import LineageGraphScene
        from .toolbar import ViewerToolbar

        self._scene = LineageGraphScene()
        self._view = _LineageGraphView(self._scene)
        self._view.setRenderHints(self._view.renderHints())

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
            on_reload=self._on_reload,
            on_reset_layout=self._scene.reset_layout,
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
        self._current_gpkg_path = gpkg_path
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

    def _on_reload(self) -> None:
        """Reload the lineage graph from the current path."""
        if self._current_gpkg_path and self._project_dir:
            self.show_lineage(self._current_gpkg_path, self._project_dir)

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
        """Load a GeoPackage file as a layer in QGIS.

        A GeoPackage may hold several tables; loading the bare path lets OGR
        pick one arbitrarily. Enumerate the sub-layers and load a specific
        table by name so the user gets the layer they expect.
        """
        from qgis.core import QgsProject, QgsVectorLayer

        if not os.path.isfile(path):
            self._iface.messageBar().pushWarning("GeoLineage", f"File not found: {path}")
            return

        table_names = self._list_gpkg_tables(path)
        if len(table_names) > 1:
            chosen = table_names[0]
            self._iface.messageBar().pushWarning(
                "GeoLineage",
                f"'{os.path.basename(path)}' contains multiple tables ({', '.join(table_names)}); loading '{chosen}'.",
            )
            uri, name = f"{path}|layername={chosen}", chosen
        elif len(table_names) == 1:
            uri, name = f"{path}|layername={table_names[0]}", table_names[0]
        else:
            uri, name = path, os.path.basename(path)

        layer = QgsVectorLayer(uri, name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
        else:
            self._iface.messageBar().pushWarning("GeoLineage", f"Could not load layer: {path}")

    @staticmethod
    def _list_gpkg_tables(path: str) -> list[str]:
        """Return the vector table names in a GeoPackage, best-effort.

        Uses QgsProviderRegistry.querySublayers when available; on any failure
        returns an empty list so the caller falls back to a plain path load.
        """
        try:
            from qgis.core import QgsProviderRegistry

            sublayers = QgsProviderRegistry.instance().querySublayers(path)
            return [s.name() for s in sublayers if s.name()]
        except Exception:
            logger.debug("Could not enumerate sub-layers for %s", path, exc_info=True)
            return []

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
                self._write_export(path, lambda: self._write_text(path, export_dot(self._current_graph)))
        elif fmt == "svg":
            from .export import export_svg

            path, _ = QFileDialog.getSaveFileName(self, "Export SVG", "", "SVG files (*.svg)")
            if path:
                self._write_export(path, lambda: export_svg(self._scene, path))
        elif fmt == "png":
            from .export import export_png

            path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "", "PNG files (*.png)")
            if path:
                self._write_export(path, lambda: export_png(self._scene, path))

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        with open(path, "w") as f:
            f.write(content)

    def _write_export(self, path: str, do_write) -> None:
        """Run an export writer, surfacing any failure to the message bar."""
        try:
            do_write()
        except Exception:
            logger.exception("Export to %s failed", path)
            self._iface.messageBar().pushWarning("GeoLineage", f"Export failed: could not write {path}")
        else:
            self._iface.messageBar().pushInfo("GeoLineage", f"Exported to {path}")


def _get_view_base():
    """Return QGraphicsView at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QGraphicsView

        return QGraphicsView
    except ImportError:
        return object


class _LineageGraphView(_get_view_base()):  # noqa: F811
    """QGraphicsView with right-click-drag pan (GIS convention).

    Left-click drag is handled by Qt's ItemIsMovable on GraphNodeItem.
    Right-click-drag pans the view. Right-click without movement (< 4px)
    lets the context menu fire normally.
    """

    def __init__(self, scene, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QGraphicsView

        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.OpenHandCursor)
        self._panning = False
        self._pan_start = None
        self._pan_origin = None

    def mousePressEvent(self, event) -> None:
        from qgis.PyQt.QtCore import Qt

        if event.button() == Qt.RightButton:
            self._panning = True
            self._pan_start = event.pos()
            # Remember where the press began so the drag/context-menu decision
            # compares net displacement, not speed-dependent accumulated deltas.
            self._pan_origin = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._pan_start = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        from qgis.PyQt.QtCore import Qt

        if event.button() == Qt.RightButton and self._panning:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor)
            moved = (event.pos() - self._pan_origin).manhattanLength() if self._pan_origin is not None else 0
            if moved < 4:
                # No real drag -- let context menu fire
                super().mouseReleaseEvent(event)
            else:
                event.accept()
        else:
            super().mouseReleaseEvent(event)


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
