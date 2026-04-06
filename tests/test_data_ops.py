"""T1 tests for lineage_manager/data_ops.py — pure Python, no QGIS dependency."""

import json
import sqlite3

import pytest

from GeoLineage.lineage_core.schema import ensure_lineage_table
from GeoLineage.lineage_manager.data_ops import (
    batch_drop_lineage,
    batch_relink_prefix,
    delete_entry,
    drop_lineage_tables,
    find_broken_parents,
    read_all_entries,
    relink_parent,
    update_entry_field,
)


def _insert_entry(db_path, layer="layer1", summary="op", tool="native:buffer", parents=None, edit_summary=None):
    """Helper to insert a lineage entry and return its id."""
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            "INSERT INTO _lineage (layer_name, operation_summary, operation_tool, "
            "parent_files, entry_type, edit_summary) VALUES (?, ?, ?, ?, 'processing', ?)",
            (layer, summary, tool, json.dumps(parents or []), edit_summary),
        )
        return cursor.lastrowid


@pytest.fixture
def gpkg_with_lineage(tmp_gpkg):
    """A GeoPackage with lineage tables and a few entries."""
    ensure_lineage_table(str(tmp_gpkg))
    _insert_entry(tmp_gpkg, "points", "Buffer 10m", "native:buffer", ["/data/input.gpkg"])
    _insert_entry(tmp_gpkg, "lines", "Dissolve", "native:dissolve", ["/data/a.gpkg", "/data/b.gpkg"], "manual fix")
    return tmp_gpkg


class TestReadAllEntries:
    def test_read_all_entries(self, gpkg_with_lineage):
        entries = read_all_entries(str(gpkg_with_lineage))
        assert len(entries) == 2
        assert entries[0]["layer_name"] == "points"
        assert entries[1]["layer_name"] == "lines"

    def test_read_all_entries_empty(self, tmp_gpkg):
        ensure_lineage_table(str(tmp_gpkg))
        entries = read_all_entries(str(tmp_gpkg))
        assert entries == []


class TestUpdateEntryField:
    def test_update_entry_field_summary(self, gpkg_with_lineage):
        update_entry_field(str(gpkg_with_lineage), 1, "operation_summary", "Updated summary")
        entries = read_all_entries(str(gpkg_with_lineage))
        assert entries[0]["operation_summary"] == "Updated summary"

    def test_update_entry_field_edit_summary(self, gpkg_with_lineage):
        update_entry_field(str(gpkg_with_lineage), 2, "edit_summary", "New edit note")
        entries = read_all_entries(str(gpkg_with_lineage))
        assert entries[1]["edit_summary"] == "New edit note"

    def test_update_entry_field_rejects_disallowed(self, gpkg_with_lineage):
        with pytest.raises(ValueError, match="not editable"):
            update_entry_field(str(gpkg_with_lineage), 1, "parent_files", "bad")

    def test_update_entry_field_rejects_layer_name(self, gpkg_with_lineage):
        with pytest.raises(ValueError, match="not editable"):
            update_entry_field(str(gpkg_with_lineage), 1, "layer_name", "evil")


class TestDeleteEntry:
    def test_delete_entry(self, gpkg_with_lineage):
        result = delete_entry(str(gpkg_with_lineage), 1)
        assert result is True
        entries = read_all_entries(str(gpkg_with_lineage))
        assert len(entries) == 1

    def test_delete_entry_missing(self, gpkg_with_lineage):
        result = delete_entry(str(gpkg_with_lineage), 999)
        assert result is False


class TestDropLineageTables:
    def test_drop_lineage_tables(self, gpkg_with_lineage):
        drop_lineage_tables(str(gpkg_with_lineage))
        with sqlite3.connect(str(gpkg_with_lineage)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "_lineage" not in tables
        assert "_lineage_meta" not in tables
        # GeoPackage system tables still intact
        assert "gpkg_contents" in tables
        assert "gpkg_spatial_ref_sys" in tables

    def test_drop_lineage_tables_idempotent(self, tmp_gpkg):
        # No lineage tables exist — should not error
        drop_lineage_tables(str(tmp_gpkg))
        drop_lineage_tables(str(tmp_gpkg))


class TestBatchDropLineage:
    def test_batch_drop_lineage(self, tmp_gpkg_factory):
        p1 = tmp_gpkg_factory("t1", index=0)
        p2 = tmp_gpkg_factory("t2", index=1)
        ensure_lineage_table(str(p1))
        ensure_lineage_table(str(p2))

        results = batch_drop_lineage(str(p1.parent))
        assert len(results) == 2
        assert all(r["success"] for r in results)

    def test_batch_drop_lineage_handles_errors(self, tmp_path):
        # Create a non-SQLite file with .gpkg extension
        bad_file = tmp_path / "bad.gpkg"
        bad_file.write_text("not a database")

        good_file = tmp_path / "good.gpkg"
        conn = sqlite3.connect(str(good_file))
        conn.execute("PRAGMA application_id = 0x47504B47")
        conn.close()

        results = batch_drop_lineage(str(tmp_path))
        assert len(results) == 2
        # One should fail, one should succeed (order depends on sort)
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0]["error"] is not None


class TestFindBrokenParents:
    def test_find_broken_parents(self, gpkg_with_lineage):
        broken = find_broken_parents(str(gpkg_with_lineage), str(gpkg_with_lineage.parent))
        # /data/input.gpkg, /data/a.gpkg, /data/b.gpkg don't exist
        assert len(broken) == 3
        assert all(not item["exists"] for item in broken)
        paths = {item["parent_path"] for item in broken}
        assert "/data/input.gpkg" in paths
        assert "/data/a.gpkg" in paths
        assert "/data/b.gpkg" in paths

    def test_find_broken_parents_all_valid(self, tmp_gpkg, tmp_path):
        ensure_lineage_table(str(tmp_gpkg))
        # Create an actual parent file
        parent_file = tmp_path / "parent.gpkg"
        parent_file.touch()
        _insert_entry(tmp_gpkg, "layer", "op", "tool", [str(parent_file)])
        broken = find_broken_parents(str(tmp_gpkg), str(tmp_path))
        assert broken == []


class TestRelinkParent:
    def test_relink_parent(self, gpkg_with_lineage):
        relink_parent(str(gpkg_with_lineage), 1, "/data/input.gpkg", "/new/input.gpkg")
        entries = read_all_entries(str(gpkg_with_lineage))
        parents = json.loads(entries[0]["parent_files"])
        assert parents == ["/new/input.gpkg"]

    def test_relink_parent_preserves_others(self, gpkg_with_lineage):
        relink_parent(str(gpkg_with_lineage), 2, "/data/a.gpkg", "/new/a.gpkg")
        entries = read_all_entries(str(gpkg_with_lineage))
        parents = json.loads(entries[1]["parent_files"])
        assert parents == ["/new/a.gpkg", "/data/b.gpkg"]


class TestBatchRelinkPrefix:
    def test_batch_relink_prefix(self, gpkg_with_lineage):
        count = batch_relink_prefix(str(gpkg_with_lineage), "/data/", "/new/data/")
        assert count == 2
        entries = read_all_entries(str(gpkg_with_lineage))
        p1 = json.loads(entries[0]["parent_files"])
        p2 = json.loads(entries[1]["parent_files"])
        assert p1 == ["/new/data/input.gpkg"]
        assert p2 == ["/new/data/a.gpkg", "/new/data/b.gpkg"]

    def test_batch_relink_prefix_no_matches(self, gpkg_with_lineage):
        count = batch_relink_prefix(str(gpkg_with_lineage), "/nonexistent/", "/other/")
        assert count == 0
