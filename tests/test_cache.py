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


def test_cache_evicts_oldest_entry_at_capacity(tmp_path):
    """Cache must not grow beyond its configured max size."""
    max_size = 4
    cache = LineageCache(max_size=max_size)
    for i in range(max_size + 2):
        f = tmp_path / f"layer_{i}.gpkg"
        f.write_bytes(f"v{i}".encode())
        cache.put(str(f), {"index": i})

    assert len(cache) <= max_size


def test_sub_second_mtime_change_detected(tmp_path):
    """A 1 ns mtime bump invisible to float64 must still be detected as stale.

    An exact integer-second timestamp is representable exactly in float64.
    The ULP of a ~1.7 × 10⁹ s value is ≈ 238 ns, so adding 1 ns keeps the
    same float while incrementing st_mtime_ns.  A float-based cache misses the
    change; an st_mtime_ns-based cache catches it.
    """
    f = tmp_path / "layer.gpkg"
    f.write_bytes(b"v1")

    # Align to an exact integer second so the float boundary is known precisely.
    t_ns = int(time.time()) * 1_000_000_000
    os.utime(f, ns=(t_ns, t_ns))

    # Confirm the float IS exact (pre-condition).
    t_float = os.path.getmtime(str(f))
    assert t_float == t_ns / 1_000_000_000, "pre-condition: integer second must be exact in float"

    cache = LineageCache()
    cache.put(str(f), {"version": 1})

    # Bump by 1 ns — guaranteed invisible to float64 (ULP ≈ 238 ns at 1.7 × 10⁹ s).
    os.utime(f, ns=(t_ns, t_ns + 1))
    assert os.path.getmtime(str(f)) == t_float, "pre-condition: 1 ns bump must be invisible to float"

    # With float-based cache: same float → returns cached data (BUG).
    # With st_mtime_ns-based cache: ns differs by 1 → returns None (CORRECT).
    assert cache.get(str(f)) is None
