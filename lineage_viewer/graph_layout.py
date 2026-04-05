"""Pure-Python Sugiyama-style layout for lineage graphs.

No Qt or QGIS imports — fully T1-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..lineage_retrieval.graph_builder import LineageGraph


@dataclass(frozen=True)
class LayoutConfig:
    node_width: float = 180.0
    node_height: float = 60.0
    horizontal_gap: float = 40.0
    vertical_gap: float = 80.0


@dataclass(frozen=True)
class NodePosition:
    x: float
    y: float
    layer: int
    order: int


def layout_graph(
    graph: LineageGraph,
    config: LayoutConfig | None = None,
) -> dict[str, NodePosition]:
    """Compute (x, y) positions for every node in the graph.

    Algorithm:
    1. Assign layers by node depth (from LineageNode.depth).
    2. Order nodes within each layer using barycenter heuristic
       to minimize edge crossings.
    3. Assign x = order * (node_width + horizontal_gap),
           y = layer * (node_height + vertical_gap).

    Returns dict keyed by node path (same keys as graph.nodes).
    """
    if not graph.nodes:
        return {}

    if config is None:
        config = LayoutConfig()

    layers = _assign_layers(graph)
    ordered_layers = _barycenter_order(layers, graph)
    return _assign_coordinates(ordered_layers, config)


def _assign_layers(graph: LineageGraph) -> dict[int, list[str]]:
    """Group node paths by depth."""
    layers: dict[int, list[str]] = {}
    for path, node in graph.nodes.items():
        depth = node.depth
        if depth not in layers:
            layers[depth] = []
        layers[depth].append(path)
    return layers


def _count_crossings(layers: dict[int, list[str]], graph: LineageGraph) -> int:
    """Count edge crossings between adjacent layers."""
    crossings = 0
    sorted_depths = sorted(layers.keys())

    for i in range(len(sorted_depths) - 1):
        upper_depth = sorted_depths[i]
        lower_depth = sorted_depths[i + 1]
        upper_order = {path: idx for idx, path in enumerate(layers[upper_depth])}
        lower_order = {path: idx for idx, path in enumerate(layers[lower_depth])}

        # Collect edges between these two layers
        between_edges: list[tuple[int, int]] = []
        for edge in graph.edges:
            p_depth = graph.nodes[edge.parent_path].depth if edge.parent_path in graph.nodes else None
            c_depth = graph.nodes[edge.child_path].depth if edge.child_path in graph.nodes else None

            if p_depth == upper_depth and c_depth == lower_depth:
                between_edges.append((upper_order[edge.parent_path], lower_order[edge.child_path]))
            elif p_depth == lower_depth and c_depth == upper_depth:
                between_edges.append((lower_order[edge.parent_path], upper_order[edge.child_path]))

        # Count crossings: two edges (u1,v1) and (u2,v2) cross iff
        # (u1 < u2 and v1 > v2) or (u1 > u2 and v1 < v2)
        for a in range(len(between_edges)):
            for b in range(a + 1, len(between_edges)):
                u1, v1 = between_edges[a]
                u2, v2 = between_edges[b]
                if (u1 < u2 and v1 > v2) or (u1 > u2 and v1 < v2):
                    crossings += 1

    return crossings


def _barycenter_order(
    layers: dict[int, list[str]],
    graph: LineageGraph,
) -> dict[int, list[str]]:
    """Reorder nodes within each layer using barycenter heuristic.

    Alternating top-down then bottom-up sweeps, capped at 4 iterations.
    Skip if every layer has <= 1 node.
    Skip if naive grid has zero crossings.
    """
    # Skip if all layers have <= 1 node
    if all(len(nodes) <= 1 for nodes in layers.values()):
        return dict(layers)

    # Check if naive ordering already has zero crossings
    if _count_crossings(layers, graph) == 0:
        return dict(layers)

    sorted_depths = sorted(layers.keys())
    # Build adjacency lookups
    # parent_path -> child_path edges (parent is at lower depth = higher in graph)
    children_of: dict[str, list[str]] = {}
    parents_of: dict[str, list[str]] = {}
    for edge in graph.edges:
        children_of.setdefault(edge.parent_path, []).append(edge.child_path)
        parents_of.setdefault(edge.child_path, []).append(edge.parent_path)

    result = {d: list(layers[d]) for d in layers}

    for iteration in range(4):
        if iteration % 2 == 0:
            # Top-down sweep
            for di in range(1, len(sorted_depths)):
                depth = sorted_depths[di]
                prev_depth = sorted_depths[di - 1]
                prev_order = {path: idx for idx, path in enumerate(result[prev_depth])}
                result[depth] = _reorder_layer(result[depth], parents_of, prev_order)
        else:
            # Bottom-up sweep
            for di in range(len(sorted_depths) - 2, -1, -1):
                depth = sorted_depths[di]
                next_depth = sorted_depths[di + 1]
                next_order = {path: idx for idx, path in enumerate(result[next_depth])}
                result[depth] = _reorder_layer(result[depth], children_of, next_order)

    return result


def _reorder_layer(
    layer_nodes: list[str],
    adjacency: dict[str, list[str]],
    neighbor_order: dict[str, int],
) -> list[str]:
    """Reorder a single layer by barycenter of connected neighbors.

    Nodes with no connections keep their original position (stable sort).
    """
    barycenters: list[tuple[float, int, str]] = []
    for orig_idx, path in enumerate(layer_nodes):
        neighbors = adjacency.get(path, [])
        positions = [neighbor_order[n] for n in neighbors if n in neighbor_order]
        bary = sum(positions) / len(positions) if positions else float(orig_idx)
        barycenters.append((bary, orig_idx, path))

    barycenters.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in barycenters]


def _assign_coordinates(
    ordered_layers: dict[int, list[str]],
    config: LayoutConfig,
) -> dict[str, NodePosition]:
    """Convert layer + order to (x, y) coordinates."""
    positions: dict[str, NodePosition] = {}
    for depth, nodes in ordered_layers.items():
        for order, path in enumerate(nodes):
            x = order * (config.node_width + config.horizontal_gap)
            y = depth * (config.node_height + config.vertical_gap)
            positions[path] = NodePosition(x=x, y=y, layer=depth, order=order)
    return positions
