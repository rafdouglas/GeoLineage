"""Tests for LineageGraphScene edge-identity pairing (issue 1.3).

reset_layout() must re-pair each edge item with its routed path by the edge's
(source, target) identity, not by list position. The pure helper
build_edge_path_map is tested directly; the reset_layout behavior is tested by
constructing the scene via __new__ (skipping the Qt __init__) and monkeypatching
the layout/measurement seams so no QApplication is required.
"""

from __future__ import annotations

import types

from GeoLineage.lineage_viewer.graph_layout import EdgePath, LayoutResult, NodePosition
from GeoLineage.lineage_viewer.graph_scene import LineageGraphScene, build_edge_path_map


def test_build_edge_path_map_keys_by_identity():
    ab = EdgePath("a.gpkg", "b.gpkg", ((0.0, 0.0), (1.0, 1.0)))
    bc = EdgePath("b.gpkg", "c.gpkg", ((2.0, 2.0),))

    result = build_edge_path_map([ab, bc])

    assert result == {("a.gpkg", "b.gpkg"): ab, ("b.gpkg", "c.gpkg"): bc}


def test_build_edge_path_map_empty():
    assert build_edge_path_map([]) == {}


class _FakeNodeItem:
    def __init__(self) -> None:
        self.pos = None

    def setPos(self, x, y) -> None:
        self.pos = (x, y)


class _FakeEdgeItem:
    def __init__(self) -> None:
        self.waypoints = None

    def set_waypoints(self, waypoints) -> None:
        self.waypoints = waypoints


def _make_scene(node_items, edge_items, monkeypatch, edge_paths):
    """Build a scene via __new__ with the Qt/layout seams stubbed out."""
    scene = LineageGraphScene.__new__(LineageGraphScene)
    scene._node_items = node_items
    scene._edge_items = edge_items
    scene._config = object()
    scene._current_graph = types.SimpleNamespace(nodes={path: object() for path in node_items})

    positions = {
        path: NodePosition(x=float(i), y=float(i), layer=0, order=i, width=180.0) for i, path in enumerate(node_items)
    }
    fake_result = LayoutResult(node_positions=positions, edge_paths=tuple(edge_paths))

    monkeypatch.setattr(
        "GeoLineage.lineage_viewer.graph_node_item.compute_node_display_width",
        lambda node: 180.0,
    )
    monkeypatch.setattr(
        "GeoLineage.lineage_viewer.graph_layout.compute_layout",
        lambda graph, config, node_widths=None: fake_result,
    )
    return scene


def test_reset_layout_pairs_by_identity(monkeypatch):
    """Each edge item must receive ITS OWN waypoints, regardless of order."""
    wp_ab = ((0.0, 0.0), (10.0, 10.0))
    wp_bc = ((20.0, 20.0), (30.0, 30.0))

    item_ab = _FakeEdgeItem()
    item_bc = _FakeEdgeItem()
    # Insert in shuffled order (BC before AB) to expose index-based pairing.
    edge_items = {
        ("b.gpkg", "c.gpkg"): item_bc,
        ("a.gpkg", "b.gpkg"): item_ab,
    }
    node_items = {"a.gpkg": _FakeNodeItem(), "b.gpkg": _FakeNodeItem(), "c.gpkg": _FakeNodeItem()}

    # edge_paths returned in a DIFFERENT order than items were inserted.
    edge_paths = [
        EdgePath("a.gpkg", "b.gpkg", wp_ab),
        EdgePath("b.gpkg", "c.gpkg", wp_bc),
    ]

    scene = _make_scene(node_items, edge_items, monkeypatch, edge_paths)
    scene.reset_layout()

    assert item_ab.waypoints == wp_ab
    assert item_bc.waypoints == wp_bc


def test_reset_layout_missing_key_leaves_waypoints_untouched(monkeypatch):
    """An edge with no matching path keeps its current waypoints (no cross-wiring)."""
    item_ab = _FakeEdgeItem()
    item_xy = _FakeEdgeItem()
    item_xy.set_waypoints("ORIGINAL")  # pre-existing waypoints

    edge_items = {
        ("a.gpkg", "b.gpkg"): item_ab,
        ("x.gpkg", "y.gpkg"): item_xy,  # not present in new layout
    }
    node_items = {"a.gpkg": _FakeNodeItem(), "b.gpkg": _FakeNodeItem()}

    edge_paths = [EdgePath("a.gpkg", "b.gpkg", ((1.0, 1.0),))]

    scene = _make_scene(node_items, edge_items, monkeypatch, edge_paths)
    scene.reset_layout()

    assert item_ab.waypoints == ((1.0, 1.0),)
    assert item_xy.waypoints == "ORIGINAL"  # untouched


def test_reset_layout_noop_without_graph():
    scene = LineageGraphScene.__new__(LineageGraphScene)
    scene._current_graph = None
    # Should return without raising even though no other attrs are set.
    scene.reset_layout()
