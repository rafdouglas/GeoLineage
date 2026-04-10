"""Build a lineage graph from a GeoPackage file by traversing parent references."""

import contextlib
import json
import logging
import os
import sqlite3
from collections import deque
from dataclasses import dataclass

from ..lineage_core.checksum import compute_checksum_via_conn
from ..lineage_core.schema import (
    get_schema_version_via_conn,
    read_lineage_rows_via_conn,
)
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
) -> tuple[str, list[dict], str | None]:
    """Read lineage data from a GeoPackage file using a single SQLite connection.

    Returns (status, entries, checksum) where status is one of:
    'present', 'raw_input', 'missing', 'busy'
    and checksum is the computed data checksum (None for non-present files).
    """
    if not os.path.isfile(path):
        return ("missing", [], None)

    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached

    try:
        conn = sqlite3.connect(path, timeout=2.0)
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError:
        return ("busy", [], None)

    try:
        checksum = compute_checksum_via_conn(conn)
        version = get_schema_version_via_conn(conn)
        if version is None:
            result = ("raw_input", [], checksum)
        else:
            rows = read_lineage_rows_via_conn(conn)
            result = ("present", rows, checksum)
    except sqlite3.OperationalError:
        result = ("raw_input", [], None)
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
    # paths where two or more children disagree on the expected checksum → always "modified"
    force_modified: set[str] = set()

    queue: deque[tuple[str, int]] = deque([(start_path, 0)])

    while queue:
        path, depth = queue.popleft()

        if path in visited:
            continue
        visited.add(path)

        status, entries, actual_checksum = _read_file_data(path, cache)

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
        if path in force_modified:
            node_status = "modified"
        elif path in expected_checksums:
            if actual_checksum is not None:
                node_status = "modified" if actual_checksum != expected_checksums[path] else status
            else:
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
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    stored_checksums = json.loads(raw_checksums)

            for parent_ref in parent_files:
                parent_refs.append((parent_ref, entry_id))
                if parent_ref in stored_checksums:
                    resolved_parent, _ = resolve(parent_ref, project_dir)
                    recorded = stored_checksums[parent_ref]
                    if resolved_parent not in expected_checksums:
                        expected_checksums[resolved_parent] = recorded
                    elif expected_checksums[resolved_parent] != recorded:
                        # Two children disagree on expected checksum → parent was modified
                        force_modified.add(resolved_parent)

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
            edges.append(
                LineageEdge(
                    parent_path=resolved_parent,
                    child_path=path,
                    entry_id=entry_id,
                )
            )
            if depth < max_depth and resolved_parent not in visited:
                queue.append((resolved_parent, depth + 1))

    return LineageGraph(
        nodes=nodes,
        edges=tuple(edges),
        root_path=start_path,
    )
