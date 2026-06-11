import logging
import sqlite3

from .settings import LINEAGE_TABLE, LOGGER_NAME, META_TABLE, SCHEMA_VERSION

logger = logging.getLogger(f"{LOGGER_NAME}.schema")

KNOWN_COLUMNS = {
    "id",
    "layer_name",
    "operation_summary",
    "operation_tool",
    "operation_params",
    "parent_files",
    "parent_metadata",
    "parent_checksums",
    "output_crs_epsg",
    "created_at",
    "created_by",
    "entry_type",
    "edit_summary",
    "qgis_sketcher",
}


def ensure_lineage_table(db_path: str) -> None:
    """Create _lineage and _lineage_meta tables if they don't exist. Idempotent.

    IMPORTANT: Do NOT register _lineage in gpkg_contents.
    Uses CREATE TABLE IF NOT EXISTS for idempotency.
    """
    with sqlite3.connect(db_path) as conn:
        ensure_lineage_table_via_conn(conn)
    logger.debug("Ensured lineage tables exist in %s", db_path)


def ensure_lineage_table_via_conn(conn: sqlite3.Connection) -> None:
    """Create lineage tables using an existing connection. Idempotent.

    Uses individual ``conn.execute()`` calls rather than ``executescript()`` so
    the caller's open transaction is preserved (``executescript`` implicitly
    commits, which would break an enclosing ``with conn:`` block).
    """
    # LINEAGE_TABLE, META_TABLE, SCHEMA_VERSION are module-level constants — safe to interpolate.
    conn.execute(
        f"""
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
    """  # noqa: S608  # nosec B608
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {META_TABLE} (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """  # noqa: S608  # nosec B608
    )
    conn.execute(
        f"INSERT OR IGNORE INTO {META_TABLE} VALUES ('schema_version', '{SCHEMA_VERSION}')"  # noqa: S608  # nosec B608
    )


def get_schema_version(db_path: str) -> str | None:
    """Read schema version from _lineage_meta. Returns None if table doesn't exist."""
    try:
        with sqlite3.connect(db_path) as conn:
            return get_schema_version_via_conn(conn)
    except sqlite3.OperationalError:
        return None


def get_schema_version_via_conn(conn: sqlite3.Connection) -> str | None:
    """Read schema version using an existing connection. Returns None if table doesn't exist."""
    try:
        row = conn.execute(f"SELECT value FROM {META_TABLE} WHERE key = 'schema_version'").fetchone()  # noqa: S608  # nosec B608
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def read_lineage_rows(db_path: str) -> list[dict]:
    """Read all rows from _lineage table. Returns list of dicts.

    Silently drops unknown keys (forward compatibility).
    Only includes these known keys: id, layer_name, operation_summary, operation_tool,
    operation_params, parent_files, parent_metadata, parent_checksums, output_crs_epsg,
    created_at, created_by, entry_type, edit_summary, qgis_sketcher
    """
    with sqlite3.connect(db_path) as conn:
        return read_lineage_rows_via_conn(conn)


def read_lineage_rows_via_conn(conn: sqlite3.Connection) -> list[dict]:
    """Read all rows from _lineage table using an existing connection.

    Silently drops unknown keys (forward compatibility).
    """
    pragma_rows = conn.execute(f"PRAGMA table_info({LINEAGE_TABLE})").fetchall()
    actual_columns = {row[1] for row in pragma_rows}
    select_columns = sorted(actual_columns & KNOWN_COLUMNS)

    if not select_columns:
        return []

    cols_sql = ", ".join(select_columns)
    rows = conn.execute(f"SELECT {cols_sql} FROM {LINEAGE_TABLE}").fetchall()  # noqa: S608  # nosec B608

    return [dict(zip(select_columns, row, strict=False)) for row in rows]
