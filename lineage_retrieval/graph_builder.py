"""Build a lineage graph from a GeoPackage file by traversing parent references."""

import json
import logging
import os
import sqlite3
from collections import deque
from dataclasses import dataclass

from ..lineage_core.checksum import compute_checksum
from ..lineage_core.schema import get_schema_version, read_lineage_rows
from ..lineage_core.settings import LOGGER_NAME
from .cache import LineageCache
from .path_resolver import resolve

logger = logging.getLogger(f"{LOGGER_NAME}.graph_builder")


@dataclass(frozen=True)
class LineageNode:
    path: str
    status: str
    entries: tuple
    filename: str
    depth: int
    truncated: bool


@dataclass(frozen=True)
class LineageEdge:
    parent_path: str
    child_path: str
    entry_id: int


@dataclass
class LineageGraph:
    nodes: dict
    edges: tuple
    root_path: str


def _read_file_data(
    path: str,
    cache: LineageCache | None,
) -> tuple[str, list[dict]]:
    """Read lineage data from a GeoPackage file.

    Returns (status, entries) where status is one of:
    'present', 'raw_input', 'missing', 'busy'
    """
    if not os.path.isfile(path):
        return ("missing", [])

    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached

    try:
        conn = sqlite3.connect(path, timeout=2.0)
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError:
        return ("busy", [])

    try:
        version = get_schema_version(path)
        if version is None:
            result = ("raw_input", [])
        else:
            rows = read_lineage_rows(path)
            result = ("present", rows)
    except sqlite3.OperationalError:
        result = ("raw_input", [])
    finally:
        conn.close()

    if cache is not None:
        cache.put(path, result)

    return result


def build_graph(
    start_path: str,
    project_dir: str,
    max_depth: int = 5,
    cache: LineageCache | None = None,
) -> LineageGraph:
    """Build a lineage graph by traversing parent references from start_path."""
    start_path = os.path.abspath(start_path)

    nodes: dict[str, LineageNode] = {}
    edges: list[LineageEdge] = []
    visited: set[str] = set()
    # path -> expected checksum (recorded by a child that used this file as parent)
    expected_checksums: dict[str, str] = {}

    queue: deque[tuple[str, int]] = deque([(start_path, 0)])

    while queue:
        path, depth = queue.popleft()

        if path in visited:
            continue
        visited.add(path)

        status, entries = _read_file_data(path, cache)

        if status in ("missing", "busy"):
            nodes[path] = LineageNode(
                path=path,
                status=status,
                entries=(),
                filename=os.path.basename(path),
                depth=depth,
                truncated=False,
            )
            continue

        # Determine final status: checksum comparison can override base status
        if path in expected_checksums:
            try:
                actual = compute_checksum(path)
                node_status = "modified" if actual != expected_checksums[path] else status
            except Exception:
                logger.debug("Could not compute checksum for %s", path)
                node_status = status
        else:
            node_status = status

        # Collect all parent references across all entries
        parent_refs: list[tuple[str, int]] = []  # (parent_ref, entry_id)
        for entry in entries:
            raw_files = entry.get("parent_files")
            raw_checksums = entry.get("parent_checksums")
            entry_id = entry.get("id", 0)

            if not raw_files:
                continue

            try:
                parent_files = json.loads(raw_files)
            except (json.JSONDecodeError, TypeError):
                continue

            stored_checksums: dict[str, str] = {}
            if raw_checksums:
                try:
                    stored_checksums = json.loads(raw_checksums)
                except (json.JSONDecodeError, TypeError):
                    pass

            for parent_ref in parent_files:
                parent_refs.append((parent_ref, entry_id))
                if parent_ref in stored_checksums:
                    resolved_parent, _ = resolve(parent_ref, project_dir)
                    if resolved_parent not in expected_checksums:
                        expected_checksums[resolved_parent] = stored_checksums[parent_ref]

        # Determine if truncated (has parents but at max_depth)
        has_parents = len(parent_refs) > 0
        truncated = has_parents and depth >= max_depth

        nodes[path] = LineageNode(
            path=path,
            status=node_status,
            entries=tuple(entries),
            filename=os.path.basename(path),
            depth=depth,
            truncated=truncated,
        )

        # Enqueue parents and create edges
        for parent_ref, entry_id in parent_refs:
            resolved_parent, _ = resolve(parent_ref, project_dir)
            edges.append(LineageEdge(
                parent_path=resolved_parent,
                child_path=path,
                entry_id=entry_id,
            ))
            if depth < max_depth and resolved_parent not in visited:
                queue.append((resolved_parent, depth + 1))

    return LineageGraph(
        nodes=nodes,
        edges=tuple(edges),
        root_path=start_path,
    )
