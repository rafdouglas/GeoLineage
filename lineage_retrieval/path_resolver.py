import logging
import os
from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.path_resolver")


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
