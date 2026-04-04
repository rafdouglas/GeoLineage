import sqlite3
import pytest


def _init_gpkg(conn: sqlite3.Connection) -> None:
    """Set the GeoPackage application ID and create required system tables."""
    conn.execute("PRAGMA application_id = 0x47504B47")
    conn.execute("""
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name                 TEXT    NOT NULL,
            srs_id                   INTEGER NOT NULL PRIMARY KEY,
            organization             TEXT    NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition               TEXT    NOT NULL,
            description              TEXT
        )
    """)
    conn.execute("""
        INSERT INTO gpkg_spatial_ref_sys VALUES (
            'WGS 84', 4326, 'EPSG', 4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
            'WGS 84 geographic coordinate system'
        )
    """)
    conn.execute("""
        CREATE TABLE gpkg_contents (
            table_name  TEXT      NOT NULL PRIMARY KEY,
            data_type   TEXT      NOT NULL,
            identifier  TEXT,
            description TEXT      DEFAULT '',
            last_change TIMESTAMP,
            min_x       DOUBLE,
            min_y       DOUBLE,
            max_x       DOUBLE,
            max_y       DOUBLE,
            srs_id      INTEGER   REFERENCES gpkg_spatial_ref_sys(srs_id)
        )
    """)
    conn.commit()


@pytest.fixture
def tmp_gpkg(tmp_path):
    """A minimal valid GeoPackage with a test_points table and a few rows."""
    path = tmp_path / "test.gpkg"
    conn = sqlite3.connect(str(path))
    _init_gpkg(conn)

    conn.execute("""
        CREATE TABLE test_points (
            id   INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO test_points (id, name) VALUES (?, ?)",
        [(1, "Alpha"), (2, "Beta"), (3, "Gamma")],
    )
    conn.execute("""
        INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id)
        VALUES ('test_points', 'attributes', 'test_points', 4326)
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def tmp_gpkg_factory(tmp_path):
    """
    Factory fixture that creates multiple GeoPackage files.

    Usage::

        def test_example(tmp_gpkg_factory):
            path = tmp_gpkg_factory("my_layer", rows=[(1, "A"), (2, "B")])
    """

    created: list = []

    def _make(table_name: str = "points", rows: list | None = None, index: int = 0):
        if rows is None:
            rows = [(1, "Row1"), (2, "Row2")]
        path = tmp_path / f"gpkg_{index}_{table_name}.gpkg"
        conn = sqlite3.connect(str(path))
        _init_gpkg(conn)
        conn.execute(f"""
            CREATE TABLE {table_name} (
                id   INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        conn.executemany(
            f"INSERT INTO {table_name} (id, name) VALUES (?, ?)",
            rows,
        )
        conn.execute(f"""
            INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id)
            VALUES ('{table_name}', 'attributes', '{table_name}', 4326)
        """)
        conn.commit()
        conn.close()
        created.append(path)
        return path

    return _make


@pytest.fixture
def empty_gpkg(tmp_path):
    """A valid GeoPackage with required system tables but no data tables."""
    path = tmp_path / "empty.gpkg"
    conn = sqlite3.connect(str(path))
    _init_gpkg(conn)
    conn.close()
    return path
