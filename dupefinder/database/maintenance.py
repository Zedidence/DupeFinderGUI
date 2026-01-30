"""
Maintenance operations for the image cache.

Provides cleanup, statistics, and vacuum operations.
"""

from __future__ import annotations

import os
import time
import sqlite3
import logging

from .connection import ConnectionManager
from .utils import CHUNK_SIZE


logger = logging.getLogger(__name__)


class MaintenanceOperations:
    """
    Handles maintenance operations for the image cache.

    Provides cleanup, statistics reporting, and database compaction.
    """

    def __init__(self, connection_manager: ConnectionManager):
        """
        Initialize maintenance operations.

        Args:
            connection_manager: ConnectionManager instance for database access
        """
        self.conn_mgr = connection_manager

    def cleanup_stale(self, max_age_days: int = 30) -> int:
        """
        Remove cache entries that haven't been accessed recently.

        Args:
            max_age_days: Remove entries not accessed in this many days

        Returns:
            Number of entries removed
        """
        try:
            cutoff = time.time() - (max_age_days * 24 * 60 * 60)
            with self.conn_mgr.connection(exclusive=True) as conn:
                result = conn.execute(
                    "DELETE FROM images WHERE last_accessed < ?",
                    (cutoff,)
                )
                return result.rowcount
        except Exception as e:
            logger.warning(f"Failed to cleanup stale cache entries: {e}")
            return 0

    def cleanup_missing(self) -> int:
        """
        Remove cache entries for files that no longer exist.

        Returns:
            Number of entries removed
        """
        try:
            with self.conn_mgr.connection(exclusive=True) as conn:
                # Get all paths
                rows = conn.execute("SELECT path FROM images").fetchall()
                missing = [row['path'] for row in rows if not os.path.exists(row['path'])]

                # Delete in chunks to avoid SQLite variable limit
                for i in range(0, len(missing), CHUNK_SIZE):
                    chunk = missing[i:i + CHUNK_SIZE]
                    placeholders = ','.join('?' * len(chunk))
                    conn.execute(
                        f"DELETE FROM images WHERE path IN ({placeholders})",
                        chunk
                    )

                return len(missing)
        except Exception as e:
            logger.warning(f"Failed to cleanup missing cache entries: {e}")
            return 0

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics:
                - total_entries: Number of cached images
                - db_size_bytes: Database size in bytes
                - db_size_mb: Database size in MB
                - db_path: Path to database file
        """
        try:
            with self.conn_mgr.connection(exclusive=False) as conn:
                total = conn.execute("SELECT COUNT(*) as cnt FROM images").fetchone()['cnt']

                # Size on disk
                db_size = os.path.getsize(self.conn_mgr.db_path) if os.path.exists(self.conn_mgr.db_path) else 0

                return {
                    'total_entries': total,
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2),
                    'db_path': self.conn_mgr.db_path,
                }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {
                'total_entries': 0,
                'db_size_bytes': 0,
                'db_size_mb': 0,
                'db_path': self.conn_mgr.db_path,
            }

    def clear(self):
        """Clear all cached data."""
        try:
            with self.conn_mgr.connection(exclusive=True) as conn:
                conn.execute("DELETE FROM images")
                conn.execute("DELETE FROM scan_history")
            # VACUUM outside transaction
            self.vacuum()
        except Exception as e:
            logger.warning(f"Failed to clear cache: {e}")

    def vacuum(self):
        """Compact the database file."""
        try:
            # VACUUM must run outside a transaction
            conn = sqlite3.connect(self.conn_mgr.db_path, timeout=30.0)
            conn.execute("VACUUM")
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to vacuum database: {e}")


__all__ = ['MaintenanceOperations']
