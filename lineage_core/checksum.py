import hashlib
import logging
import re
import sqlite3
import struct

from .settings import LINEAGE_TABLE, LOGGER_NAME, META_TABLE

logger = logging.getLogger(f"{LOGGER_NAME}.checksum")

# Table names from gpkg_contents are interpolated into PRAGMA/SELECT statements.
# They cannot be parameterized, so only accept plain SQL identifiers.
_VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
        if not _VALID_TABLE_NAME.match(table_name):
            logger.warning("Skipping table with non-identifier name in checksum: %r", table_name)
            continue

        h.update(table_name.encode("utf-8"))

        col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        col_names = [info[1] for info in sorted(col_info, key=lambda x: x[0])]

        # Order rows by primary key columns (stable across VACUUM/re-insert);
        # fall back to rowid for tables with no explicit PK (e.g. views).
        pk_cols = [info[1] for info in col_info if info[5] > 0]
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
    - For each table: hashes table name (UTF-8), then rows in PK (or rowid) order
    - For each row: columns in PRAGMA table_info cid order, each value serialized
      with type tag prefix
    - Row boundaries marked with sentinel byte 0xFF
    - Empty tables still contribute their table name to the hash

    Returns hex SHA-256 string.
    """
    with sqlite3.connect(gpkg_path) as conn:
        return compute_checksum_via_conn(conn)
