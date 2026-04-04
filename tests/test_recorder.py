import json
import sqlite3

import pytest

from lineage_core.recorder import record_edit, record_export, record_processing
from lineage_core.settings import LINEAGE_TABLE


def _make_gpkg(path) -> str:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA application_id = 0x47504B47")
    conn.execute("""CREATE TABLE gpkg_spatial_ref_sys (
        srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
        organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
        definition TEXT NOT NULL, description TEXT)""")
    conn.execute(
        "INSERT INTO gpkg_spatial_ref_sys VALUES ('WGS 84', 4326, 'EPSG', 4326, 'GEOGCS[\"WGS 84\"]', 'WGS 84')"
    )
    conn.execute("""CREATE TABLE gpkg_contents (
        table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
        identifier TEXT, description TEXT DEFAULT '', last_change TIMESTAMP,
        min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
        srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id))""")
    conn.commit()
    conn.close()
    return str(path)


def test_record_processing_writes_row(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    row_id = record_processing(
        gpkg_path=gpkg,
        layer_name="rivers",
        tool="native:clip",
        params={"distance": 10},
        parents=["/data/input.gpkg"],
        parent_metadata=[{"name": "input", "rows": 100}],
        parent_checksums={"/data/input.gpkg": "abc123"},
        output_crs_epsg=4326,
        created_by="alice",
    )

    with sqlite3.connect(gpkg) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)
        ).fetchone()

    assert row is not None
    assert row["layer_name"] == "rivers"
    assert row["operation_tool"] == "native:clip"
    assert row["entry_type"] == "processing"
    assert row["output_crs_epsg"] == 4326
    assert row["created_by"] == "alice"
    assert row["operation_summary"] == "clip"


def test_record_processing_json_fields(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    params = {"distance": 10, "dissolve": True}
    parents = ["/data/a.gpkg", "/data/b.gpkg"]
    parent_metadata = [{"rows": 50}, {"rows": 75}]
    parent_checksums = {"/data/a.gpkg": "aaa", "/data/b.gpkg": "bbb"}

    row_id = record_processing(
        gpkg_path=gpkg,
        layer_name="roads",
        tool="native:buffer",
        params=params,
        parents=parents,
        parent_metadata=parent_metadata,
        parent_checksums=parent_checksums,
    )

    with sqlite3.connect(gpkg) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)
        ).fetchone()

    assert json.loads(row["operation_params"]) == params
    assert json.loads(row["parent_files"]) == parents
    assert json.loads(row["parent_metadata"]) == parent_metadata
    assert json.loads(row["parent_checksums"]) == parent_checksums


def test_record_edit_writes_row(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    edit_summary = {
        "features_added": 3,
        "features_modified": 1,
        "features_deleted": 0,
        "attributes_modified": 2,
    }

    row_id = record_edit(
        gpkg_path=gpkg,
        layer_name="parcels",
        edit_summary=edit_summary,
    )

    with sqlite3.connect(gpkg) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)
        ).fetchone()

    assert row is not None
    assert row["layer_name"] == "parcels"
    assert row["entry_type"] == "manual_edit"
    assert json.loads(row["edit_summary"]) == edit_summary


def test_record_export_writes_row(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    parent_path = "/data/source.gpkg"

    row_id = record_export(
        gpkg_path=gpkg,
        layer_name="buildings",
        parent_path=parent_path,
        parent_metadata=[{"rows": 200}],
        parent_checksums={parent_path: "deadbeef"},
        output_crs_epsg=32632,
    )

    with sqlite3.connect(gpkg) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)
        ).fetchone()

    assert row is not None
    assert row["layer_name"] == "buildings"
    assert row["entry_type"] == "export"
    parent_files = json.loads(row["parent_files"])
    assert parent_path in parent_files


def test_record_calls_ensure_lineage_table(tmp_path):
    """record_processing on a gpkg without lineage tables should create them."""
    gpkg = _make_gpkg(tmp_path / "fresh.gpkg")

    # Verify _lineage does not exist yet
    with sqlite3.connect(gpkg) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "_lineage" not in tables

    record_processing(
        gpkg_path=gpkg,
        layer_name="layer",
        tool="some:tool",
        params={},
        parents=[],
        parent_metadata=[],
        parent_checksums={},
    )

    with sqlite3.connect(gpkg) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "_lineage" in tables


def test_record_processing_returns_rowid(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")

    row_id = record_processing(
        gpkg_path=gpkg,
        layer_name="layer",
        tool="native:dissolve",
        params={},
        parents=[],
        parent_metadata=[],
        parent_checksums={},
    )

    assert isinstance(row_id, int)
    assert row_id > 0

    with sqlite3.connect(gpkg) as conn:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {LINEAGE_TABLE} WHERE id = ?", (row_id,)
        ).fetchone()[0]
    assert count == 1


def test_multiple_records(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")

    id1 = record_processing(
        gpkg_path=gpkg,
        layer_name="layer_a",
        tool="native:clip",
        params={"x": 1},
        parents=[],
        parent_metadata=[],
        parent_checksums={},
    )
    id2 = record_edit(
        gpkg_path=gpkg,
        layer_name="layer_b",
        edit_summary={"features_added": 5},
    )
    id3 = record_export(
        gpkg_path=gpkg,
        layer_name="layer_c",
        parent_path="/src.gpkg",
        parent_metadata=[],
        parent_checksums={},
    )

    with sqlite3.connect(gpkg) as conn:
        rows = conn.execute(f"SELECT id FROM {LINEAGE_TABLE} ORDER BY id").fetchall()

    ids = [r[0] for r in rows]
    assert len(ids) == 3
    assert id1 in ids
    assert id2 in ids
    assert id3 in ids
    assert len(set(ids)) == 3  # all unique


def test_record_with_created_by(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")

    proc_id = record_processing(
        gpkg_path=gpkg,
        layer_name="layer",
        tool="native:buffer",
        params={},
        parents=[],
        parent_metadata=[],
        parent_checksums={},
        created_by="bob",
    )
    edit_id = record_edit(
        gpkg_path=gpkg,
        layer_name="layer",
        edit_summary={"features_added": 1},
        created_by="carol",
    )
    export_id = record_export(
        gpkg_path=gpkg,
        layer_name="layer",
        parent_path="/src.gpkg",
        parent_metadata=[],
        parent_checksums={},
        created_by="dave",
    )

    with sqlite3.connect(gpkg) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            r["id"]: r
            for r in conn.execute(f"SELECT * FROM {LINEAGE_TABLE}").fetchall()
        }

    assert rows[proc_id]["created_by"] == "bob"
    assert rows[edit_id]["created_by"] == "carol"
    assert rows[export_id]["created_by"] == "dave"
