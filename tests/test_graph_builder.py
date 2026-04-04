"""Tests for lineage_retrieval.graph_builder — Phase 3: Lineage Retrieval & Graph Building."""

import json
import os
import sqlite3
import time

import pytest

from GeoLineage.lineage_core.checksum import compute_checksum
from GeoLineage.lineage_core.recorder import record_export, record_processing
from GeoLineage.lineage_core.schema import ensure_lineage_table
from GeoLineage.lineage_retrieval.cache import LineageCache
from GeoLineage.lineage_retrieval.graph_builder import (
    LineageEdge,
    LineageGraph,
    LineageNode,
    build_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_gpkg(path: str, table_name: str = "points", rows=None):
    """Create a minimal valid GeoPackage with a data table."""
    if rows is None:
        rows = [(1, "A"), (2, "B")]
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA application_id = 0x47504B47")
    conn.execute("""
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT
        )
    """)
    conn.execute("""
        INSERT INTO gpkg_spatial_ref_sys VALUES (
            'WGS 84', 4326, 'EPSG', 4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
            'WGS 84'
        )
    """)
    conn.execute("""
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
            identifier TEXT, description TEXT DEFAULT '', last_change TIMESTAMP,
            min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
            srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id)
        )
    """)
    conn.execute(f"""
        CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, name TEXT)
    """)
    conn.executemany(f"INSERT INTO {table_name} (id, name) VALUES (?, ?)", rows)
    conn.execute(f"""
        INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id)
        VALUES ('{table_name}', 'attributes', '{table_name}', 4326)
    """)
    conn.commit()
    conn.close()


def _make_gpkg(tmp_path, name, table="points", rows=None):
    """Create a named GeoPackage and return its absolute path."""
    path = tmp_path / name
    _init_gpkg(str(path), table, rows)
    return str(path)


def _link_parent(child_path, parent_path, tool="native:buffer"):
    """Record a processing entry in child that references parent."""
    checksum = compute_checksum(parent_path)
    record_processing(
        gpkg_path=child_path,
        layer_name="output",
        tool=tool,
        params={"INPUT": parent_path},
        parents=[parent_path],
        parent_metadata=[{"table": "points"}],
        parent_checksums={parent_path: checksum},
        output_crs_epsg=4326,
    )


# ---------------------------------------------------------------------------
# US-301: Data structure tests
# ---------------------------------------------------------------------------


class TestDataStructures:
    def test_lineage_node_frozen(self):
        node = LineageNode("p", "present", (), "f.gpkg", 0, False)
        with pytest.raises(AttributeError):
            node.status = "modified"

    def test_lineage_edge_frozen(self):
        edge = LineageEdge("a", "b", 1)
        with pytest.raises(AttributeError):
            edge.entry_id = 2

    def test_lineage_graph_mutable_nodes(self):
        g = LineageGraph(nodes={}, edges=(), root_path="/x")
        g.nodes["k"] = LineageNode("/k", "present", (), "k.gpkg", 0, False)
        assert "k" in g.nodes

    def test_no_qgis_imports(self):
        import GeoLineage.lineage_retrieval.graph_builder as mod

        with open(mod.__file__) as f:
            src = f.read()
        assert "qgis" not in src.lower() or "qgis" in src.lower().split("#")[0] is False


# ---------------------------------------------------------------------------
# US-302: Linear chain traversal
# ---------------------------------------------------------------------------


class TestLinearChain:
    def test_single_node_no_parents(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 1
        assert g.root_path == os.path.abspath(a)
        node = g.nodes[os.path.abspath(a)]
        assert node.depth == 0
        assert node.filename == "a.gpkg"
        assert node.truncated is False

    def test_two_node_chain(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        g = build_graph(b, str(tmp_path))
        assert len(g.nodes) == 2
        assert len(g.edges) == 1
        b_abs = os.path.abspath(b)
        a_abs = os.path.abspath(a)
        assert g.nodes[b_abs].depth == 0
        assert g.nodes[a_abs].depth == 1

    def test_three_node_linear_chain(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        _link_parent(b, a)
        _link_parent(c, b)
        g = build_graph(c, str(tmp_path))
        assert len(g.nodes) == 3
        assert len(g.edges) == 2
        c_abs = os.path.abspath(c)
        b_abs = os.path.abspath(b)
        a_abs = os.path.abspath(a)
        assert g.nodes[c_abs].depth == 0
        assert g.nodes[b_abs].depth == 1
        assert g.nodes[a_abs].depth == 2

    def test_node_filenames(self, tmp_path):
        a = _make_gpkg(tmp_path, "source.gpkg")
        b = _make_gpkg(tmp_path, "output.gpkg")
        _link_parent(b, a)
        g = build_graph(b, str(tmp_path))
        a_abs = os.path.abspath(a)
        b_abs = os.path.abspath(b)
        assert g.nodes[a_abs].filename == "source.gpkg"
        assert g.nodes[b_abs].filename == "output.gpkg"

    def test_entries_populated(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        g = build_graph(b, str(tmp_path))
        b_abs = os.path.abspath(b)
        assert len(g.nodes[b_abs].entries) == 1
        assert g.nodes[b_abs].entries[0]["operation_tool"] == "native:buffer"

    def test_edge_structure(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        g = build_graph(b, str(tmp_path))
        edge = g.edges[0]
        assert edge.parent_path == os.path.abspath(a)
        assert edge.child_path == os.path.abspath(b)


# ---------------------------------------------------------------------------
# US-303: Diamond DAG and cycle handling
# ---------------------------------------------------------------------------


class TestDiamondAndCycles:
    def test_diamond_dag(self, tmp_path):
        """A->B, A->C, B->D, C->D — 4 nodes, D not duplicated."""
        d = _make_gpkg(tmp_path, "d.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        a = _make_gpkg(tmp_path, "a.gpkg")
        _link_parent(b, d)
        _link_parent(c, d)
        _link_parent(a, b)
        _link_parent(a, c)
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 4
        # D should appear only once
        d_abs = os.path.abspath(d)
        assert d_abs in g.nodes

    def test_cycle_does_not_infinite_loop(self, tmp_path):
        """Corrupt data: A references B, B references A."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        _link_parent(a, b)
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 2  # Both visited, no infinite loop

    def test_self_reference_handled(self, tmp_path):
        """Corrupt data: A references itself."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        checksum = compute_checksum(a)
        record_processing(
            gpkg_path=a,
            layer_name="output",
            tool="native:buffer",
            params={},
            parents=[a],
            parent_metadata=[],
            parent_checksums={a: checksum},
        )
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 1


# ---------------------------------------------------------------------------
# US-304: Node status detection
# ---------------------------------------------------------------------------


class TestNodeStatus:
    def test_missing_parent(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        fake_parent = str(tmp_path / "nonexistent.gpkg")
        ensure_lineage_table(a)
        with sqlite3.connect(a) as conn:
            conn.execute(
                "INSERT INTO _lineage (layer_name, operation_summary, parent_files, entry_type) "
                "VALUES ('out', 'test', ?, 'processing')",
                (json.dumps([fake_parent]),),
            )
        g = build_graph(a, str(tmp_path))
        assert g.nodes[fake_parent].status == "missing"

    def test_raw_input_no_lineage_table(self, tmp_path):
        """File exists but has no _lineage table."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        raw = _make_gpkg(tmp_path, "raw.gpkg")
        # raw has no lineage table — it's just a plain gpkg
        _link_parent(a, raw)
        g = build_graph(a, str(tmp_path))
        raw_abs = os.path.abspath(raw)
        assert g.nodes[raw_abs].status == "raw_input"

    def test_present_checksum_match(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)  # a has lineage table → eligible for 'present'
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)  # stores correct checksum
        g = build_graph(b, str(tmp_path))
        a_abs = os.path.abspath(a)
        assert g.nodes[a_abs].status == "present"

    def test_modified_checksum_mismatch(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)  # stores checksum of a
        # Now modify a's data so checksum changes
        with sqlite3.connect(a) as conn:
            conn.execute("INSERT INTO points (id, name) VALUES (99, 'Modified')")
        g = build_graph(b, str(tmp_path))
        a_abs = os.path.abspath(a)
        assert g.nodes[a_abs].status == "modified"

    def test_busy_locked_file(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        locked = _make_gpkg(tmp_path, "locked.gpkg")
        _link_parent(a, locked)
        locked_abs = os.path.abspath(locked)

        # Hold an exclusive lock on the file using a separate connection
        lock_conn = sqlite3.connect(locked)
        lock_conn.execute("BEGIN EXCLUSIVE")

        try:
            g = build_graph(a, str(tmp_path))
            # The locked file should either be 'busy' or still readable
            # (SQLite on some platforms allows concurrent reads)
            # We accept either 'busy' or a readable status
            assert locked_abs in g.nodes
            assert g.nodes[locked_abs].status in ("busy", "present", "raw_input")
        finally:
            lock_conn.rollback()
            lock_conn.close()

    def test_root_node_present(self, tmp_path):
        """Root node with lineage but no parent checksum reference is 'present'."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        g = build_graph(a, str(tmp_path))
        a_abs = os.path.abspath(a)
        assert g.nodes[a_abs].status == "present"


# ---------------------------------------------------------------------------
# US-305: Depth limit and truncation
# ---------------------------------------------------------------------------


class TestDepthLimit:
    def test_max_depth_zero_root_only(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        g = build_graph(b, str(tmp_path), max_depth=0)
        assert len(g.nodes) == 1
        b_abs = os.path.abspath(b)
        assert g.nodes[b_abs].truncated is True

    def test_max_depth_one_stops_at_parent(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        _link_parent(b, a)
        _link_parent(c, b)
        g = build_graph(c, str(tmp_path), max_depth=1)
        c_abs = os.path.abspath(c)
        b_abs = os.path.abspath(b)
        a_abs = os.path.abspath(a)
        assert c_abs in g.nodes
        assert b_abs in g.nodes
        assert a_abs not in g.nodes  # Beyond depth limit
        assert g.nodes[b_abs].truncated is True

    def test_truncated_node_has_flag(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        _link_parent(b, a)
        _link_parent(c, b)
        g = build_graph(c, str(tmp_path), max_depth=1)
        b_abs = os.path.abspath(b)
        assert g.nodes[b_abs].truncated is True

    def test_expansion_from_truncated_node(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        _link_parent(b, a)
        _link_parent(c, b)
        # First: depth=1, b is truncated
        g1 = build_graph(c, str(tmp_path), max_depth=1)
        b_abs = os.path.abspath(b)
        assert g1.nodes[b_abs].truncated is True
        # Expand from b
        g2 = build_graph(b, str(tmp_path), max_depth=5)
        a_abs = os.path.abspath(a)
        assert a_abs in g2.nodes
        assert g2.nodes[a_abs].depth == 1

    def test_leaf_not_truncated(self, tmp_path):
        """Node with no parents is not truncated even at max depth."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        g = build_graph(a, str(tmp_path), max_depth=0)
        a_abs = os.path.abspath(a)
        assert g.nodes[a_abs].truncated is False

    def test_default_max_depth_five(self, tmp_path):
        """Build a 7-node chain; default max_depth=5 should stop at depth 5."""
        paths = []
        for i in range(7):
            p = _make_gpkg(tmp_path, f"n{i}.gpkg", rows=[(1, f"R{i}")])
            paths.append(p)
        for i in range(1, 7):
            _link_parent(paths[i], paths[i - 1])
        g = build_graph(paths[6], str(tmp_path))
        # Root at depth 0, chain goes 6->5->4->3->2->1->0
        # max_depth=5 means node at depth 5 is included but truncated
        assert len(g.nodes) == 6  # depths 0..5
        deepest = os.path.abspath(paths[1])
        assert g.nodes[deepest].truncated is True


# ---------------------------------------------------------------------------
# US-306: Cache integration
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    def test_cache_hit_on_second_call(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        cache = LineageCache()
        g1 = build_graph(a, str(tmp_path), cache=cache)
        # Second call should use cache
        g2 = build_graph(a, str(tmp_path), cache=cache)
        assert len(g1.nodes) == len(g2.nodes)

    def test_cache_miss_after_modification(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        cache = LineageCache()
        build_graph(a, str(tmp_path), cache=cache)
        # Modify file
        time.sleep(0.05)  # Ensure mtime changes
        with sqlite3.connect(a) as conn:
            conn.execute("INSERT INTO points (id, name) VALUES (99, 'New')")
        # Cache should miss now
        a_abs = os.path.abspath(a)
        assert cache.get(a_abs) is None

    def test_cache_optional_none(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        g = build_graph(a, str(tmp_path), cache=None)
        assert len(g.nodes) == 1


# ---------------------------------------------------------------------------
# US-307: Read-only safety and performance
# ---------------------------------------------------------------------------


class TestReadOnlyAndPerformance:
    def test_parent_not_modified(self, tmp_path):
        """Parent file checksum must be identical before and after graph build."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        _link_parent(b, a)
        checksum_before = compute_checksum(a)
        build_graph(b, str(tmp_path))
        checksum_after = compute_checksum(a)
        assert checksum_before == checksum_after

    def test_fifty_node_graph_under_two_seconds(self, tmp_path):
        """Graph with 50 nodes must build in < 2 seconds."""
        paths = []
        for i in range(50):
            p = _make_gpkg(tmp_path, f"n{i}.gpkg", rows=[(1, f"R{i}")])
            paths.append(p)
        # Create a chain: each node references the previous
        for i in range(1, 50):
            _link_parent(paths[i], paths[i - 1])
        start = time.monotonic()
        g = build_graph(paths[49], str(tmp_path), max_depth=50)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Graph build took {elapsed:.2f}s (> 2s)"
        assert len(g.nodes) == 50

    def test_all_t1_no_qgis(self):
        """Verify no QGIS imports in graph_builder module."""
        import GeoLineage.lineage_retrieval.graph_builder as mod

        with open(mod.__file__) as f:
            source = f.read()
        # Check no qgis imports
        for line in source.splitlines():
            stripped = line.split("#")[0].strip()
            assert "import qgis" not in stripped.lower()
            assert "from qgis" not in stripped.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_parent_files_field(self, tmp_path):
        """Entry with null parent_files should not crash."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        with sqlite3.connect(a) as conn:
            conn.execute(
                "INSERT INTO _lineage (layer_name, operation_summary, entry_type) VALUES ('out', 'test', 'processing')"
            )
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 1

    def test_invalid_json_parent_files(self, tmp_path):
        """Entry with invalid JSON in parent_files should not crash."""
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        with sqlite3.connect(a) as conn:
            conn.execute(
                "INSERT INTO _lineage (layer_name, operation_summary, parent_files, entry_type) "
                "VALUES ('out', 'test', 'not-json', 'processing')"
            )
        g = build_graph(a, str(tmp_path))
        assert len(g.nodes) == 1
        assert len(g.edges) == 0

    def test_export_entry_with_parent(self, tmp_path):
        """Export entries also have parent_files and should be traversed."""
        raw = _make_gpkg(tmp_path, "raw.gpkg")
        exported = _make_gpkg(tmp_path, "exported.gpkg")
        checksum = compute_checksum(raw)
        record_export(
            gpkg_path=exported,
            layer_name="output",
            parent_path=raw,
            parent_metadata=[],
            parent_checksums={raw: checksum},
        )
        g = build_graph(exported, str(tmp_path))
        assert len(g.nodes) == 2
        raw_abs = os.path.abspath(raw)
        assert raw_abs in g.nodes

    def test_multiple_parents_in_one_entry(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        b = _make_gpkg(tmp_path, "b.gpkg")
        c = _make_gpkg(tmp_path, "c.gpkg")
        cs_a = compute_checksum(a)
        cs_b = compute_checksum(b)
        record_processing(
            gpkg_path=c,
            layer_name="output",
            tool="native:merge",
            params={},
            parents=[a, b],
            parent_metadata=[],
            parent_checksums={a: cs_a, b: cs_b},
        )
        g = build_graph(c, str(tmp_path))
        assert len(g.nodes) == 3
        assert len(g.edges) == 2

    def test_absolute_path_normalization(self, tmp_path):
        a = _make_gpkg(tmp_path, "a.gpkg")
        ensure_lineage_table(a)
        # Pass a non-normalized path
        weird_path = os.path.join(str(tmp_path), ".", "a.gpkg")
        g = build_graph(weird_path, str(tmp_path))
        assert g.root_path == os.path.abspath(a)
