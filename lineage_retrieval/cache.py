import logging
import os
from collections import OrderedDict

from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.cache")


class LineageCache:
    """Simple cache for lineage graph data, keyed by (path, mtime_ns).

    Automatically invalidates when a file's mtime changes.  Uses
    st_mtime_ns (nanosecond integer) rather than st_mtime (float) to
    avoid float64 precision loss (~200 ns ULP at current epoch timestamps).
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, tuple[int, object]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._store)

    def get(self, path: str) -> object | None:
        """Get cached data for a path. Returns None on miss or stale mtime."""
        if path not in self._store:
            return None
        cached_mtime_ns, data = self._store[path]
        try:
            current_mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            # File doesn't exist anymore
            del self._store[path]
            return None
        if current_mtime_ns != cached_mtime_ns:
            del self._store[path]
            return None
        self._store.move_to_end(path)  # mark as recently used
        return data

    def put(self, path: str, data: object) -> None:
        """Store data for a path, keyed by current mtime_ns."""
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            logger.debug("Cannot cache %s: file not found", path)
            return
        self._store[path] = (mtime_ns, data)
        self._store.move_to_end(path)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)  # evict LRU (oldest)

    def invalidate(self, path: str) -> None:
        """Remove a specific path from the cache."""
        self._store.pop(path, None)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()
