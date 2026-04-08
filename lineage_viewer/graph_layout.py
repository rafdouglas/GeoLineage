"""Pure-Python Sugiyama-style layout for lineage graphs.

No Qt or QGIS imports — fully T1-testable.

Algorithm phases:
1. Cycle breaking (DFS back-edge reversal)
2. Rank assignment (longest-path from roots)
3. Dummy node insertion (split multi-rank edges)
4. Crossing minimisation (barycenter heuristic, 6 sweeps)
5. X-coordinate assignment (centered per rank)
6. Dummy node removal
7. Edge routing (waypoints from dummy positions)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from ..lineage_retrieval.graph_builder import LineageGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutConfig:
    node_width: float = 180.0
    node_height: float = 60.0
    horizontal_gap: float = 40.0
    vertical_gap: float = 80.0


@dataclass(frozen=True)
class NodePosition:
    """Position of a node in the layout.

    ``layer`` holds the Sugiyama rank (topological distance from roots),
    which may differ from ``LineageNode.depth`` (BFS distance from the
    selected node).  Rank is used for visual positioning; depth is used
    by ``graph_builder`` for traversal control.

    ``width`` holds the display width used by the layout engine so that
    downstream rendering can match exactly.
    """

    x: float
    y: float
    layer: int
    order: int
    width: float = 180.0


@dataclass(frozen=True)
class EdgePath:
    """Routed path for a single edge.

    ``source`` and ``target`` use the *original* edge direction
    (parent -> child) regardless of any internal cycle-breaking reversal.
    ``waypoints`` are ordered from source exit to target entry.
    """

    source: str
    target: str
    waypoints: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LayoutResult:
    """Result of Sugiyama layout computation.

    ``node_positions`` contains real nodes only, keyed by file path.
    ``edge_paths`` contains one ``EdgePath`` per original edge.

    Note: ``NodePosition.layer`` holds the Sugiyama rank (topological
    distance from roots), which may differ from ``LineageNode.depth``
    (BFS distance from the selected node).  Rank is used for visual
    positioning; depth is used by ``graph_builder`` for traversal control.
    """

    node_positions: dict[str, NodePosition]
    edge_paths: tuple[EdgePath, ...]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_layout(
    graph: LineageGraph,
    config: LayoutConfig | None = None,
    node_widths: dict[str, float] | None = None,
) -> LayoutResult:
    """Compute positions and edge paths for a lineage graph.

    Implements a 7-phase Sugiyama pipeline:
    1. Cycle breaking   2. Rank assignment   3. Dummy insertion
    4. Crossing min     5. X-coordinate      6. Dummy removal
    7. Edge routing

    ``node_widths`` maps node IDs to their display width in pixels.
    When *None* or for missing keys, ``config.node_width`` is used.
    """
    if not graph.nodes:
        return LayoutResult(node_positions={}, edge_paths=())

    if config is None:
        config = LayoutConfig()

    if node_widths is None:
        node_widths = {}

    children_map, parents_map = _build_adjacency(graph)

    # Phase 1: break cycles
    acyclic_children, acyclic_parents, reversed_edges = _break_cycles(children_map, parents_map)

    # Phase 2: rank assignment (longest-path from roots)
    ranks = _assign_ranks(acyclic_children, acyclic_parents)

    # Phase 3: dummy node insertion
    aug_children, aug_parents, dummy_set, rank_lists = _insert_dummy_nodes(ranks, acyclic_children, acyclic_parents)

    # Phase 4: crossing minimisation
    rank_lists = _minimise_crossings(rank_lists, aug_children, aug_parents)

    # Phase 5: x-coordinate assignment
    all_positions = _assign_x_coordinates(rank_lists, config, node_widths)

    # Phase 6: dummy removal — keep positions for routing
    node_positions: dict[str, NodePosition] = {}
    for node_id, (x, y) in all_positions.items():
        if node_id not in dummy_set:
            rank = ranks[node_id]
            order = rank_lists[rank].index(node_id)
            w = node_widths.get(node_id, config.node_width)
            node_positions[node_id] = NodePosition(x=x, y=y, layer=rank, order=order, width=w)

    # Phase 7: edge routing
    edge_paths = _route_edges(graph.edges, all_positions, dummy_set, reversed_edges, config, node_widths)

    return LayoutResult(node_positions=node_positions, edge_paths=edge_paths)


def layout_graph(
    graph: LineageGraph,
    config: LayoutConfig | None = None,
) -> dict[str, NodePosition]:
    """Backward-compatible wrapper returning only node positions."""
    result = compute_layout(graph, config=config)
    return result.node_positions


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _build_adjacency(
    graph: LineageGraph,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build children/parents adjacency maps from graph edges.

    Only includes nodes present in ``graph.nodes``.
    """
    node_set = set(graph.nodes)
    children_map: dict[str, list[str]] = {n: [] for n in node_set}
    parents_map: dict[str, list[str]] = {n: [] for n in node_set}

    for edge in graph.edges:
        if edge.parent_path in node_set and edge.child_path in node_set:
            children_map[edge.parent_path].append(edge.child_path)
            parents_map[edge.child_path].append(edge.parent_path)

    return children_map, parents_map


