import logging
import os
from lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.cache")


class LineageCache:
    """Simple cache for lineage graph data, keyed by (path, mtime).

    Automatically invalidates when a file's mtime changes.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}  # path -> (mtime, data)

    def get(self, path: str) -> object | None:
        """Get cached data for a path. Returns None on miss or stale mtime."""
        if path not in self._store:
            return None
        cached_mtime, data = self._store[path]
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            # File doesn't exist anymore
            del self._store[path]
            return None
        if current_mtime != cached_mtime:
            del self._store[path]
            return None
        return data

    def put(self, path: str, data: object) -> None:
        """Store data for a path, keyed by current mtime."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            logger.debug("Cannot cache %s: file not found", path)
            return
        self._store[path] = (mtime, data)

    def invalidate(self, path: str) -> None:
        """Remove a specific path from the cache."""
        self._store.pop(path, None)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()
