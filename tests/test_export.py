"""T1 tests for lineage_viewer/export.py — DOT export (pure Python, no Qt)."""

from unittest.mock import MagicMock, patch

import pytest

from GeoLineage.lineage_retrieval.graph_builder import (
    LineageEdge,
    LineageGraph,
    LineageNode,
)
from GeoLineage.lineage_viewer.export import _path_to_id, export_dot


def _make_node(path, status="present", depth=0):
    return LineageNode(
        path=path,
        status=status,
        entries=(),
        filename=path.split("/")[-1],
        depth=depth,
        truncated=False,
    )


def _make_graph(nodes_dict, edges=(), root_path=""):
    return LineageGraph(
        nodes=nodes_dict,
        edges=tuple(edges),
        root_path=root_path,
    )


class TestExportDotBasic:
    def test_contains_digraph_keyword(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg")}
        graph = _make_graph(nodes)
        dot = export_dot(graph)
        assert "digraph" in dot

    def test_one_node_per_graph_node(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        graph = _make_graph(nodes)
        dot = export_dot(graph)
        assert 'label="a.gpkg"' in dot
        assert 'label="b.gpkg"' in dot

    def test_one_edge_per_graph_edge(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        edges = [LineageEdge("/a.gpkg", "/b.gpkg", 1)]
        graph = _make_graph(nodes, edges)
        dot = export_dot(graph)
        assert "->" in dot


class TestExportDotStatusColors:
    def test_present_green(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="present")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=green" in dot

    def test_missing_red(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="missing")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=red" in dot

    def test_modified_gold(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="modified")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=gold" in dot

    def test_raw_input_blue(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="raw_input")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=deepskyblue" in dot

    def test_busy_orange(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="busy")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=orange" in dot

    def test_unknown_status_gray(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", status="unknown_status")}
        dot = export_dot(_make_graph(nodes))
        assert "fillcolor=gray" in dot


class TestExportDotEmpty:
    def test_empty_graph_valid_digraph(self):
        graph = _make_graph({})
        dot = export_dot(graph)
        assert "digraph" in dot
        assert "{" in dot
        assert "}" in dot


class TestExportDotSyntax:
    def test_dot_syntax_valid(self):
        """Verify DOT output is syntactically reasonable."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges, "/c.gpkg")
        dot = export_dot(graph)

        # Must start with digraph and end with }
        lines = dot.strip().split("\n")
        assert lines[0].startswith("digraph")
        assert lines[-1].strip() == "}"

        # Count node definitions (lines with label=)
        node_lines = [line for line in lines if "label=" in line]
        assert len(node_lines) == 3

        # Count edge definitions (lines with ->)
        edge_lines = [line for line in lines if "->" in line]
        assert len(edge_lines) == 2

    def test_filename_with_quotes_escaped(self):
        """Filenames with quotes should be escaped in DOT labels."""
        nodes = {'/a"b.gpkg': _make_node('/a"b.gpkg')}
        dot = export_dot(_make_graph(nodes))
        # The quote should be escaped
        assert '\\"' in dot


class TestExportDotDanglingEdge:
    def test_edge_to_absent_node_does_not_crash(self):
        """An edge whose target is not in graph.nodes still exports cleanly."""
        nodes = {"/a.gpkg": _make_node("/a.gpkg")}
        edges = [LineageEdge("/a.gpkg", "/missing.gpkg", 1)]
        dot = export_dot(_make_graph(nodes, edges))

        # Edge is still emitted (by hashed ids); no exception.
        assert "->" in dot
        assert _path_to_id("/a.gpkg") in dot
        assert _path_to_id("/missing.gpkg") in dot


class TestPathToIdCollisions:
    def test_distinct_paths_distinct_ids(self):
        """Paths that previously collapsed to the same id now differ."""
        # Old char-substitution mapped both of these to 'n_a_b_gpkg'.
        id1 = _path_to_id("a/b.gpkg")
        id2 = _path_to_id("a_b.gpkg")
        assert id1 != id2

    def test_id_is_stable(self):
        assert _path_to_id("/data/x.gpkg") == _path_to_id("/data/x.gpkg")

    def test_id_is_valid_dot_identifier(self):
        node_id = _path_to_id("/some/weird path!.gpkg")
        assert node_id.startswith("n_")
        assert node_id[2:].isalnum()

    def test_export_dot_distinct_node_ids_for_colliding_paths(self):
        nodes = {
            "a/b.gpkg": _make_node("a/b.gpkg"),
            "a_b.gpkg": _make_node("a_b.gpkg"),
        }
        dot = export_dot(_make_graph(nodes))
        node_lines = [line for line in dot.splitlines() if "label=" in line]
        ids = [line.strip().split(" ")[0] for line in node_lines]
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# Export error surfacing (issue 2.2) — Qt mocked
# ---------------------------------------------------------------------------


def _make_qgis_export_mocks(*, painter_active=True, save_ok=True):
    """Build qgis.PyQt mock modules for export_svg/export_png."""
    painter_instance = MagicMock()
    painter_instance.isActive.return_value = painter_active
    qpainter = MagicMock(return_value=painter_instance)

    image_instance = MagicMock()
    image_instance.save.return_value = save_ok
    qimage = MagicMock(return_value=image_instance)

    qtgui = MagicMock()
    qtgui.QPainter = qpainter
    qtgui.QImage = qimage

    qtcore = MagicMock()
    qtsvg = MagicMock()

    pyqt = MagicMock()
    pyqt.QtCore = qtcore
    pyqt.QtGui = qtgui
    pyqt.QtSvg = qtsvg

    modules = {
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtCore": qtcore,
        "qgis.PyQt.QtGui": qtgui,
        "qgis.PyQt.QtSvg": qtsvg,
    }
    return modules


def _make_scene():
    scene = MagicMock()
    rect = MagicMock()
    rect.width.return_value = 100.0
    rect.height.return_value = 80.0
    scene.sceneRect.return_value = rect
    return scene


class TestExportErrorSurfacing:
    def test_export_svg_raises_when_painter_inactive(self):
        modules = _make_qgis_export_mocks(painter_active=False)
        with patch.dict("sys.modules", modules):
            from GeoLineage.lineage_viewer.export import export_svg

            with pytest.raises(OSError):
                export_svg(_make_scene(), "/some/out.svg")

    def test_export_png_raises_when_painter_inactive(self):
        modules = _make_qgis_export_mocks(painter_active=False)
        with patch.dict("sys.modules", modules):
            from GeoLineage.lineage_viewer.export import export_png

            with pytest.raises(OSError):
                export_png(_make_scene(), "/some/out.png")

    def test_export_png_raises_when_save_fails(self):
        modules = _make_qgis_export_mocks(painter_active=True, save_ok=False)
        with patch.dict("sys.modules", modules):
            from GeoLineage.lineage_viewer.export import export_png

            with pytest.raises(OSError):
                export_png(_make_scene(), "/some/out.png")

    def test_export_png_succeeds_when_save_ok(self):
        modules = _make_qgis_export_mocks(painter_active=True, save_ok=True)
        with patch.dict("sys.modules", modules):
            from GeoLineage.lineage_viewer.export import export_png

            # Must not raise.
            export_png(_make_scene(), "/some/out.png")