def _break_cycles(
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]], set[tuple[str, str]]]:
    """Phase 1: DFS back-edge reversal to make the graph acyclic."""
    all_nodes = set(children_map)
    visited: set[str] = set()
    in_stack: set[str] = set()
    reversed_edges: set[tuple[str, str]] = set()

    # Work on copies
    ac: dict[str, list[str]] = {n: list(ch) for n, ch in children_map.items()}
    ap: dict[str, list[str]] = {n: list(pa) for n, pa in parents_map.items()}

    # Find roots (no parents)
    roots = [n for n in all_nodes if not parents_map[n]]
    # If no roots (all nodes in cycles), start from any node
    if not roots:
        roots = sorted(all_nodes)

    def dfs(node: str) -> None:
        visited.add(node)
        in_stack.add(node)
        for child in list(ac[node]):
            if child in in_stack:
                # Back edge — reverse it
                logger.warning(
                    "Cycle detected: back-edge %s -> %s reversed for layout",
                    node,
                    child,
                )
                reversed_edges.add((node, child))
                ac[node].remove(child)
                ap[child].remove(node)
                ac[child].append(node)
                ap[node].append(child)
            elif child not in visited:
                dfs(child)
        in_stack.discard(node)

    for root in roots:
        if root not in visited:
            dfs(root)

    # Visit any remaining unvisited nodes (disconnected components)
    for node in sorted(all_nodes):
        if node not in visited:
            dfs(node)

    return ac, ap, reversed_edges


