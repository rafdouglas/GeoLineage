"""Tests for lineage_retrieval.cache module."""

import os
import time

from GeoLineage.lineage_retrieval.cache import LineageCache


def test_get_miss():
    """get on an empty cache returns None."""
    cache = LineageCache()

    result = cache.get("/nonexistent/file.gpkg")

    assert result is None


def test_put_and_get(tmp_path):
    """put followed by get returns the stored data."""
    cache = LineageCache()
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"")
    data = {"nodes": [1, 2, 3]}

    cache.put(str(target), data)
    result = cache.get(str(target))

    assert result == data


def test_invalidate(tmp_path):
    """put then invalidate causes get to return None."""
    cache = LineageCache()
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"")

    cache.put(str(target), {"key": "value"})
    cache.invalidate(str(target))

    assert cache.get(str(target)) is None


def test_clear(tmp_path):
    """clear removes all entries; all subsequent gets return None."""
    cache = LineageCache()
    paths = []
    for name in ("a.gpkg", "b.gpkg", "c.gpkg"):
        p = tmp_path / name
        p.write_bytes(b"")
        cache.put(str(p), {"name": name})
        paths.append(str(p))

    cache.clear()

    for path in paths:
        assert cache.get(path) is None


def test_stale_mtime(tmp_path):
    """get returns None when the file's mtime has changed since put."""
    cache = LineageCache()
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"original")

    cache.put(str(target), {"version": 1})

    # Advance mtime by writing new content; ensure a measurable mtime difference
    time.sleep(0.01)
    target.write_bytes(b"modified")
    # Force a distinct mtime by nudging it forward if the filesystem resolution is coarse
    current = os.path.getmtime(str(target))
    os.utime(str(target), (current + 1.0, current + 1.0))

    result = cache.get(str(target))

    assert result is None


def test_file_deleted(tmp_path):
    """get returns None when the cached file has been deleted."""
    cache = LineageCache()
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"")

    cache.put(str(target), {"key": "value"})
    target.unlink()

    result = cache.get(str(target))

    assert result is None
