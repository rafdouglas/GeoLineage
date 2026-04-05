"""T1 tests for lineage_core.repair_lineage — no QGIS dependency required."""

import json
import sqlite3

from lineage_core.repair_lineage import repair_lineage
from lineage_core.settings import LINEAGE_TABLE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_gpkg(path) -> sqlite3.Connection:
    """Create a minimal GeoPackage (SQLite DB) with the _lineage table."""
    conn = sqlite3.connect(str(path))
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {LINEAGE_TABLE} (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_name          TEXT NOT NULL,
            operation_summary   TEXT NOT NULL,
            operation_tool      TEXT,
            operation_params    TEXT,
            parent_files        TEXT,
            parent_metadata     TEXT,
            parent_checksums    TEXT,
            output_crs_epsg     INTEGER,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by          TEXT,
            entry_type          TEXT NOT NULL DEFAULT 'processing',
            edit_summary        TEXT,
            qgis_sketcher       TEXT
        );
    """)
    return conn


def _insert_row(
    conn: sqlite3.Connection,
    *,
    layer_name: str = "test_layer",
    operation_summary: str = "test op",
    operation_tool: str | None = None,
    operation_params: str | None = None,
    parent_files: str | None = None,
) -> int:
    cur = conn.execute(
        f"""INSERT INTO {LINEAGE_TABLE}
            (layer_name, operation_summary, operation_tool, operation_params, parent_files)
            VALUES (?, ?, ?, ?, ?)""",
        (layer_name, operation_summary, operation_tool, operation_params, parent_files),
    )
    conn.commit()
    return cur.lastrowid


def _get_parent_files(conn: sqlite3.Connection, row_id: int) -> str | None:
    row = conn.execute(f"SELECT parent_files FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_repair_nested_inputs(tmp_path):
    """Nested 'inputs' dict is unwrapped and INPUT path is extracted."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {"inputs": {"INPUT": "/path/to/source.gpkg|layername=foo"}}
    row_id = _insert_row(conn, operation_params=json.dumps(params), parent_files="[]")
    conn.close()

    results = repair_lineage(str(gpkg))

    assert len(results) == 1
    assert results[0]["id"] == row_id
    assert results[0]["parents"] == ["/path/to/source.gpkg"]

    conn = sqlite3.connect(str(gpkg))
    stored = json.loads(_get_parent_files(conn, row_id))
    conn.close()
    assert stored == ["/path/to/source.gpkg"]


def test_repair_flat_params(tmp_path):
    """Flat (non-nested) INPUT param is also repaired."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {"INPUT": "/path/to/source.gpkg|layername=foo"}
    _insert_row(conn, operation_params=json.dumps(params), parent_files="[]")
    conn.close()

    results = repair_lineage(str(gpkg))

    assert len(results) == 1
    assert results[0]["parents"] == ["/path/to/source.gpkg"]


def test_no_op_when_populated(tmp_path):
    """Rows with a non-empty parent_files array are left untouched."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    existing = json.dumps(["/existing.gpkg"])
    params = {"INPUT": "/other.gpkg"}
    row_id = _insert_row(conn, operation_params=json.dumps(params), parent_files=existing)
    conn.close()

    results = repair_lineage(str(gpkg))

    assert results == []

    conn = sqlite3.connect(str(gpkg))
    stored = _get_parent_files(conn, row_id)
    conn.close()
    assert stored == existing


def test_malformed_json(tmp_path):
    """Rows with malformed operation_params JSON are skipped without crash."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    _insert_row(conn, operation_params="not valid json", parent_files="[]")
    conn.close()

    results = repair_lineage(str(gpkg))

    assert results == []


def test_strips_layername_suffix(tmp_path):
    """The |layername=xxx suffix is stripped from paths."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {"INPUT": "/data/cities.gpkg|layername=cities_2024"}
    _insert_row(conn, operation_params=json.dumps(params), parent_files=None)
    conn.close()

    results = repair_lineage(str(gpkg))

    assert len(results) == 1
    assert results[0]["parents"] == ["/data/cities.gpkg"]


def test_only_gpkg_paths(tmp_path):
    """Non-.gpkg paths are filtered out; only .gpkg paths are kept."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {
        "INPUT": "/data/source.gpkg",
        "INPUT_LAYER": "/data/source.shp",
        "OVERLAY": "/data/overlay.csv",
    }
    _insert_row(conn, operation_params=json.dumps(params), parent_files="[]")
    conn.close()

    results = repair_lineage(str(gpkg))

    assert len(results) == 1
    assert results[0]["parents"] == ["/data/source.gpkg"]


def test_missing_lineage_table(tmp_path):
    """GeoPackage without _lineage table returns empty list without crash."""
    gpkg = tmp_path / "no_lineage.gpkg"
    # Create a plain SQLite file with no lineage table.
    conn = sqlite3.connect(str(gpkg))
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    results = repair_lineage(str(gpkg))

    assert results == []


def test_multiple_input_keys(tmp_path):
    """Both OVERLAY and INPUT paths are extracted when present."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {
        "INPUT": "/data/base.gpkg|layername=base",
        "OVERLAY": "/data/overlay.gpkg|layername=overlay",
    }
    _insert_row(conn, operation_params=json.dumps(params), parent_files="[]")
    conn.close()

    results = repair_lineage(str(gpkg))

    assert len(results) == 1
    parents = results[0]["parents"]
    assert "/data/base.gpkg" in parents
    assert "/data/overlay.gpkg" in parents
    assert len(parents) == 2


def test_idempotent(tmp_path):
    """Running repair twice leaves state unchanged on the second run."""
    gpkg = tmp_path / "test.gpkg"
    conn = _create_gpkg(gpkg)
    params = {"INPUT": "/data/source.gpkg|layername=src"}
    row_id = _insert_row(conn, operation_params=json.dumps(params), parent_files="[]")
    conn.close()

    first = repair_lineage(str(gpkg))
    assert len(first) == 1

    second = repair_lineage(str(gpkg))
    assert second == []

    conn = sqlite3.connect(str(gpkg))
    stored = json.loads(_get_parent_files(conn, row_id))
    conn.close()
    assert stored == ["/data/source.gpkg"]
