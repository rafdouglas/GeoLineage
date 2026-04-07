"""Management operations on _lineage table.

Recording operations live in lineage_core/recorder.py.
Schema definitions live in lineage_core/schema.py.
"""

import json
import logging
import os
import sqlite3

from ..lineage_core.schema import read_lineage_rows
from ..lineage_core.settings import LINEAGE_TABLE, LOGGER_NAME, META_TABLE
from ..lineage_retrieval.path_resolver import resolve

logger = logging.getLogger(f"{LOGGER_NAME}.data_ops")

ALLOWED_FIELDS = frozenset({"operation_summary", "edit_summary"})


def read_all_entries(db_path: str) -> list[dict]:
    """Read all lineage entries from a GeoPackage.

    Delegates to schema.read_lineage_rows for forward-compatible reading.
    """
    return read_lineage_rows(db_path)


def update_entry_field(db_path: str, entry_id: int, field: str, value: str) -> None:
    """Update a single field on a _lineage row.

    Only fields in ALLOWED_FIELDS may be updated. parent_files modifications
    must go through relink_parent/batch_relink_prefix to preserve JSON structure.

    Raises:
        ValueError: If field is not in the allow-list.
    """
    if field not in ALLOWED_FIELDS:
        msg = f"Field {field!r} is not editable. Allowed: {sorted(ALLOWED_FIELDS)}"
        raise ValueError(msg)

    # field is from a hardcoded allow-list, safe to interpolate into SQL
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE {LINEAGE_TABLE} SET {field} = ? WHERE id = ?",  # noqa: S608  # nosec B608
            (value, entry_id),
        )


def delete_entry(db_path: str, entry_id: int) -> bool:
    """Delete a lineage entry by ID.

    Returns True if a row was deleted, False if no row matched.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"DELETE FROM {LINEAGE_TABLE} WHERE id = ?",  # noqa: S608  # nosec B608
            (entry_id,),
        )
        return cursor.rowcount > 0


def drop_lineage_tables(db_path: str) -> None:
    """Drop both _lineage and _lineage_meta tables from a GeoPackage.

    Idempotent — no error if tables are already absent.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {LINEAGE_TABLE}")  # noqa: S608  # nosec B608
        conn.execute(f"DROP TABLE IF EXISTS {META_TABLE}")  # noqa: S608  # nosec B608
    logger.info("Dropped lineage tables from %s", db_path)


def batch_drop_lineage(directory: str) -> list[dict]:
    """Drop lineage tables from all .gpkg files in a directory.

    Returns a list of result dicts: {"path": str, "success": bool, "error": str | None}.
    Individual file failures do not abort the batch.
    """
    results = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".gpkg"):
            continue
        filepath = os.path.join(directory, filename)
        try:
            drop_lineage_tables(filepath)
            results.append({"path": filepath, "success": True, "error": None})
        except Exception as exc:  # noqa: BLE001
            results.append({"path": filepath, "success": False, "error": str(exc)})
    return results


def find_broken_parents(db_path: str, project_dir: str) -> list[dict]:
    """Find lineage entries with parent paths that don't exist on disk.

    Returns a list of dicts:
        {"entry_id": int, "parent_path": str, "resolved_path": str, "exists": bool}
    """
    entries = read_all_entries(db_path)
    broken = []
    for entry in entries:
        raw_parents = entry.get("parent_files", "")
        if not raw_parents:
            continue
        try:
            parents = json.loads(raw_parents) if isinstance(raw_parents, str) else raw_parents
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parents, list):
            continue
        for parent_path in parents:
            resolved_path, status = resolve(parent_path, project_dir)
            exists = status == "found"
            broken.append(
                {
                    "entry_id": entry["id"],
                    "parent_path": parent_path,
                    "resolved_path": resolved_path,
                    "exists": exists,
                }
            )
    return [item for item in broken if not item["exists"]]


def relink_parent(db_path: str, entry_id: int, old_path: str, new_path: str) -> None:
    """Replace a specific parent path in a lineage entry's parent_files JSON.

    Uses BEGIN IMMEDIATE to prevent concurrent read-modify-write races.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT parent_files FROM {LINEAGE_TABLE} WHERE id = ?",  # noqa: S608  # nosec B608
            (entry_id,),
        ).fetchone()
        if row is None:
            return
        raw = row[0]
        try:
            parents = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(parents, list):
            return
        updated = [new_path if p == old_path else p for p in parents]
        conn.execute(
            f"UPDATE {LINEAGE_TABLE} SET parent_files = ? WHERE id = ?",  # noqa: S608  # nosec B608
            (json.dumps(updated), entry_id),
        )
        conn.commit()
    finally:
        conn.close()


def batch_relink_prefix(db_path: str, old_prefix: str, new_prefix: str) -> int:
    """Replace a path prefix in parent_files across all lineage entries.

    Returns the count of modified entries. All updates run within a single
    connection/transaction for atomicity.
    """
    conn = sqlite3.connect(db_path)
    modified_count = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(f"SELECT id, parent_files FROM {LINEAGE_TABLE}").fetchall()  # noqa: S608  # nosec B608
        for row_id, raw in rows:
            if not raw:
                continue
            try:
                parents = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(parents, list):
                continue
            updated = [new_prefix + p[len(old_prefix) :] if p.startswith(old_prefix) else p for p in parents]
            if updated != parents:
                conn.execute(
                    f"UPDATE {LINEAGE_TABLE} SET parent_files = ? WHERE id = ?",  # noqa: S608  # nosec B608
                    (json.dumps(updated), row_id),
                )
                modified_count += 1
        conn.commit()
    finally:
        conn.close()
    return modified_count
