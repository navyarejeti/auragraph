"""
db_pool.py — SQLite connection pool for AuraGraph.

Problem solved: the naive pattern of sqlite3.connect() / con.close() on every
query creates a new OS file handle, re-reads the WAL header, and re-acquires
directory locks on every single call.  Under moderate concurrency (5+ requests/s)
this becomes the dominant latency component.

Solution: one long-lived connection per (DB path, thread).
  - Thread-local storage keeps it safe without a mutex.
  - WAL + synchronous=NORMAL gives the best write throughput while remaining
    crash-safe (no full fsync on every transaction).
  - 8 MB page cache reduces repeated page loads for large notebooks.
  - Connections are never closed (process lifetime == connection lifetime).

Usage (drop-in replacement for the old per-query _conn() pattern):

    from agents.db_pool import pooled_conn
    from pathlib import Path

    DB = str(Path(__file__).parent.parent / "auragraph.db")

    # Old pattern:
    @contextmanager
    def _conn():
        con = sqlite3.connect(DB, ...)
        ...

    # New pattern:
    def _conn():               # note: NOT a generator — returns a context manager
        return pooled_conn(DB)
"""

import sqlite3
import threading
from contextlib import contextmanager

_local = threading.local()


def _open(db_path: str) -> sqlite3.Connection:
    """Open and configure a new connection (called at most once per thread per path)."""
    con = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA synchronous=NORMAL")   # crash-safe but avoids full fsync
    con.execute("PRAGMA cache_size=-8000")     # 8 MB page cache
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def get_conn(db_path: str) -> sqlite3.Connection:
    """Return the thread-local connection for *db_path*, opening it on first use."""
    cache = getattr(_local, "conns", None)
    if cache is None:
        _local.conns = {}
        cache = _local.conns
    if db_path not in cache:
        cache[db_path] = _open(db_path)
    return cache[db_path]


@contextmanager
def pooled_conn(db_path: str):
    """
    Context manager that yields the thread-local connection for *db_path*.
    Commits on clean exit, rolls back on exception.
    The connection is NOT closed — it lives for the process lifetime.
    """
    con = get_conn(db_path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
