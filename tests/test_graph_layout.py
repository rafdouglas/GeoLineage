"""T1 tests for lineage_viewer/graph_layout.py — pure Python, no Qt."""

import logging
import time

from GeoLineage.lineage_retrieval.graph_builder import (
    LineageEdge,
    LineageGraph,
    LineageNode,
)
from GeoLineage.lineage_viewer.graph_layout import (
    EdgePath,
    LayoutConfig,
    LayoutResult,
    NodePosition,
    compute_layout,
    layout_graph,
)


def _make_node(path, depth=0, status="present", truncated=False):
    return LineageNode(
        path=path,
        status=status,
        entries=(),
        filename=path.split("/")[-1],
        depth=depth,
        truncated=truncated,
    )


def _make_graph(nodes_dict, edges=(), root_path=""):
    return LineageGraph(
        nodes=nodes_dict,
        edges=tuple(edges),
        root_path=root_path,
    )


def _assert_no_overlap(positions: dict[str, NodePosition], config: LayoutConfig):
    """Assert no two node bounding boxes overlap."""
    pos_list = list(positions.values())
    for i in range(len(pos_list)):
        for j in range(i + 1, len(pos_list)):
            a = pos_list[i]
            b = pos_list[j]
            a_right = a.x + config.node_width
            b_right = b.x + config.node_width
            a_bottom = a.y + config.node_height
            b_bottom = b.y + config.node_height

            x_overlap = a.x < b_right and b.x < a_right
            y_overlap = a.y < b_bottom and b.y < a_bottom

            assert not (x_overlap and y_overlap), f"Nodes overlap: ({a.x},{a.y}) and ({b.x},{b.y})"


class TestComputeLayoutEmpty:
    def test_empty_graph_returns_empty_result(self):
        graph = _make_graph({})
        result = compute_layout(graph)
        assert isinstance(result, LayoutResult)
        assert result.node_positions == {}
        assert result.edge_paths == ()


