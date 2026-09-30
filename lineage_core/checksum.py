import hashlib
import logging
import sqlite3
import struct

from .db import connect
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


def _quote_identifier(name: str) -> str:
    """Quote a SQLite identifier, escaping embedded double quotes."""
    return '"' + name.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    """Quote a SQLite string literal, escaping embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def compute_checksum_via_conn(conn: sqlite3.Connection) -> str:
    """Compute a data-only SHA-256 checksum using an existing SQLite connection.

    See compute_checksum for the full algorithm description.
    """
    h = hashlib.sha256()
    cursor = conn.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name ASC")
    tables = [row[0] for row in cursor.fetchall() if row[0] not in _EXCLUDED_TABLES]

    for table_name in tables:
        # PRAGMA table_info returns no rows for a table that gpkg_contents still
        # lists but that no longer exists (stale registration left by other tools).
        col_info = conn.execute(f"PRAGMA table_info({_quote_string(table_name)})").fetchall()
        if not col_info:
            logger.warning("gpkg_contents lists %r but the table does not exist; skipping it in checksum", table_name)
            continue

        h.update(table_name.encode("utf-8"))

        # Column names in cid order
        col_names = [info[1] for info in sorted(col_info, key=lambda x: x[0])]

        # Order by primary key columns (stable across VACUUM/re-insert).
        # Falls back to rowid for tables with no explicit PK (e.g. views).
        pk_cols = [info[1] for info in col_info if info[5] > 0]
        order_clause = ", ".join(_quote_identifier(c) for c in pk_cols) if pk_cols else "rowid"
        cols_sql = ", ".join(_quote_identifier(c) for c in col_names)
        rows = conn.execute(
            f"SELECT {cols_sql} FROM {_quote_identifier(table_name)} ORDER BY {order_clause} ASC"  # noqa: S608  # nosec B608
        )

        # Iterate the cursor instead of fetchall() so large tables are not
        # materialised in memory.
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
    - Skips tables registered in gpkg_contents that no longer exist
    - Iterates tables in table name ASC order
    - For each table: hashes table name (UTF-8), then rows in primary-key
      (or rowid) ASC order
    - For each row: columns in PRAGMA table_info cid order, each value serialized
      with type tag prefix
    - Row boundaries marked with sentinel byte 0xFF
    - Empty tables still contribute their table name to the hash

    Returns hex SHA-256 string.
    """
    with connect(gpkg_path, query_only=True) as conn:
        return compute_checksum_via_conn(conn)
