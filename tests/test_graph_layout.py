"""T1 tests for lineage_viewer/graph_layout.py — pure Python, no Qt."""

from GeoLineage.lineage_retrieval.graph_builder import (
    LineageEdge,
    LineageGraph,
    LineageNode,
)
from GeoLineage.lineage_viewer.graph_layout import (
    LayoutConfig,
    NodePosition,
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


class TestLayoutGraphEmpty:
    def test_empty_graph_returns_empty_dict(self):
        graph = _make_graph({})
        result = layout_graph(graph)
        assert result == {}


class TestLayoutGraphSingleNode:
    def test_single_node_at_origin(self):
        nodes = {"/a.gpkg": _make_node("/a.gpkg", depth=0)}
        graph = _make_graph(nodes, root_path="/a.gpkg")
        result = layout_graph(graph)
        assert len(result) == 1
        pos = result["/a.gpkg"]
        assert pos.x == 0.0
        assert pos.y == 0.0
        assert pos.layer == 0
        assert pos.order == 0


class TestLayoutGraphLinearChain:
    def test_three_node_chain_three_layers(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=0),
            "/b.gpkg": _make_node("/b.gpkg", depth=1),
            "/c.gpkg": _make_node("/c.gpkg", depth=2),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges, root_path="/c.gpkg")
        result = layout_graph(graph)
        assert len(result) == 3
        # Each at a different layer
        layers = {result[p].layer for p in nodes}
        assert layers == {0, 1, 2}

    def test_three_node_chain_no_overlap(self):
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=0),
            "/b.gpkg": _make_node("/b.gpkg", depth=1),
            "/c.gpkg": _make_node("/c.gpkg", depth=2),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges, root_path="/c.gpkg")
        config = LayoutConfig()
        result = layout_graph(graph, config)
        _assert_no_overlap(result, config)


class TestLayoutGraphDiamond:
    def test_diamond_dag_middle_layer_side_by_side(self):
        """Diamond: A -> B, A -> C, B -> D, C -> D."""
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=0),
            "/b.gpkg": _make_node("/b.gpkg", depth=1),
            "/c.gpkg": _make_node("/c.gpkg", depth=1),
            "/d.gpkg": _make_node("/d.gpkg", depth=2),
        }
        edges = [
            LineageEdge("/a.gpkg", "/b.gpkg", 1),
            LineageEdge("/a.gpkg", "/c.gpkg", 2),
            LineageEdge("/b.gpkg", "/d.gpkg", 3),
            LineageEdge("/c.gpkg", "/d.gpkg", 4),
        ]
        graph = _make_graph(nodes, edges, root_path="/d.gpkg")
        config = LayoutConfig()
        result = layout_graph(graph, config)

        # Middle layer has 2 nodes at layer 1
        layer1_nodes = [p for p, pos in result.items() if pos.layer == 1]
        assert len(layer1_nodes) == 2

        # They should be side by side (different orders)
        orders = {result[p].order for p in layer1_nodes}
        assert len(orders) == 2

        _assert_no_overlap(result, config)


class TestLayoutGraphWide:
    def test_ten_nodes_same_depth_no_overlap(self):
        nodes = {f"/n{i}.gpkg": _make_node(f"/n{i}.gpkg", depth=0) for i in range(10)}
        graph = _make_graph(nodes, root_path="/n0.gpkg")
        config = LayoutConfig()
        result = layout_graph(graph, config)
        assert len(result) == 10
        _assert_no_overlap(result, config)


class TestLayoutGraph50Nodes:
    def test_50_node_chain_no_overlap(self):
        nodes = {}
        edges = []
        for i in range(50):
            path = f"/node{i}.gpkg"
            nodes[path] = _make_node(path, depth=i)
            if i > 0:
                prev = f"/node{i - 1}.gpkg"
                edges.append(LineageEdge(prev, path, i))

        graph = _make_graph(nodes, edges, root_path="/node0.gpkg")
        config = LayoutConfig()
        result = layout_graph(graph, config)
        assert len(result) == 50
        _assert_no_overlap(result, config)


class TestBarycenterReordering:
    def test_barycenter_reduces_crossings(self):
        """Graph where naive insertion order would have crossings.

        Layer 0: A, B
        Layer 1: C, D
        Edges: A->D, B->C  (crossing if C before D in layer 1)
        Barycenter should reorder layer 1 to [D, C] or produce fewer crossings.
        """
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=0),
            "/b.gpkg": _make_node("/b.gpkg", depth=0),
            "/c.gpkg": _make_node("/c.gpkg", depth=1),
            "/d.gpkg": _make_node("/d.gpkg", depth=1),
        }
        edges = [
            LineageEdge("/a.gpkg", "/d.gpkg", 1),
            LineageEdge("/b.gpkg", "/c.gpkg", 2),
        ]
        graph = _make_graph(nodes, edges, root_path="/c.gpkg")
        config = LayoutConfig()
        result = layout_graph(graph, config)

        # After barycenter: A connects to D, B connects to C
        # So D should be below A (order matching A's order)
        # and C should be below B
        a_order = result["/a.gpkg"].order
        b_order = result["/b.gpkg"].order
        c_order = result["/c.gpkg"].order
        d_order = result["/d.gpkg"].order

        # No crossings means: if a_order < b_order then d_order < c_order
        if a_order < b_order:
            assert d_order < c_order, "Barycenter should reduce edge crossings"
        else:
            assert c_order < d_order, "Barycenter should reduce edge crossings"


class TestLayoutConfig:
    def test_custom_config_affects_spacing(self):
        config = LayoutConfig(
            node_width=100,
            node_height=40,
            horizontal_gap=20,
            vertical_gap=50,
        )
        nodes = {
            "/a.gpkg": _make_node("/a.gpkg", depth=0),
            "/b.gpkg": _make_node("/b.gpkg", depth=0),
            "/c.gpkg": _make_node("/c.gpkg", depth=1),
        }
        edges = [LineageEdge("/a.gpkg", "/c.gpkg", 1)]
        graph = _make_graph(nodes, edges)
        result = layout_graph(graph, config)

        # Two nodes at depth 0 should be spaced by node_width + horizontal_gap
        positions_depth0 = [pos for pos in result.values() if pos.layer == 0]
        xs = sorted(pos.x for pos in positions_depth0)
        assert len(xs) == 2
        assert xs[1] - xs[0] == 100 + 20  # node_width + horizontal_gap

    def test_node_position_is_frozen(self):
        pos = NodePosition(x=1.0, y=2.0, layer=0, order=0)
        try:
            pos.x = 5.0  # type: ignore[misc]
            assert False, "NodePosition should be frozen"
        except AttributeError:
            pass


def _assert_no_overlap(positions: dict[str, NodePosition], config: LayoutConfig):
    """Assert no two node bounding boxes overlap."""
    pos_list = list(positions.values())
    for i in range(len(pos_list)):
        for j in range(i + 1, len(pos_list)):
            a = pos_list[i]
            b = pos_list[j]
            # Check if bounding boxes overlap
            a_right = a.x + config.node_width
            b_right = b.x + config.node_width
            a_bottom = a.y + config.node_height
            b_bottom = b.y + config.node_height

            x_overlap = a.x < b_right and b.x < a_right
            y_overlap = a.y < b_bottom and b.y < a_bottom

            assert not (x_overlap and y_overlap), f"Nodes overlap: ({a.x},{a.y}) and ({b.x},{b.y})"