class TestComputeLayoutSingleNode:
    def test_single_node_at_rank_zero(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", depth=0)}
        graph = _make_graph(nodes, root_path="/a.gpkg")
        result = compute_layout(graph)
        assert len(result.node_positions) == 1
        pos = result.node_positions["/a.gpkg"]
        assert pos.layer == 0
        assert pos.order == 0
        # Single node centered at x=0
        assert pos.x == 0.0
        assert pos.y == 0.0


class TestRankAssignment:
    """Ranks come from DAG structure (longest-path from roots), NOT node.depth."""

    def test_chain_a_b_c(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=99),
            "/b.gpkg": _make_node("/b.gpkg", depth=99),
            "/c.gpkg": _make_node("/c.gpkg", depth=99),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/b.gpkg"].layer == 1
        assert result.node_positions["/c.gpkg"].layer == 2

    def test_diamond(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=99),
            "/b.gpkg": _make_node("/b.gpkg", depth=99),
            "/c.gpkg": _make_node("/c.gpkg", depth=99),
            "/d.gpkg": _make_node("/d.gpkg", depth=99),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/a.gpkg", "/c.gpkg", 2),
            LineageEdge("/b.gpkg", "/d.gpkg", 3),
            LineageEdge("/c.gpkg", "/d.gpkg", 4),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/b.gpkg"].layer == 1
        assert result.node_positions["/c.gpkg"].layer == 1
        assert result.node_positions["/d.gpkg"].layer == 2

    def test_fan_out(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
            "/d.gpkg": _make_node("/d.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/a.gpkg", "/c.gpkg", 2),
            LineageEdge("/a.gpkg", "/d.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/b.gpkg"].layer == 1
        assert result.node_positions["/c.gpkg"].layer == 1
        assert result.node_positions["/d.gpkg"].layer == 1

    def test_fan_in(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/c.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/b.gpkg"].layer == 0
        assert result.node_positions["/c.gpkg"].layer == 1

    def test_multi_level_skip(self):
        """A->B->C and A->C: C must be at rank 2 (longest path)."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
            LineageEdge("/a.gpkg", "/c.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/b.gpkg"].layer == 1
        assert result.node_positions["/c.gpkg"].layer == 2


class TestDummyNodeInsertion:
    def test_skip_edge_produces_extra_waypoints(self):
        """Edge A->C skipping rank 1 should produce EdgePath with 3+ waypoints."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
            LineageEdge("/a.gpkg", "/c.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)

        # Find the A->C edge path
        skip_path = next(ep for ep in result.edge_paths if ep.source == "/a.gpkg" and ep.target == "/c.gpkg")
        # Should have 3+ waypoints: source exit, dummy center, target entry
        assert len(skip_path.waypoints) >= 3

    def test_no_dummy_nodes_in_positions(self):
        """Dummy nodes must not appear in node_positions."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
            LineageEdge("/a.gpkg", "/c.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        for key in result.node_positions:
            assert not key.startswith("__dummy__"), f"Dummy node {key} leaked into positions"


class TestCrossingMinimisation:
    def test_barycenter_reduces_crossings(self):
        """A->D, B->C: barycenter should reorder to reduce crossings."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
            "/d.gpkg": _make_node("/d.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/d.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)

        a_order = result.node_positions["/a.gpkg"].order
        b_order = result.node_positions["/b.gpkg"].order
        c_order = result.node_positions["/c.gpkg"].order
        d_order = result.node_positions["/d.gpkg"].order

        if a_order < b_order:
            assert d_order < c_order, "Barycenter should reduce edge crossings"
        else:
            assert c_order < d_order, "Barycenter should reduce edge crossings"


class TestEdgePaths:
    def test_single_rank_edge_has_two_waypoints(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        edges = [LineageEdge("/a.gpkg", "/b.gpkg", 1)]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)

        assert len(result.edge_paths) == 1
        ep = result.edge_paths[0]
        assert ep.source == "/a.gpkg"
        assert ep.target == "/b.gpkg"
        assert len(ep.waypoints) == 2

    def test_edge_path_source_target_match_original(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        edges = [LineageEdge("/a.gpkg", "/b.gpkg", 1)]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        ep = result.edge_paths[0]
        assert isinstance(ep, EdgePath)
        assert ep.source == "/a.gpkg"
        assert ep.target == "/b.gpkg"

    def test_waypoints_ordered_top_to_bottom(self):
        """Waypoints should go from lower y (source) to higher y (target)."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        edges = [LineageEdge("/a.gpkg", "/b.gpkg", 1)]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        ep = result.edge_paths[0]
        assert ep.waypoints[0][1] < ep.waypoints[-1][1]


class TestBackwardCompat:
    def test_layout_graph_returns_dict(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg")}
        graph = _make_graph(nodes, root_path="/a.gpkg")
        result = layout_graph(graph)
        assert isinstance(result, dict)
        assert "/a.gpkg" in result
        assert isinstance(result["/a.gpkg"], NodePosition)

    def test_layout_graph_empty(self):
        graph = _make_graph({})
        result = layout_graph(graph)
        assert result == {}


class TestLayoutConfig:
    def test_custom_config_affects_spacing(self):
        config = LayoutConfig(
            node_width=100,
            node_height=40,
            horizontal_gap=20,
            vertical_gap=50,
        )
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        # Both are roots (no edges), so both at rank 0
        graph = _make_graph(nodes)
        result = compute_layout(graph, config)

        positions_rank0 = [pos for pos in result.node_positions.values() if pos.layer == 0]
        xs = sorted(pos.x for pos in positions_rank0)
        assert len(xs) == 2
        assert xs[1] - xs[0] == 100 + 20  # node_width + horizontal_gap

    def test_node_position_is_frozen(self):
        pos = NodePosition(x=1.0, y=2.0, layer=0, order=0)
        try:
            pos.x = 5.0  # type: ignore[misc]
            assert False, "NodePosition should be frozen"
        except AttributeError:
            pass

    def test_edge_path_is_frozen(self):
        ep = EdgePath(source="a", target="b", waypoints=((0.0, 0.0), (1.0, 1.0)))
        try:
            ep.source = "c"  # type: ignore[misc]
            assert False, "EdgePath should be frozen"
        except AttributeError:
            pass

    def test_layout_result_is_frozen(self):
        lr = LayoutResult(node_positions={}, edge_paths=())
        try:
            lr.node_positions = {}  # type: ignore[misc]
            assert False, "LayoutResult should be frozen"
        except AttributeError:
            pass


class TestNoOverlap:
    def test_ten_wide_no_overlap(self):
        nodes = {f"/n{i}.gpkg": _make_node(f"/n{i}.gpkg") for i in range(10)}
        graph = _make_graph(nodes)
        config = LayoutConfig()
        result = compute_layout(graph, config)
        assert len(result.node_positions) == 10
        _assert_no_overlap(result.node_positions, config)

    def test_50_chain_no_overlap(self):
        nodes = {}
        edges = []
        for i in range(50):
            path = f"/node{i}.gpkg"
            nodes[path] = _make_node(path, depth=i)
            if i > 0:
                prev = f"/node{i - 1}.gpkg"
                edges.append(LineageEdge(prev, path, i))
        graph = _make_graph(nodes, edges)
        config = LayoutConfig()
        result = compute_layout(graph, config)
        assert len(result.node_positions) == 50
        _assert_no_overlap(result.node_positions, config)

    def test_diamond_no_overlap(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
            "/d.gpkg": _make_node("/d.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/a.gpkg", "/c.gpkg", 2),
            LineageEdge("/b.gpkg", "/d.gpkg", 3),
            LineageEdge("/c.gpkg", "/d.gpkg", 4),
        ]
        graph = _make_graph(nodes, edges)
        config = LayoutConfig()
        result = compute_layout(graph, config)
        _assert_no_overlap(result.node_positions, config)


class TestDisconnectedComponents:
    def test_two_disconnected_subgraphs(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/x.gpkg": _make_node("/x.gpkg"),
            "/y.gpkg": _make_node("/y.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/x.gpkg", "/y.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)

        # Both roots at rank 0
        assert result.node_positions["/a.gpkg"].layer == 0
        assert result.node_positions["/x.gpkg"].layer == 0
        # Both children at rank 1
        assert result.node_positions["/b.gpkg"].layer == 1
        assert result.node_positions["/y.gpkg"].layer == 1


class TestCycleHandling:
    def test_cycle_does_not_crash(self):
        """A->B->C->A: cycle should be broken gracefully."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
            LineageEdge("/c.gpkg", "/a.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert len(result.node_positions) == 3

    def test_cycle_logs_warning(self, caplog):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
            "/c.gpkg": _make_node("/c.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
            LineageEdge("/c.gpkg", "/a.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        with caplog.at_level(logging.WARNING):
            compute_layout(graph)
        assert any("Cycle detected" in r.message for r in caplog.records)

    def test_cycle_all_nodes_get_positions(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg"),
            "/b.gpkg": _make_node("/b.gpkg"),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/a.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)
        assert "/a.gpkg" in result.node_positions
        assert "/b.gpkg" in result.node_positions


class TestPerformance:
    def test_50_node_graph_under_one_second(self):
        nodes = {}
        edges = []
        for i in range(50):
            path = f"/node{i}.gpkg"
            nodes[path] = _make_node(path, depth=i)
            if i > 0:
                prev = f"/node{i - 1}.gpkg"
                edges.append(LineageEdge(prev, path, i))
            # Add some cross-edges for complexity
            if i > 2:
                skip = f"/node{i - 2}.gpkg"
                edges.append(LineageEdge(skip, path, 1000 + i))
        graph = _make_graph(nodes, edges)

        start = time.monotonic()
        result = compute_layout(graph)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Layout took {elapsed:.3f}s, expected <1s"
        assert len(result.node_positions) == 50