def _assign_ranks(
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
) -> dict[str, int]:
    """Phase 2: longest-path rank assignment using Kahn's algorithm.

    Roots (no parents) get rank 0.  Each node's rank is
    ``max(rank[parent] + 1 for parent in parents)``.
    """
    all_nodes = set(children_map)
    in_degree: dict[str, int] = {n: len(parents_map.get(n, [])) for n in all_nodes}
    ranks: dict[str, int] = {}

    queue = deque(n for n in all_nodes if in_degree[n] == 0)

    # If no zero-in-degree nodes, all are in cycles — pick one
    if not queue:
        queue.append(min(sorted(all_nodes)))
        in_degree[queue[0]] = 0

    for node in queue:
        ranks[node] = 0

    while queue:
        node = queue.popleft()
        for child in children_map.get(node, []):
            ranks[child] = max(ranks.get(child, 0), ranks[node] + 1)
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Any remaining unranked nodes (shouldn't happen after cycle breaking)
    for node in all_nodes:
        if node not in ranks:
            ranks[node] = 0

    return ranks


def _insert_dummy_nodes(
    ranks: dict[str, int],
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    set[str],
    dict[int, list[str]],
]:
    """Phase 3: insert dummy nodes for edges spanning >1 rank."""
    aug_children: dict[str, list[str]] = {n: list(ch) for n, ch in children_map.items()}
    aug_parents: dict[str, list[str]] = {n: list(pa) for n, pa in parents_map.items()}
    dummy_set: set[str] = set()

    # Build initial rank lists
    rank_lists: dict[int, list[str]] = {}
    for node, rank in ranks.items():
        rank_lists.setdefault(rank, []).append(node)

    # Process each edge for multi-rank spans
    edges_to_process = []
    for source, children in list(children_map.items()):
        for target in children:
            span = ranks[target] - ranks[source]
            if span > 1:
                edges_to_process.append((source, target, span))

    for source, target, _span in edges_to_process:
        # Remove direct edge
        aug_children[source].remove(target)
        aug_parents[target].remove(source)

        # Insert chain of dummy nodes
        prev = source
        for r in range(ranks[source] + 1, ranks[target]):
            dummy_id = f"__dummy__{source}__{target}__{r}"
            dummy_set.add(dummy_id)
            ranks[dummy_id] = r
            rank_lists.setdefault(r, []).append(dummy_id)
            aug_children[dummy_id] = []
            aug_parents[dummy_id] = []

            aug_children[prev].append(dummy_id)
            aug_parents[dummy_id].append(prev)
            prev = dummy_id

        # Connect last dummy to target
        aug_children[prev].append(target)
        aug_parents[target].append(prev)

    return aug_children, aug_parents, dummy_set, rank_lists


def _minimise_crossings(
    rank_lists: dict[int, list[str]],
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
    n_sweeps: int = 6,
) -> dict[int, list[str]]:
    """Phase 4: barycenter heuristic with alternating sweeps + transpose."""
    sorted_ranks = sorted(rank_lists.keys())
    if len(sorted_ranks) <= 1:
        return rank_lists

    result = {r: list(rank_lists[r]) for r in rank_lists}

    for sweep in range(n_sweeps):
        if sweep % 2 == 0:
            # Top-down
            for ri in range(1, len(sorted_ranks)):
                rank = sorted_ranks[ri]
                prev_rank = sorted_ranks[ri - 1]
                prev_order = {node: idx for idx, node in enumerate(result[prev_rank])}
                result[rank] = _reorder_layer(result[rank], parents_map, prev_order)
        else:
            # Bottom-up
            for ri in range(len(sorted_ranks) - 2, -1, -1):
                rank = sorted_ranks[ri]
                next_rank = sorted_ranks[ri + 1]
                next_order = {node: idx for idx, node in enumerate(result[next_rank])}
                result[rank] = _reorder_layer(result[rank], children_map, next_order)

    # Transpose step: swap adjacent pairs when it reduces crossings
    _transpose(result, sorted_ranks, children_map, parents_map)

    return result


def _reorder_layer(
    layer_nodes: list[str],
    adjacency: dict[str, list[str]],
    neighbor_order: dict[str, int],
) -> list[str]:
    """Reorder a single layer by barycenter of connected neighbors."""
    barycenters: list[tuple[float, int, str]] = []
    for orig_idx, node in enumerate(layer_nodes):
        neighbors = adjacency.get(node, [])
        positions = [neighbor_order[n] for n in neighbors if n in neighbor_order]
        bary = sum(positions) / len(positions) if positions else float(orig_idx)
        barycenters.append((bary, orig_idx, node))

    barycenters.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in barycenters]


def _count_crossings_between_pair(
    u: str,
    v: str,
    adj_order: dict[str, int],
    adjacency: dict[str, list[str]],
) -> int:
    """Count edge crossings between u and v w.r.t. an adjacent rank.

    u is left of v in the current rank.  A crossing occurs when an
    edge from u goes to a position *right of* an edge from v (or
    vice-versa) in the adjacent rank.
    """
    u_pos = sorted(adj_order[n] for n in adjacency.get(u, []) if n in adj_order)
    v_pos = sorted(adj_order[n] for n in adjacency.get(v, []) if n in adj_order)
    count = 0
    for a in u_pos:
        for b in v_pos:
            if a > b:
                count += 1
    return count


def _transpose(
    result: dict[int, list[str]],
    sorted_ranks: list[int],
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
) -> None:
    """Transpose step: try swapping adjacent node pairs to reduce crossings.

    Modifies *result* in place.  Converges quickly (typically 1-3 passes).
    """
    improved = True
    while improved:
        improved = False
        for rank in sorted_ranks:
            nodes = result[rank]
            for i in range(len(nodes) - 1):
                u, v = nodes[i], nodes[i + 1]
                cross_before = 0
                cross_after = 0

                # Check against rank above (use parents_map)
                rank_idx = sorted_ranks.index(rank)
                if rank_idx > 0:
                    above_rank = sorted_ranks[rank_idx - 1]
                    above_order = {n: idx for idx, n in enumerate(result[above_rank])}
                    cross_before += _count_crossings_between_pair(u, v, above_order, parents_map)
                    cross_after += _count_crossings_between_pair(v, u, above_order, parents_map)

                # Check against rank below (use children_map)
                if rank_idx < len(sorted_ranks) - 1:
                    below_rank = sorted_ranks[rank_idx + 1]
                    below_order = {n: idx for idx, n in enumerate(result[below_rank])}
                    cross_before += _count_crossings_between_pair(u, v, below_order, children_map)
                    cross_after += _count_crossings_between_pair(v, u, below_order, children_map)

                if cross_after < cross_before:
                    nodes[i], nodes[i + 1] = nodes[i + 1], nodes[i]
                    improved = True


