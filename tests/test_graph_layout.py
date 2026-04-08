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
    """Assert no two node bounding boxes overlap.

    Uses per-node ``width`` from ``NodePosition`` (falls back to
    ``config.node_width`` for backward compatibility).
    """
    pos_list = list(positions.values())
    for i in range(len(pos_list)):
        for j in range(i + 1, len(pos_list)):
            a = pos_list[i]
            b = pos_list[j]
            a_right = a.x + a.width
            b_right = b.x + b.width
            a_bottom = a.y + config.node_height
            b_bottom = b.y + config.node_height

            x_overlap = a.x < b_right and b.x < a_right
            y_overlap = a.y < b_bottom and b.y < a_bottom

            assert not (x_overlap and y_overlap), (
                f"Nodes overlap: ({a.x},{a.y},w={a.width}) and ({b.x},{b.y},w={b.width})"
            )


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


class TestVariableWidthNoOverlap:
    """Nodes with different widths must not overlap."""

    def test_wide_nodes_same_rank_no_overlap(self):
        """Three nodes at the same rank with very different widths."""
        nodes = {
            "/short.gpkg": _make_node("/short.gpkg"),
            "/a_very_long_filename_that_exceeds_default.gpkg": _make_node(
                "/a_very_long_filename_that_exceeds_default.gpkg"
            ),
            "/another_extremely_long_filename.gpkg": _make_node("/another_extremely_long_filename.gpkg"),
        }
        graph = _make_graph(nodes)
        config = LayoutConfig()
        node_widths = {
            "/short.gpkg": 120.0,
            "/a_very_long_filename_that_exceeds_default.gpkg": 350.0,
            "/another_extremely_long_filename.gpkg": 300.0,
        }
        result = compute_layout(graph, config, node_widths=node_widths)
        assert len(result.node_positions) == 3
        _assert_no_overlap(result.node_positions, config)

    def test_variable_width_diamond_no_overlap(self):
        """Diamond topology where middle-rank nodes have very different widths."""
        nodes = {
            "/root.gpkg": _make_node("/root.gpkg"),
            "/wide_node_name.gpkg": _make_node("/wide_node_name.gpkg"),
            "/x.gpkg": _make_node("/x.gpkg"),
            "/sink.gpkg": _make_node("/sink.gpkg"),
        }
        edges = [
            LineageEdge("/root.gpkg", "/wide_node_name.gpkg", 1),
            LineageEdge("/root.gpkg", "/x.gpkg", 2),
            LineageEdge("/wide_node_name.gpkg", "/sink.gpkg", 3),
            LineageEdge("/x.gpkg", "/sink.gpkg", 4),
        ]
        graph = _make_graph(nodes, edges)
        config = LayoutConfig()
        node_widths = {
            "/root.gpkg": 180.0,
            "/wide_node_name.gpkg": 400.0,
            "/x.gpkg": 120.0,
            "/sink.gpkg": 180.0,
        }
        result = compute_layout(graph, config, node_widths=node_widths)
        _assert_no_overlap(result.node_positions, config)

    def test_node_position_stores_width(self):
        """NodePosition.width should reflect the node_widths passed in."""
        nodes = {"/a.gpkg": _make_node("/a.gpkg")}
        graph = _make_graph(nodes, root_path="/a.gpkg")
        result = compute_layout(graph, node_widths={"/a.gpkg": 250.0})
        assert result.node_positions["/a.gpkg"].width == 250.0

    def test_default_width_when_no_node_widths(self):
        """Without node_widths, NodePosition.width defaults to config.node_width."""
        nodes = {"/a.gpkg": _make_node("/a.gpkg")}
        graph = _make_graph(nodes, root_path="/a.gpkg")
        config = LayoutConfig(node_width=200.0)
        result = compute_layout(graph, config)
        assert result.node_positions["/a.gpkg"].width == 200.0


