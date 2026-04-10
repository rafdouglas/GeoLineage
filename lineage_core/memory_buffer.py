import logging

from .recorder import record_processing
from .settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.memory_buffer")


class MemoryBuffer:
    """Graph-based in-memory buffer for pending lineage entries.

    Tracks entries keyed by layer ID and parent-child relationships
    between layers (link graph). When flush() is called, traverses
    the link graph to collect the full ancestry chain and writes
    all entries to the target GeoPackage.
    """

    def __init__(self) -> None:
        self._entries: dict[str, list[dict]] = {}
        self._links: dict[str, list[str]] = {}

    def add(self, layer_id: str, entry: dict) -> None:
        """Store a pending lineage entry for a layer.

        entry should be a dict with keys matching record_processing params:
        layer_name, tool, params, parents, parent_metadata, parent_checksums,
        output_crs_epsg, created_by
        """
        self._entries.setdefault(layer_id, []).append(entry)

    def link(self, output_layer_id: str, input_layer_ids: list[str]) -> None:
        """Record that output_layer_id was derived from input_layer_ids.

        Creates directed edges in the internal dependency graph.
        link(id, []) is a valid no-op (no parents).
        """
        if not input_layer_ids:
            return
        self._links.setdefault(output_layer_id, []).extend(input_layer_ids)

    def get_chain(self, layer_id: str) -> list[dict]:
        """Traverse the link graph to collect the full lineage chain.

        Returns entries in topological order (ancestors before descendants),
        breaking ties by insertion order.

        Returns empty list if layer_id is unknown.
        Raises ValueError if a cycle is detected.
        """
        if layer_id not in self._entries and layer_id not in self._links:
            return []

        # Collect all ancestor IDs via DFS, detect cycles
        order: list[str] = []
        visited: set[str] = set()
        in_stack: set[str] = set()  # for cycle detection

        def _dfs(node_id: str) -> None:
            if node_id in in_stack:
                raise ValueError(f"Cycle detected in lineage graph at {node_id}")
            if node_id in visited:
                return
            in_stack.add(node_id)
            # Visit parents first (ancestors before descendants)
            for parent_id in self._links.get(node_id, []):
                _dfs(parent_id)
            in_stack.discard(node_id)
            visited.add(node_id)
            order.append(node_id)

        _dfs(layer_id)

        # Collect entries in topological order
        chain: list[dict] = []
        for node_id in order:
            chain.extend(self._entries.get(node_id, []))
        return chain

    def flush(self, layer_id: str, gpkg_path: str) -> None:
        """Write the complete lineage chain to the GeoPackage.

        Traverses the link graph to collect all ancestor entries,
        then writes each entry to the _lineage table via record_processing.

        No-op if layer_id is unknown.
        """
        chain = self.get_chain(layer_id)
        if not chain:
            logger.debug("flush(%s): no entries to write", layer_id)
            return

        for entry in chain:
            record_processing(
                gpkg_path=gpkg_path,
                layer_name=entry.get("layer_name", "unknown"),
                tool=entry.get("tool", "unknown"),
                params=entry.get("params", {}),
                parents=entry.get("parents", []),
                parent_metadata=entry.get("parent_metadata", []),
                parent_checksums=entry.get("parent_checksums", {}),
                output_crs_epsg=entry.get("output_crs_epsg"),
                created_by=entry.get("created_by"),
            )

        # Clean up flushed entries and links
        self._cleanup_chain(layer_id)

    def discard(self, layer_id: str) -> None:
        """Drop this layer's entries and remove it from the link graph.

        No-op if layer_id is unknown.
        """
        self._entries.pop(layer_id, None)
        self._links.pop(layer_id, None)
        # Also remove this layer_id from other nodes' parent lists
        for node_id in list(self._links.keys()):
            self._links[node_id] = [pid for pid in self._links[node_id] if pid != layer_id]
            if not self._links[node_id]:
                del self._links[node_id]

    def _cleanup_chain(self, layer_id: str) -> None:
        """Remove all entries and links for the flushed chain."""
        visited: set[str] = set()

        def _collect(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            for parent_id in self._links.get(node_id, []):
                _collect(parent_id)

        _collect(layer_id)
        for node_id in visited:
            self._entries.pop(node_id, None)
            # Remove this node as a parent reference from all remaining link lists
            for remaining_parents in self._links.values():
                try:
                    remaining_parents.remove(node_id)
                except ValueError:
                    pass
            self._links.pop(node_id, None)
