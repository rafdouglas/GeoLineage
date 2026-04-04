import sqlite3

import pytest

from GeoLineage.lineage_core.memory_buffer import MemoryBuffer
from GeoLineage.lineage_core.settings import LINEAGE_TABLE


def _make_gpkg(path) -> str:
    """Create a minimal valid GeoPackage for testing."""
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


def _make_entry(layer_name: str = "rivers", tool: str = "clip") -> dict:
    return {
        "layer_name": layer_name,
        "tool": tool,
        "params": {"distance": 10},
        "parents": [],
        "parent_metadata": [],
        "parent_checksums": {},
        "output_crs_epsg": 4326,
        "created_by": "test",
    }


# ---------------------------------------------------------------------------
# 1. test_add_stores_entry
# ---------------------------------------------------------------------------


def test_add_stores_entry():
    buf = MemoryBuffer()
    entry = _make_entry("rivers")
    buf.add("layer-1", entry)

    chain = buf.get_chain("layer-1")

    assert len(chain) == 1
    assert chain[0] is entry


# ---------------------------------------------------------------------------
# 2. test_link_chain
# ---------------------------------------------------------------------------


def test_link_chain():
    buf = MemoryBuffer()
    a_entry = _make_entry("layer_a")
    b_entry = _make_entry("layer_b")
    c_entry = _make_entry("layer_c")

    buf.add("A", a_entry)
    buf.add("B", b_entry)
    buf.add("C", c_entry)
    buf.link("B", ["A"])
    buf.link("C", ["B"])

    chain = buf.get_chain("C")

    assert chain == [a_entry, b_entry, c_entry]


# ---------------------------------------------------------------------------
# 3. test_get_chain_unknown_id
# ---------------------------------------------------------------------------


def test_get_chain_unknown_id():
    buf = MemoryBuffer()
    chain = buf.get_chain("nonexistent")
    assert chain == []


# ---------------------------------------------------------------------------
# 4. test_link_empty_list_noop
# ---------------------------------------------------------------------------


def test_link_empty_list_noop():
    buf = MemoryBuffer()
    buf.add("X", _make_entry())
    buf.link("X", [])

    # No parents added — internal _links should not have "X"
    assert "X" not in buf._links

    chain = buf.get_chain("X")
    assert len(chain) == 1


# ---------------------------------------------------------------------------
# 5. test_cycle_detection
# ---------------------------------------------------------------------------


def test_cycle_detection():
    buf = MemoryBuffer()
    buf.add("A", _make_entry("a"))
    buf.add("B", _make_entry("b"))
    buf.link("A", ["B"])
    buf.link("B", ["A"])

    with pytest.raises(ValueError, match="Cycle detected"):
        buf.get_chain("A")


# ---------------------------------------------------------------------------
# 6. test_flush_writes_to_gpkg
# ---------------------------------------------------------------------------


def test_flush_writes_to_gpkg(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    buf = MemoryBuffer()

    a_entry = _make_entry("layer_a", "buffer")
    b_entry = _make_entry("layer_b", "clip")
    buf.add("A", a_entry)
    buf.add("B", b_entry)
    buf.link("B", ["A"])

    buf.flush("B", gpkg)

    with sqlite3.connect(gpkg) as conn:
        rows = conn.execute(f"SELECT layer_name, operation_tool FROM {LINEAGE_TABLE} ORDER BY id").fetchall()

    assert len(rows) == 2
    assert rows[0] == ("layer_a", "buffer")
    assert rows[1] == ("layer_b", "clip")


# ---------------------------------------------------------------------------
# 7. test_flush_unknown_noop
# ---------------------------------------------------------------------------


def test_flush_unknown_noop(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    buf = MemoryBuffer()

    # Should not raise and should not write anything
    buf.flush("ghost", gpkg)

    with sqlite3.connect(gpkg) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    # _lineage table should not even be created
    assert LINEAGE_TABLE not in tables


# ---------------------------------------------------------------------------
# 8. test_discard_removes_entries
# ---------------------------------------------------------------------------


def test_discard_removes_entries():
    buf = MemoryBuffer()
    buf.add("layer-1", _make_entry())
    buf.discard("layer-1")

    chain = buf.get_chain("layer-1")
    assert chain == []


# ---------------------------------------------------------------------------
# 9. test_discard_removes_from_links
# ---------------------------------------------------------------------------


def test_discard_removes_from_links():
    buf = MemoryBuffer()
    buf.add("A", _make_entry("a"))
    buf.add("B", _make_entry("b"))
    buf.add("C", _make_entry("c"))
    buf.link("B", ["A"])
    buf.link("C", ["B"])

    buf.discard("B")

    # B should be gone from C's parent list
    assert "B" not in buf._links.get("C", [])
    # B's own entry should be gone
    assert "B" not in buf._entries


# ---------------------------------------------------------------------------
# 10. test_flush_cleans_up
# ---------------------------------------------------------------------------


def test_flush_cleans_up(tmp_path):
    gpkg = _make_gpkg(tmp_path / "test.gpkg")
    buf = MemoryBuffer()

    buf.add("A", _make_entry("a"))
    buf.add("B", _make_entry("b"))
    buf.link("B", ["A"])

    buf.flush("B", gpkg)

    assert "A" not in buf._entries
    assert "B" not in buf._entries
    assert "A" not in buf._links
    assert "B" not in buf._links
