import json
import logging
import sqlite3
from lineage_core.schema import ensure_lineage_table
from lineage_core.settings import LINEAGE_TABLE, LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.recorder")


def record_processing(
    gpkg_path: str,
    layer_name: str,
    tool: str,
    params: dict,
    parents: list[str],
    parent_metadata: list[dict],
    parent_checksums: dict[str, str],
    output_crs_epsg: int | None = None,
    created_by: str | None = None,
) -> int:
    """Record a processing operation in the _lineage table.

    Returns the row id of the inserted entry.
    """
    ensure_lineage_table(gpkg_path)
    with sqlite3.connect(gpkg_path) as conn:
        cursor = conn.execute(
            f"""INSERT INTO {LINEAGE_TABLE}
            (layer_name, operation_summary, operation_tool, operation_params,
             parent_files, parent_metadata, parent_checksums, output_crs_epsg,
             created_by, entry_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing')""",
            (
                layer_name,
                _build_processing_summary(tool, params),
                tool,
                json.dumps(params),
                json.dumps(parents),
                json.dumps(parent_metadata),
                json.dumps(parent_checksums),
                output_crs_epsg,
                created_by,
            ),
        )
        return cursor.lastrowid


def record_edit(
    gpkg_path: str,
    layer_name: str,
    edit_summary: dict,
    created_by: str | None = None,
) -> int:
    """Record a manual edit in the _lineage table.

    edit_summary should have keys like: features_added, features_modified,
    features_deleted, attributes_modified.

    Returns the row id of the inserted entry.
    """
    ensure_lineage_table(gpkg_path)
    summary_text = _build_edit_summary_text(edit_summary)
    with sqlite3.connect(gpkg_path) as conn:
        cursor = conn.execute(
            f"""INSERT INTO {LINEAGE_TABLE}
            (layer_name, operation_summary, entry_type, edit_summary, created_by)
            VALUES (?, ?, 'manual_edit', ?, ?)""",
            (layer_name, summary_text, json.dumps(edit_summary), created_by),
        )
        return cursor.lastrowid


def record_export(
    gpkg_path: str,
    layer_name: str,
    parent_path: str,
    parent_metadata: list[dict],
    parent_checksums: dict[str, str],
    output_crs_epsg: int | None = None,
    created_by: str | None = None,
) -> int:
    """Record an export operation in the _lineage table.

    Returns the row id of the inserted entry.
    """
    ensure_lineage_table(gpkg_path)
    with sqlite3.connect(gpkg_path) as conn:
        cursor = conn.execute(
            f"""INSERT INTO {LINEAGE_TABLE}
            (layer_name, operation_summary, parent_files, parent_metadata,
             parent_checksums, output_crs_epsg, created_by, entry_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'export')""",
            (
                layer_name,
                f"Exported from {parent_path}",
                json.dumps([parent_path]),
                json.dumps(parent_metadata),
                json.dumps(parent_checksums),
                output_crs_epsg,
                created_by,
            ),
        )
        return cursor.lastrowid


def _build_processing_summary(tool: str, params: dict) -> str:
    """Build a human-readable summary from tool name and params."""
    short_name = tool.split(":")[-1] if ":" in tool else tool
    return short_name


def _build_edit_summary_text(edit_summary: dict) -> str:
    """Build human-readable text from edit summary dict."""
    parts = []
    if edit_summary.get("features_added", 0) > 0:
        parts.append(f"{edit_summary['features_added']} added")
    if edit_summary.get("features_modified", 0) > 0:
        parts.append(f"{edit_summary['features_modified']} modified")
    if edit_summary.get("features_deleted", 0) > 0:
        parts.append(f"{edit_summary['features_deleted']} deleted")
    if edit_summary.get("attributes_modified", 0) > 0:
        parts.append(f"{edit_summary['attributes_modified']} attrs modified")
    return f"Manual edit: {', '.join(parts)}" if parts else "Manual edit"
