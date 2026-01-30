"""
Shared utilities for database operations.

Provides:
- CacheStats: Statistics dataclass for tracking cache performance
- Utility functions to eliminate code duplication
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from ..models import ImageInfo


# SQLite variable limit constant - used for batch operations
# SQLite has a limit of 999 variables, we use 500 for safety
CHUNK_SIZE = 500


@dataclass
class CacheStats:
    """Statistics about cache usage during a scan."""
    cache_hits: int = 0
    cache_misses: int = 0
    total_files: int = 0

    @property
    def hit_rate(self) -> float:
        """Return cache hit rate as percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.cache_hits / self.total_files) * 100


def make_cache_key(filepath: str, mtime: float, size: int) -> str:
    """
    Create a cache key from file attributes.

    The key changes if the file is modified or its size changes.

    Args:
        filepath: Path to the file
        mtime: File modification time (from os.stat)
        size: File size in bytes

    Returns:
        Cache key string
    """
    return f"{filepath}:{mtime}:{size}"


def get_file_stats(filepath: str) -> tuple[float, int]:
    """
    Get file mtime and size.

    Args:
        filepath: Path to the file

    Returns:
        Tuple of (mtime, size)
    """
    stat = os.stat(filepath)
    return stat.st_mtime, stat.st_size


def row_to_imageinfo(row: sqlite3.Row) -> ImageInfo:
    """
    Convert database row to ImageInfo object.

    Args:
        row: sqlite3.Row from database query

    Returns:
        ImageInfo object
    """
    return ImageInfo(
        path=row['path'],
        file_size=row['file_size'],
        width=row['width'] or 0,
        height=row['height'] or 0,
        pixel_count=row['pixel_count'] or 0,
        bit_depth=row['bit_depth'] or 0,
        format=row['format'] or "",
        file_hash=row['file_hash'] or "",
        perceptual_hash=row['perceptual_hash'] or "",
        quality_score=row['quality_score'] or 0.0,
        error=row['error'],
    )


__all__ = [
    'CHUNK_SIZE',
    'CacheStats',
    'make_cache_key',
    'get_file_stats',
    'row_to_imageinfo',
]
