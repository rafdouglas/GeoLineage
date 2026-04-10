import hashlib
import logging
import sqlite3
import struct

from .settings import LINEAGE_TABLE, LOGGER_NAME, META_TABLE

logger = logging.getLogger(f"{LOGGER_NAME}.checksum")

# Type tags for byte-level serialization
_TAG_NULL = b"\x00"
_TAG_INTEGER = b"\x01"
_TAG_REAL = b"\x02"
_TAG_TEXT = b"\x03"
_TAG_BLOB = b"\x04"
_ROW_SENTINEL = b"\xff"

# Tables to exclude from checksum
_EXCLUDED_TABLES = {LINEAGE_TABLE, META_TABLE}


def _serialize_value(value) -> bytes:
    """Serialize a single SQLite value to bytes with type tag prefix."""
    if value is None:
        return _TAG_NULL + b"\x00"
    elif isinstance(value, int):
        return _TAG_INTEGER + struct.pack("!q", value)
    elif isinstance(value, float):
        return _TAG_REAL + struct.pack("!d", value)
    elif isinstance(value, str):
        return _TAG_TEXT + value.encode("utf-8")
    elif isinstance(value, bytes):
        return _TAG_BLOB + value
    else:
        raise TypeError(f"Unsupported SQLite type: {type(value)}")


def compute_checksum_via_conn(conn: sqlite3.Connection) -> str:
    """Compute a data-only SHA-256 checksum using an existing SQLite connection.

    See compute_checksum for the full algorithm description.
    """
    h = hashlib.sha256()
    cursor = conn.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name ASC")
    tables = [row[0] for row in cursor.fetchall() if row[0] not in _EXCLUDED_TABLES]

    for table_name in tables:
        h.update(table_name.encode("utf-8"))

        col_info = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        col_names = [info[1] for info in sorted(col_info, key=lambda x: x[0])]

        pk_cols = [row[1] for row in conn.execute(f"PRAGMA table_info('{table_name}')") if row[5] > 0]
        order_clause = ", ".join(f'"{c}"' for c in pk_cols) if pk_cols else "rowid"
        cols_sql = ", ".join(f'"{c}"' for c in col_names)
        rows = conn.execute(
            f'SELECT {cols_sql} FROM "{table_name}" ORDER BY {order_clause} ASC'  # noqa: S608  # nosec B608
        ).fetchall()

        for row in rows:
            for value in row:
                value_bytes = _serialize_value(value)
                h.update(len(value_bytes).to_bytes(4, "little"))
                h.update(value_bytes)
            h.update(_ROW_SENTINEL)

    return h.hexdigest()


def compute_checksum(gpkg_path: str) -> str:
    """Compute a data-only SHA-256 checksum of a GeoPackage file.

    - Queries gpkg_contents for registered table names
    - Excludes _lineage and _lineage_meta tables
    - Iterates tables in table name ASC order
    - For each table: hashes table name (UTF-8), then rows in rowid ASC order
    - For each row: columns in PRAGMA table_info cid order, each value serialized
      with type tag prefix
    - Row boundaries marked with sentinel byte 0xFF
    - Empty tables still contribute their table name to the hash

    Returns hex SHA-256 string.
    """
    h = hashlib.sha256()
    with sqlite3.connect(gpkg_path) as conn:
        # Get registered tables from gpkg_contents, sorted by name
        cursor = conn.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name ASC")
        tables = [row[0] for row in cursor.fetchall() if row[0] not in _EXCLUDED_TABLES]

        for table_name in tables:
            # Hash table name
            h.update(table_name.encode("utf-8"))

            # Get column names in cid order
            col_info = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            col_names = [info[1] for info in sorted(col_info, key=lambda x: x[0])]

            # Read all rows ordered by primary key columns (stable across VACUUM/re-insert).
            # Falls back to rowid for tables with no explicit PK (e.g. views).
            pk_cols = [
                row[1]
                for row in conn.execute(f"PRAGMA table_info('{table_name}')")
                if row[5] > 0  # column's pk index > 0 means it participates in the PK
            ]
            order_clause = ", ".join(f'"{c}"' for c in pk_cols) if pk_cols else "rowid"
            cols_sql = ", ".join(f'"{c}"' for c in col_names)
            rows = conn.execute(
                f'SELECT {cols_sql} FROM "{table_name}" ORDER BY {order_clause} ASC'  # noqa: S608  # nosec B608
            ).fetchall()

            for row in rows:
                for value in row:
                    value_bytes = _serialize_value(value)
                    h.update(len(value_bytes).to_bytes(4, "little"))
                    h.update(value_bytes)
                h.update(_ROW_SENTINEL)

    return h.hexdigest()