class TestTransposeCrossingReduction:
    """The transpose step should reduce or eliminate crossings."""

    def test_transpose_eliminates_simple_crossing(self):
        """A->D, B->C with A left of B: edges cross unless D is left of C.

        After transpose, the ordering should avoid this crossing.
        """
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

        a = result.node_positions["/a.gpkg"]
        b = result.node_positions["/b.gpkg"]
        c = result.node_positions["/c.gpkg"]
        d = result.node_positions["/d.gpkg"]

        # If A is left of B, then D should be left of C (no crossing)
        if a.x < b.x:
            assert d.x < c.x, "Transpose should eliminate this crossing"
        else:
            assert c.x < d.x, "Transpose should eliminate this crossing"

    def test_crossing_with_three_parent_child_pairs(self):
        """Three parents each connected to one child in reverse order."""
        nodes = {
            "/p1.gpkg": _make_node("/p1.gpkg"),
            "/p2.gpkg": _make_node("/p2.gpkg"),
            "/p3.gpkg": _make_node("/p3.gpkg"),
            "/c1.gpkg": _make_node("/c1.gpkg"),
            "/c2.gpkg": _make_node("/c2.gpkg"),
            "/c3.gpkg": _make_node("/c3.gpkg"),
        }
        edges = [
            LineageEdge("/p1.gpkg", "/c3.gpkg", 1),
            LineageEdge("/p2.gpkg", "/c2.gpkg", 2),
            LineageEdge("/p3.gpkg", "/c1.gpkg", 3),
        ]
        graph = _make_graph(nodes, edges)
        result = compute_layout(graph)

        # After crossing minimization, edges should not cross
        parents = sorted(
            [("/p1.gpkg", "/c3.gpkg"), ("/p2.gpkg", "/c2.gpkg"), ("/p3.gpkg", "/c1.gpkg")],
            key=lambda pair: result.node_positions[pair[0]].x,
        )
        child_xs = [result.node_positions[pair[1]].x for pair in parents]
        # Child x-coords should be non-decreasing (no crossings)
        for i in range(len(child_xs) - 1):
            assert child_xs[i] <= child_xs[i + 1], "Crossing minimisation should order children to match parents"


class TestInterpolateWaypoints:
    """Test _interpolate_waypoints free function (no Qt needed)."""

    def test_two_point_edge_returns_endpoints(self):
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (10.0, 0.0)
        tgt = (20.0, 100.0)
        result = _interpolate_waypoints(src, tgt, [src, tgt])
        assert result == [src, tgt]

    def test_three_point_edge_interpolates_middle(self):
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (0.0, 0.0)
        tgt = (100.0, 200.0)
        original = [(0.0, 0.0), (50.0, 100.0), (100.0, 200.0)]
        result = _interpolate_waypoints(src, tgt, original)
        assert len(result) == 3
        assert result[0] == src
        assert result[2] == tgt
        # Middle x should be interpolated to halfway between src and tgt
        assert result[1][0] == 50.0
        # Middle y stays at original
        assert result[1][1] == 100.0

    def test_five_point_edge_preserves_y_interpolates_x(self):
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (0.0, 0.0)
        tgt = (100.0, 400.0)
        original = [
            (0.0, 0.0),
            (999.0, 100.0),
            (999.0, 200.0),
            (999.0, 300.0),
            (100.0, 400.0),
        ]
        result = _interpolate_waypoints(src, tgt, original)
        assert len(result) == 5
        assert result[0] == src
        assert result[4] == tgt
        # Intermediate x-coords should be evenly interpolated
        assert result[1][0] == 25.0  # 100 * 1/4
        assert result[2][0] == 50.0  # 100 * 2/4
        assert result[3][0] == 75.0  # 100 * 3/4
        # Y-coords preserved from originals
        assert result[1][1] == 100.0
        assert result[2][1] == 200.0
        assert result[3][1] == 300.0

    def test_single_point_returns_endpoints(self):
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (10.0, 0.0)
        tgt = (20.0, 50.0)
        result = _interpolate_waypoints(src, tgt, [(10.0, 0.0)])
        assert result == [src, tgt]


class TestInterpolateWaypointsYAxis:
    """Verify y-coordinates use proportional interpolation, not original values."""

    def test_y_interpolated_not_preserved(self):
        """Original middle y=50 but proportional t_y gives 50."""
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (0.0, 0.0)
        tgt = (100.0, 200.0)
        original = [(0.0, 0.0), (50.0, 50.0), (100.0, 200.0)]
        result = _interpolate_waypoints(src, tgt, original)
        # t_y = (50 - 0) / (200 - 0) = 0.25, interp_y = 0 + 200 * 0.25 = 50
        assert result[1][1] == 50.0

    def test_vertical_drag_shifts_intermediates(self):
        """Source moved down: intermediates shift proportionally."""
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (0.0, 100.0)
        tgt = (100.0, 400.0)
        original = [(0.0, 0.0), (50.0, 100.0), (50.0, 200.0), (50.0, 300.0), (100.0, 400.0)]
        result = _interpolate_waypoints(src, tgt, original)
        # orig_span = 400, new_span = 300
        # t_y for wp1: (100-0)/400 = 0.25 -> 100 + 300*0.25 = 175
        # t_y for wp2: (200-0)/400 = 0.50 -> 100 + 300*0.50 = 250
        # t_y for wp3: (300-0)/400 = 0.75 -> 100 + 300*0.75 = 325
        assert result[1][1] == 175.0
        assert result[2][1] == 250.0
        assert result[3][1] == 325.0

    def test_zero_span_y_uses_uniform(self):
        """All original waypoints at same y: uses uniform t fallback."""
        from GeoLineage.lineage_viewer.graph_edge_item import _interpolate_waypoints

        src = (0.0, 0.0)
        tgt = (100.0, 200.0)
        original = [(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)]
        result = _interpolate_waypoints(src, tgt, original)
        # orig_span_y = 0, falls back to uniform t = 0.5
        assert result[1][1] == 100.0


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