def _assign_x_coordinates(
    rank_lists: dict[int, list[str]],
    config: LayoutConfig,
    node_widths: dict[str, float] | None = None,
) -> dict[str, tuple[float, float]]:
    """Phase 5: centered x-coordinate assignment.

    Each rank is centered around x=0.  When *node_widths* is provided,
    nodes are spaced according to their individual widths so that no two
    nodes in the same rank overlap.
    """
    if node_widths is None:
        node_widths = {}

    positions: dict[str, tuple[float, float]] = {}
    cell_height = config.node_height + config.vertical_gap

    for rank, nodes in rank_lists.items():
        n = len(nodes)
        if n == 0:
            continue

        # Place nodes left-to-right with per-node widths
        x_cursor = 0.0
        node_xs: list[float] = []
        widths: list[float] = []
        for node_id in nodes:
            node_xs.append(x_cursor)
            w = node_widths.get(node_id, config.node_width)
            widths.append(w)
            x_cursor += w + config.horizontal_gap

        # Center the rank so the mean x-position of all node left-edges
        # matches the old behavior: ``(order - (n-1)/2) * cell_width``.
        # For uniform widths this produces identical coordinates.
        mean_x = sum(node_xs) / n
        offset = -mean_x

        y = rank * cell_height
        for i, node_id in enumerate(nodes):
            positions[node_id] = (node_xs[i] + offset, y)

    return positions


def _route_edges(
    graph_edges: tuple,
    all_positions: dict[str, tuple[float, float]],
    dummy_set: set[str],
    reversed_edges: set[tuple[str, str]],
    config: LayoutConfig,
    node_widths: dict[str, float] | None = None,
) -> tuple[EdgePath, ...]:
    """Phase 7: collect waypoints from dummy node positions for each edge.

    Waypoints go from source bottom-center through dummy centers to
    target top-center.
    """
    if node_widths is None:
        node_widths = {}
    default_half_w = config.node_width / 2
    node_h = config.node_height

    # Build a lookup: (original_source, original_target) -> list of dummy ids in rank order
    # We need to trace from source through dummies to target
    edge_paths: list[EdgePath] = []

    for edge in graph_edges:
        src = edge.parent_path
        tgt = edge.child_path

        if src not in all_positions or tgt not in all_positions:
            continue

        # Check if this edge was reversed during cycle breaking
        is_reversed = (src, tgt) in reversed_edges

        if is_reversed:
            # In the acyclic graph, the edge direction was flipped: tgt -> src
            # So dummies are named __dummy__{tgt}__{src}__{rank}
            layout_src, layout_tgt = tgt, src
        else:
            layout_src, layout_tgt = src, tgt

        # Find dummy nodes for this edge
        prefix = f"__dummy__{layout_src}__{layout_tgt}__"
        dummies = sorted(
            (did for did in dummy_set if did.startswith(prefix)),
            key=lambda d: all_positions[d][1],  # sort by y (rank order)
        )

        # Build waypoints: source bottom-center -> dummy centers -> target top-center
        waypoints: list[tuple[float, float]] = []

        # Source bottom-center (use actual node width)
        sx, sy = all_positions[src]
        src_half_w = node_widths.get(src, config.node_width) / 2
        waypoints.append((sx + src_half_w, sy + node_h))

        # Dummy node centers (in layout order, but we need source->target order)
        if is_reversed:
            # Dummies go from tgt to src in layout; reverse for original direction
            for did in reversed(dummies):
                dx, dy = all_positions[did]
                waypoints.append((dx + default_half_w, dy + node_h / 2))
        else:
            for did in dummies:
                dx, dy = all_positions[did]
                waypoints.append((dx + default_half_w, dy + node_h / 2))

        # Target top-center (use actual node width)
        tx, ty = all_positions[tgt]
        tgt_half_w = node_widths.get(tgt, config.node_width) / 2
        waypoints.append((tx + tgt_half_w, ty))

        edge_paths.append(EdgePath(source=src, target=tgt, waypoints=tuple(waypoints)))

    return tuple(edge_paths)
