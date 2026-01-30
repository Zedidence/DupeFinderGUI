"""
Database connection management with thread safety.

Provides ConnectionManager for thread-safe SQLite operations with WAL mode.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class ConnectionManager:
    """
    Manages SQLite connections with thread-safety.

    Provides context manager for database connections with:
    - Thread-safe write operations via lock
    - WAL mode for better read/write concurrency
    - Transaction management (BEGIN/COMMIT/ROLLBACK)
    """

    def __init__(self, db_path: str):
        """
        Initialize connection manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._ensure_directory()

    def _ensure_directory(self):
        """Ensure the directory for the database file exists."""
        db_path = Path(self.db_path).resolve()
        db_dir = db_path.parent

        # Only create directory if it doesn't exist and has a parent path
        if db_dir and db_dir != db_path:
            db_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self, exclusive: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Args:
            exclusive: If True, acquire write lock for thread safety

        Yields:
            sqlite3.Connection with row factory and WAL mode enabled

        Example:
            with conn_mgr.connection(exclusive=True) as conn:
                conn.execute("INSERT INTO ...")
        """
        if exclusive:
            self._write_lock.acquire()

        try:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                # Enable WAL mode for better concurrency
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row

            # Enable WAL mode for better read/write concurrency
            conn.execute("PRAGMA journal_mode=WAL")

            # Begin transaction
            conn.execute("BEGIN")

            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        finally:
            if exclusive:
                self._write_lock.release()


__all__ = ['ConnectionManager']
