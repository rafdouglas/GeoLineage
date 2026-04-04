import sqlite3

import pytest

from lineage_core.schema import ensure_lineage_table, get_schema_version, read_lineage_rows
from lineage_core.settings import LINEAGE_TABLE, META_TABLE


def _make_gpkg(path) -> str:
    """Create a minimal valid GeoPackage (SQLite file with gpkg_contents table)."""
    db_path = str(path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE,
                min_y DOUBLE,
                max_x DOUBLE,
                max_y DOUBLE,
                srs_id INTEGER
            );
        """)
    return db_path


def test_ensure_lineage_table_creates_tables(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert LINEAGE_TABLE in tables
    assert META_TABLE in tables


def test_ensure_lineage_table_idempotent(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)
    ensure_lineage_table(db_path)  # second call must not raise

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {META_TABLE} WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert count == 1


def test_lineage_not_in_gpkg_contents(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE table_name = ?",
            (LINEAGE_TABLE,),
        ).fetchone()

    assert row is None


def test_get_schema_version(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    assert get_schema_version(db_path) == "1"


def test_get_schema_version_missing_table(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    # No ensure_lineage_table call — _lineage_meta does not exist

    assert get_schema_version(db_path) is None


def test_read_lineage_rows_empty(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    rows = read_lineage_rows(db_path)

    assert rows == []


def test_read_lineage_rows_with_data(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {LINEAGE_TABLE}
                (layer_name, operation_summary, operation_tool, entry_type)
            VALUES
                ('rivers', 'Clipped to AOI', 'clip', 'processing')
            """
        )

    rows = read_lineage_rows(db_path)

    assert len(rows) == 1
    row = rows[0]
    assert row["layer_name"] == "rivers"
    assert row["operation_summary"] == "Clipped to AOI"
    assert row["operation_tool"] == "clip"
    assert row["entry_type"] == "processing"
    assert "id" in row


def test_read_lineage_rows_drops_unknown_columns(tmp_path):
    db_path = _make_gpkg(tmp_path / "test.gpkg")
    ensure_lineage_table(db_path)

    # Add a column not in KNOWN_COLUMNS to simulate a future schema migration
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"ALTER TABLE {LINEAGE_TABLE} ADD COLUMN future_field TEXT")
        conn.execute(
            f"""
            INSERT INTO {LINEAGE_TABLE}
                (layer_name, operation_summary, future_field)
            VALUES
                ('roads', 'Buffer 10m', 'some_future_value')
            """
        )

    rows = read_lineage_rows(db_path)

    assert len(rows) == 1
    assert "future_field" not in rows[0]
    assert rows[0]["layer_name"] == "roads"
