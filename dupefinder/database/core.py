"""
ImageCache facade class for coordinating database operations.

Provides a unified interface to all cache operations using the facade pattern.
"""

from __future__ import annotations

from typing import Optional

from ..config import CACHE_DB_FILE
from ..models import ImageInfo
from .connection import ConnectionManager
from .schema import initialize_schema, SCHEMA_VERSION
from .operations import CacheOperations
from .maintenance import MaintenanceOperations


class ImageCache:
    """
    SQLite-backed cache for image analysis results.

    Thread-safe for concurrent read/write operations.
    Uses facade pattern to delegate to specialized components.

    Usage:
        cache = ImageCache()

        # Check if image is cached
        info = cache.get(filepath)
        if info is None:
            info = analyze_image(filepath)
            cache.put(info)
    """

    # Schema version - increment when changing table structure
    SCHEMA_VERSION = SCHEMA_VERSION

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the image cache.

        Args:
            db_path: Path to SQLite database file. Uses default if None.
        """
        self.db_path = db_path or CACHE_DB_FILE

        # Initialize components
        self._conn_mgr = ConnectionManager(self.db_path)
        self._operations = CacheOperations(self._conn_mgr)
        self._maintenance = MaintenanceOperations(self._conn_mgr)

        # Initialize database schema
        with self._conn_mgr.connection(exclusive=True) as conn:
            initialize_schema(conn)

    # Delegate to CacheOperations
    def get(self, filepath: str) -> Optional[ImageInfo]:
        """Get cached image info if available and still valid."""
        return self._operations.get(filepath)

    def put(self, info: ImageInfo) -> bool:
        """Cache an ImageInfo object."""
        return self._operations.put(info)

    def get_batch(self, filepaths: list[str]) -> dict[str, Optional[ImageInfo]]:
        """Get cached info for multiple files efficiently."""
        return self._operations.get_batch(filepaths)

    def put_batch(self, images: list[ImageInfo]) -> int:
        """Cache multiple ImageInfo objects efficiently."""
        return self._operations.put_batch(images)

    def invalidate(self, filepath: str):
        """Remove a specific file from the cache."""
        self._operations.invalidate(filepath)

    def invalidate_directory(self, directory: str):
        """Remove all cached entries for files in a directory."""
        self._operations.invalidate_directory(directory)

    # Delegate to MaintenanceOperations
    def cleanup_stale(self, max_age_days: int = 30) -> int:
        """Remove cache entries that haven't been accessed recently."""
        return self._maintenance.cleanup_stale(max_age_days)

    def cleanup_missing(self) -> int:
        """Remove cache entries for files that no longer exist."""
        return self._maintenance.cleanup_missing()

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return self._maintenance.get_stats()

    def clear(self):
        """Clear all cached data."""
        self._maintenance.clear()

    def vacuum(self):
        """Compact the database file."""
        self._maintenance.vacuum()

    # Backward compatibility - expose internal components if needed
    @property
    def _write_lock(self):
        """Access to write lock for backward compatibility."""
        return self._conn_mgr._write_lock

    def _conn(self, exclusive: bool = False):
        """Access to connection manager for backward compatibility."""
        return self._conn_mgr.connection(exclusive=exclusive)


__all__ = ['ImageCache']
