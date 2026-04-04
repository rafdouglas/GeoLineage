"""Tests for lineage_core.checksum module."""

import sqlite3

import pytest

from lineage_core.checksum import compute_checksum
from lineage_core.settings import LINEAGE_TABLE, META_TABLE


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_gpkg(path):
    """Create a minimal valid GeoPackage and return the open connection."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA application_id = 0x47504B47")
    conn.execute("""CREATE TABLE gpkg_spatial_ref_sys (
        srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
        organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
        definition TEXT NOT NULL, description TEXT)""")
    conn.execute(
        "INSERT INTO gpkg_spatial_ref_sys VALUES "
        "('WGS 84', 4326, 'EPSG', 4326, 'GEOGCS[\"WGS 84\"]', 'WGS 84')"
    )
    conn.execute("""CREATE TABLE gpkg_contents (
        table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
        identifier TEXT, description TEXT DEFAULT '', last_change TIMESTAMP,
        min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
        srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id))""")
    return conn


def _register_table(conn, table_name):
    conn.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) "
        "VALUES (?, 'attributes', ?, 4326)",
        (table_name, table_name),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_compute_checksum_returns_hex_string(tmp_path):
    """Result is a 64-character lowercase hex string (SHA-256)."""
    path = tmp_path / "a.gpkg"
    conn = _make_gpkg(path)
    conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO pts VALUES (1, 'Alpha')")
    _register_table(conn, "pts")
    conn.commit()
    conn.close()

    result = compute_checksum(str(path))

    assert isinstance(result, str)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_identical_data_same_checksum(tmp_path):
    """Two GeoPackages with identical data produce the same checksum."""
    rows = [(1, "Alpha"), (2, "Beta")]

    def _build(name):
        path = tmp_path / name
        conn = _make_gpkg(path)
        conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany("INSERT INTO pts VALUES (?, ?)", rows)
        _register_table(conn, "pts")
        conn.commit()
        conn.close()
        return path

    path_a = _build("a.gpkg")
    path_b = _build("b.gpkg")

    assert compute_checksum(str(path_a)) == compute_checksum(str(path_b))


def test_different_data_different_checksum(tmp_path):
    """Changing a row value produces a different checksum."""
    def _build(name, value):
        path = tmp_path / name
        conn = _make_gpkg(path)
        conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO pts VALUES (1, ?)", (value,))
        _register_table(conn, "pts")
        conn.commit()
        conn.close()
        return path

    path_a = _build("a.gpkg", "Alpha")
    path_b = _build("b.gpkg", "Beta")

    assert compute_checksum(str(path_a)) != compute_checksum(str(path_b))


def test_excludes_lineage_tables(tmp_path):
    """Adding _lineage / _lineage_meta data does not change the checksum."""
    def _build(name, include_lineage):
        path = tmp_path / name
        conn = _make_gpkg(path)
        conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO pts VALUES (1, 'Alpha')")
        _register_table(conn, "pts")
        if include_lineage:
            conn.execute(
                f"CREATE TABLE {LINEAGE_TABLE} (id INTEGER PRIMARY KEY, data TEXT)"
            )
            conn.execute(
                f"INSERT INTO {LINEAGE_TABLE} VALUES (1, 'some lineage data')"
            )
            _register_table(conn, LINEAGE_TABLE)
            conn.execute(
                f"CREATE TABLE {META_TABLE} (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(f"INSERT INTO {META_TABLE} VALUES ('version', '1')")
            _register_table(conn, META_TABLE)
        conn.commit()
        conn.close()
        return path

    path_without = _build("without.gpkg", include_lineage=False)
    path_with = _build("with.gpkg", include_lineage=True)

    assert compute_checksum(str(path_without)) == compute_checksum(str(path_with))


def test_empty_table_contributes_name(tmp_path):
    """A registered empty table changes the checksum versus no table at all."""
    # GeoPackage with no registered data tables
    path_no_table = tmp_path / "no_table.gpkg"
    conn = _make_gpkg(path_no_table)
    conn.commit()
    conn.close()

    # GeoPackage with an empty registered table
    path_empty_table = tmp_path / "empty_table.gpkg"
    conn = _make_gpkg(path_empty_table)
    conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
    _register_table(conn, "pts")
    conn.commit()
    conn.close()

    assert compute_checksum(str(path_no_table)) != compute_checksum(str(path_empty_table))


def test_null_values_serialized(tmp_path):
    """A table with NULL values produces a valid (non-crashing) checksum."""
    path = tmp_path / "nulls.gpkg"
    conn = _make_gpkg(path)
    conn.execute("CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO pts VALUES (1, NULL)")
    conn.execute("INSERT INTO pts VALUES (2, 'Present')")
    _register_table(conn, "pts")
    conn.commit()
    conn.close()

    result = compute_checksum(str(path))

    assert isinstance(result, str)
    assert len(result) == 64


def test_type_tag_differentiation(tmp_path):
    """Integer 0 and NULL produce different checksums (type tags distinguish them)."""
    def _build(name, value):
        path = tmp_path / name
        conn = _make_gpkg(path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val)")
        conn.execute("INSERT INTO t VALUES (1, ?)", (value,))
        _register_table(conn, "t")
        conn.commit()
        conn.close()
        return path

    path_zero = _build("zero.gpkg", 0)
    path_null = _build("null.gpkg", None)

    assert compute_checksum(str(path_zero)) != compute_checksum(str(path_null))


def test_column_order_deterministic(tmp_path):
    """Checksum uses PRAGMA cid order, producing a stable result on repeated calls."""
    path = tmp_path / "det.gpkg"
    conn = _make_gpkg(path)
    conn.execute(
        "CREATE TABLE pts (id INTEGER PRIMARY KEY, name TEXT, score REAL)"
    )
    conn.execute("INSERT INTO pts VALUES (1, 'Alpha', 9.5)")
    conn.execute("INSERT INTO pts VALUES (2, 'Beta', 7.0)")
    _register_table(conn, "pts")
    conn.commit()
    conn.close()

    first = compute_checksum(str(path))
    second = compute_checksum(str(path))

    assert first == second
