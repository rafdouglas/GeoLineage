"""Shared SQLite connection helper.

``sqlite3.connect`` used as a context manager commits or rolls back but never
closes the connection, which keeps the GeoPackage file handle open until garbage
collection (and locks the file on Windows). Every module that touches a
GeoPackage goes through :func:`connect` so that connections are always closed.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator

DEFAULT_TIMEOUT = 5.0


@contextlib.contextmanager
def connect(db_path: str, timeout: float = DEFAULT_TIMEOUT, query_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection that is committed on success, rolled back on error and always closed."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        if query_only:
            conn.execute("PRAGMA query_only = ON")
        with conn:
            yield conn
    finally:
        conn.close()


def is_locked_error(exc: BaseException) -> bool:
    """Return True when an sqlite3 error means the database is locked or busy."""
    text = str(exc).lower()
    return "locked" in text or "busy" in text
