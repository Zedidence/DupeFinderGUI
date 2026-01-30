"""
Core CRUD operations for the image cache.

Provides CacheOperations class for single and batch operations.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from ..models import ImageInfo
from .connection import ConnectionManager
from .utils import make_cache_key, get_file_stats, row_to_imageinfo, CHUNK_SIZE


logger = logging.getLogger(__name__)


class CacheOperations:
    """
    Handles CRUD operations for the image cache.

    Provides single and batch operations for retrieving, storing, and
    invalidating cached image analysis results.
    """

    def __init__(self, connection_manager: ConnectionManager):
        """
        Initialize cache operations.

        Args:
            connection_manager: ConnectionManager instance for database access
        """
        self.conn_mgr = connection_manager

    def get(self, filepath: str) -> Optional[ImageInfo]:
        """
        Get cached image info if available and still valid.

        Args:
            filepath: Path to the image file

        Returns:
            ImageInfo if cached and valid, None otherwise
        """
        try:
            if not os.path.exists(filepath):
                return None

            mtime, size = get_file_stats(filepath)
            cache_key = make_cache_key(filepath, mtime, size)

            # Read operations don't need exclusive lock
            with self.conn_mgr.connection(exclusive=False) as conn:
                row = conn.execute("""
                    SELECT * FROM images WHERE cache_key = ?
                """, (cache_key,)).fetchone()

                if row:
                    # Update last accessed time (write operation)
                    conn.execute("""
                        UPDATE images SET last_accessed = strftime('%s', 'now')
                        WHERE cache_key = ?
                    """, (cache_key,))

                    return row_to_imageinfo(row)

            return None

        except Exception as e:
            logger.debug(f"Failed to get cached info for {filepath}: {e}")
            return None

    def put(self, info: ImageInfo) -> bool:
        """
        Cache an ImageInfo object.

        Args:
            info: ImageInfo to cache

        Returns:
            True if successfully cached
        """
        try:
            if not os.path.exists(info.path):
                return False

            mtime, size = get_file_stats(info.path)
            cache_key = make_cache_key(info.path, mtime, size)

            # Write operations use exclusive lock
            with self.conn_mgr.connection(exclusive=True) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO images (
                        path, file_size, mtime, cache_key,
                        width, height, pixel_count, bit_depth, format,
                        file_hash, perceptual_hash, quality_score, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    info.path, info.file_size, mtime, cache_key,
                    info.width, info.height, info.pixel_count,
                    info.bit_depth, info.format,
                    info.file_hash, info.perceptual_hash,
                    info.quality_score, info.error
                ))

            return True

        except Exception as e:
            logger.debug(f"Failed to cache image info for {info.path}: {e}")
            return False

    def get_batch(self, filepaths: list[str]) -> dict[str, Optional[ImageInfo]]:
        """
        Get cached info for multiple files efficiently.

        Args:
            filepaths: List of file paths

        Returns:
            Dict mapping filepath to ImageInfo (or None if not cached)
        """
        results: dict[str, Optional[ImageInfo]] = {fp: None for fp in filepaths}

        try:
            # Build cache keys for files that exist
            cache_keys = {}
            for fp in filepaths:
                try:
                    if os.path.exists(fp):
                        mtime, size = get_file_stats(fp)
                        cache_keys[make_cache_key(fp, mtime, size)] = fp
                except Exception:
                    continue

            if not cache_keys:
                return results

            # Process in chunks to avoid SQLite variable limit
            cache_key_list = list(cache_keys.keys())
            all_hit_keys = []

            with self.conn_mgr.connection(exclusive=False) as conn:
                for i in range(0, len(cache_key_list), CHUNK_SIZE):
                    chunk = cache_key_list[i:i + CHUNK_SIZE]
                    placeholders = ','.join('?' * len(chunk))

                    rows = conn.execute(f"""
                        SELECT * FROM images WHERE cache_key IN ({placeholders})
                    """, chunk).fetchall()

                    for row in rows:
                        filepath = cache_keys.get(row['cache_key'])
                        if filepath is not None:
                            results[filepath] = row_to_imageinfo(row)
                            all_hit_keys.append(row['cache_key'])

                # Update last accessed for cache hits (also in chunks)
                for i in range(0, len(all_hit_keys), CHUNK_SIZE):
                    chunk = all_hit_keys[i:i + CHUNK_SIZE]
                    placeholders = ','.join('?' * len(chunk))
                    conn.execute(f"""
                        UPDATE images SET last_accessed = strftime('%s', 'now')
                        WHERE cache_key IN ({placeholders})
                    """, chunk)

        except Exception as e:
            logger.warning(f"Error during batch retrieval: {e}")

        return results

    def put_batch(self, images: list[ImageInfo]) -> int:
        """
        Cache multiple ImageInfo objects efficiently.

        Args:
            images: List of ImageInfo objects

        Returns:
            Number of successfully cached images
        """
        cached = 0

        try:
            # Single exclusive lock for entire batch operation
            with self.conn_mgr.connection(exclusive=True) as conn:
                for info in images:
                    try:
                        if not os.path.exists(info.path):
                            continue

                        mtime, size = get_file_stats(info.path)
                        cache_key = make_cache_key(info.path, mtime, size)

                        conn.execute("""
                            INSERT OR REPLACE INTO images (
                                path, file_size, mtime, cache_key,
                                width, height, pixel_count, bit_depth, format,
                                file_hash, perceptual_hash, quality_score, error
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            info.path, info.file_size, mtime, cache_key,
                            info.width, info.height, info.pixel_count,
                            info.bit_depth, info.format,
                            info.file_hash, info.perceptual_hash,
                            info.quality_score, info.error
                        ))
                        cached += 1

                    except Exception:
                        continue

        except Exception as e:
            logger.warning(f"Error during batch caching: {e}")

        return cached

    def invalidate(self, filepath: str):
        """
        Remove a specific file from the cache.

        Args:
            filepath: Path to the file to invalidate
        """
        try:
            with self.conn_mgr.connection(exclusive=True) as conn:
                conn.execute("DELETE FROM images WHERE path = ?", (filepath,))
        except Exception as e:
            logger.debug(f"Failed to invalidate cache for {filepath}: {e}")

    def invalidate_directory(self, directory: str):
        """
        Remove all cached entries for files in a directory.

        Args:
            directory: Directory path
        """
        try:
            with self.conn_mgr.connection(exclusive=True) as conn:
                conn.execute(
                    "DELETE FROM images WHERE path LIKE ?",
                    (f"{directory}%",)
                )
        except Exception as e:
            logger.debug(f"Failed to invalidate cache for directory {directory}: {e}")


__all__ = ['CacheOperations']
