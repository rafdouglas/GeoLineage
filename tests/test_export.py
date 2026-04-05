"""T1 tests for lineage_viewer/export.py — DOT export (pure Python, no Qt)."""

from GeoLineage.lineage_retrieval.graph_builder import (
    LineageEdge,
    LineageGraph,
    LineageNode,
)
from GeoLineage.lineage_viewer.export import export_dot


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
