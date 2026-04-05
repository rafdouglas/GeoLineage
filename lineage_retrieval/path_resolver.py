import logging
import os

from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.path_resolver")


def extract_gpkg_path(source: str) -> str | None:
    """Extract the .gpkg file path from a QGIS layer source URI.

    QGIS vector layer source for GeoPackage looks like:
    '/path/to/file.gpkg|layername=tablename'

    Returns the path if the source refers to a GeoPackage file,
    or None otherwise.
    """
    if not source:
        return None
    path = source.split("|")[0]
    return path if path.endswith(".gpkg") else None


def resolve(parent_ref: str, project_dir: str) -> tuple[str, str]:
    """Resolve a parent file reference to an actual path.

    Tries relative path first (relative to project_dir), then absolute.

    Args:
        parent_ref: The stored path reference (could be relative or absolute)
        project_dir: The QGIS project directory for resolving relative paths

    Returns:
        (resolved_path, status) where status is 'found' or 'not_found'
    """
    # Try as relative path first
    relative_candidate = os.path.normpath(os.path.join(project_dir, parent_ref))
    if os.path.isfile(relative_candidate):
        return (relative_candidate, "found")

    # Try as absolute path
    absolute_candidate = os.path.normpath(parent_ref)
    if os.path.isfile(absolute_candidate):
        return (absolute_candidate, "found")

    # Not found
    return (parent_ref, "not_found")
