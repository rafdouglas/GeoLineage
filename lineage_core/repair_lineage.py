"""Repair historically broken lineage records.

Scans _lineage rows where parent_files is empty and reconstructs
parent paths from operation_params JSON. Safe to run multiple times
(idempotent: rows with populated parent_files are left untouched).

Usage:
    python -m lineage_core.repair_lineage /path/to/file.gpkg
"""

import json
import logging
import sqlite3

from .settings import LINEAGE_TABLE, LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.repair_lineage")

# Keys in operation_params that may reference parent layers.
_PARENT_KEYS = ("INPUT", "INPUT_LAYER", "OVERLAY", "LAYER", "SOURCE_LAYER", "INPUT1", "INPUT2", "LAYERS")


def _extract_parents_from_params(params: dict) -> list[str]:
    """Extract gpkg parent paths from operation params dict.

    Handles the nested 'inputs' dict (same unwrap logic as hooks.py) and
    strips |layername=... suffixes.  Only paths ending in .gpkg are returned.
    """
    # Unwrap nested inputs dict (dialog hook pattern).
    inner = params.get("inputs")
    if isinstance(inner, dict):
        params = {**params, **inner}

    paths: list[str] = []
    for key in _PARENT_KEYS:
        value = params.get(key)
        if value is None:
            continue
        # LAYERS key may hold a list of paths.
        candidates: list[str] = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            # Strip |layername=... suffix.
            path = candidate.split("|")[0].strip()
            if path.lower().endswith(".gpkg"):
                paths.append(path)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def repair_lineage(gpkg_path: str) -> list[dict]:
    """Repair broken parent_files in lineage table.

    Scans rows where parent_files is NULL, empty string, or '[]' and
    attempts to reconstruct the parent list from operation_params.

    Returns a list of dicts describing each repaired row:
        {"id": int, "operation_tool": str | None, "parents": list[str]}
    """
    repaired: list[dict] = []

    try:
        conn = sqlite3.connect(gpkg_path)
    except sqlite3.Error as exc:
        logger.error("Cannot open %s: %s", gpkg_path, exc)
        return repaired

    try:
        # Check that the table exists.
        try:
            rows = conn.execute(
                f"SELECT id, operation_tool, operation_params, parent_files FROM {LINEAGE_TABLE}"  # noqa: S608  # nosec B608
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("Table %s not found in %s: %s", LINEAGE_TABLE, gpkg_path, exc)
            return repaired

        for row_id, operation_tool, operation_params_raw, parent_files_raw in rows:
            # Skip rows that already have a non-empty parent array.
            if parent_files_raw not in (None, "", "[]"):
                try:
                    existing = json.loads(parent_files_raw)
                    if isinstance(existing, list) and existing:
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass

            # Parse operation_params.
            if not operation_params_raw:
                continue
            try:
                params = json.loads(operation_params_raw)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Row %d: malformed operation_params JSON — skipping", row_id)
                continue

            if not isinstance(params, dict):
                continue

            parents = _extract_parents_from_params(params)
            if not parents:
                continue

            new_parent_files = json.dumps(parents)
            try:
                conn.execute(
                    f"UPDATE {LINEAGE_TABLE} SET parent_files = ? WHERE id = ?",  # noqa: S608  # nosec B608
                    (new_parent_files, row_id),
                )
                conn.commit()
            except sqlite3.Error as exc:
                logger.error("Row %d: failed to update parent_files: %s", row_id, exc)
                continue

            logger.info(
                "Repaired row id=%d operation_tool=%r parents=%r",
                row_id,
                operation_tool,
                parents,
            )
            repaired.append({"id": row_id, "operation_tool": operation_tool, "parents": parents})

    finally:
        conn.close()

    return repaired


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) != 2:
        print("Usage: python -m lineage_core.repair_lineage <path/to/file.gpkg>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    results = repair_lineage(path)
    if results:
        print(f"Repaired {len(results)} row(s):")
        for entry in results:
            print(f"  id={entry['id']} tool={entry['operation_tool']!r} parents={entry['parents']}")
    else:
        print("No rows repaired.")
