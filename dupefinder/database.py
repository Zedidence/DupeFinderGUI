"""
SQLite database backend for Duplicate Image Finder.

Provides persistent caching of image analysis results to enable:
- Incremental re-scans (only analyze new/changed files)
- Reduced memory usage for large collections
- Faster subsequent scans of the same directories

The cache uses file path + mtime + size as a cache key to detect changes.
"""

import sqlite3
import os
import time
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator
from dataclasses import dataclass

from .config import CACHE_DB_FILE
from .models import ImageInfo

logger = logging.getLogger(__name__)


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


class ImageCache:
    """
    SQLite-backed cache for image analysis results.
    
    FIXED #7: Now thread-safe for concurrent read/write operations.
    
    Usage:
        cache = ImageCache()
        
        # Check if image is cached
        info = cache.get(filepath)
        if info is None:
            info = analyze_image(filepath)
            cache.put(info)
        
        # Or use the helper
        info = cache.get_or_analyze(filepath, analyze_func)
    """
    
    # Schema version - increment when changing table structure
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the image cache.
        
        Args:
            db_path: Path to SQLite database file. Uses default if None.
        """
        self.db_path = db_path or CACHE_DB_FILE
        self._ensure_directory()
        
        # FIXED #7: Thread lock for write operations
        self._write_lock = threading.Lock()
        
        self._init_db()
    
    def _ensure_directory(self):
        """Ensure the directory for the database file exists."""
        # Use Path for more robust cross-platform handling
        db_path = Path(self.db_path).resolve()
        db_dir = db_path.parent

        # Only create directory if it doesn't exist and has a parent path
        if db_dir and db_dir != db_path:
            db_dir.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def _conn(self, exclusive: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.
        
        Args:
            exclusive: If True, acquire write lock for thread safety
        """
        # FIXED #7: Acquire lock for exclusive (write) operations
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
    
    def _init_db(self):
        """Initialize database schema."""
        with self._conn(exclusive=True) as conn:
            # Check schema version
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            result = conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            
            current_version = int(result['value']) if result else 0
            
            if current_version < self.SCHEMA_VERSION:
                # Drop and recreate tables if schema changed
                conn.execute("DROP TABLE IF EXISTS images")
                conn.execute("DROP TABLE IF EXISTS scan_history")
            
            # Main images table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    cache_key TEXT UNIQUE NOT NULL,
                    
                    -- Image metadata
                    width INTEGER,
                    height INTEGER,
                    pixel_count INTEGER,
                    bit_depth INTEGER,
                    format TEXT,
                    
                    -- Hashes
                    file_hash TEXT,
                    perceptual_hash TEXT,
                    
                    -- Computed
                    quality_score REAL,
                    error TEXT,
                    
                    -- Timestamps
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    last_accessed REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_images_cache_key 
                ON images(cache_key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_images_path 
                ON images(path)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_images_file_hash 
                ON images(file_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_images_phash_prefix 
                ON images(substr(perceptual_hash, 1, 8))
            """)
            
            # Scan history for tracking directories
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    directory TEXT NOT NULL,
                    file_count INTEGER,
                    scan_time REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Update schema version
            conn.execute("""
                INSERT OR REPLACE INTO meta (key, value) 
                VALUES ('schema_version', ?)
            """, (str(self.SCHEMA_VERSION),))
    
    @staticmethod
    def _make_cache_key(filepath: str, mtime: float, size: int) -> str:
        """
        Create a cache key from file attributes.
        
        The key changes if the file is modified or its size changes.
        """
        return f"{filepath}:{mtime}:{size}"
    
    @staticmethod
    def _get_file_stats(filepath: str) -> tuple[float, int]:
        """Get file mtime and size."""
        stat = os.stat(filepath)
        return stat.st_mtime, stat.st_size
    
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
            
            mtime, size = self._get_file_stats(filepath)
            cache_key = self._make_cache_key(filepath, mtime, size)
            
            # Read operations don't need exclusive lock
            with self._conn(exclusive=False) as conn:
                row = conn.execute("""
                    SELECT * FROM images WHERE cache_key = ?
                """, (cache_key,)).fetchone()
                
                if row:
                    # Update last accessed time (write operation)
                    # This is a minor race condition but acceptable for access time
                    conn.execute("""
                        UPDATE images SET last_accessed = strftime('%s', 'now')
                        WHERE cache_key = ?
                    """, (cache_key,))
                    
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
            
            mtime, size = self._get_file_stats(info.path)
            cache_key = self._make_cache_key(info.path, mtime, size)
            
            # FIXED #7: Write operations use exclusive lock
            with self._conn(exclusive=True) as conn:
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
    
    def put_batch(self, images: list[ImageInfo]) -> int:
        """
        Cache multiple ImageInfo objects efficiently.
        
        FIXED #7: Now thread-safe with exclusive lock for entire batch.
        
        Args:
            images: List of ImageInfo objects
            
        Returns:
            Number of successfully cached images
        """
        cached = 0
        
        try:
            # FIXED #7: Single exclusive lock for entire batch operation
            with self._conn(exclusive=True) as conn:
                for info in images:
                    try:
                        if not os.path.exists(info.path):
                            continue
                        
                        mtime, size = self._get_file_stats(info.path)
                        cache_key = self._make_cache_key(info.path, mtime, size)
                        
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
    
    def get_batch(self, filepaths: list[str]) -> dict[str, Optional[ImageInfo]]:
        """
        Get cached info for multiple files efficiently.

        Args:
            filepaths: List of file paths

        Returns:
            Dict mapping filepath to ImageInfo (or None if not cached)
        """
        results: dict[str, Optional[ImageInfo]] = {fp: None for fp in filepaths}

        # SQLite has a limit on SQL variables (typically 999)
        # Chunk queries to stay well under the limit
        CHUNK_SIZE = 500

        try:
            # Build cache keys for files that exist
            cache_keys = {}
            for fp in filepaths:
                try:
                    if os.path.exists(fp):
                        mtime, size = self._get_file_stats(fp)
                        cache_keys[self._make_cache_key(fp, mtime, size)] = fp
                except Exception:
                    continue

            if not cache_keys:
                return results

            # Process in chunks to avoid SQLite variable limit
            cache_key_list = list(cache_keys.keys())
            all_hit_keys = []

            with self._conn(exclusive=False) as conn:
                for i in range(0, len(cache_key_list), CHUNK_SIZE):
                    chunk = cache_key_list[i:i + CHUNK_SIZE]
                    placeholders = ','.join('?' * len(chunk))

                    rows = conn.execute(f"""
                        SELECT * FROM images WHERE cache_key IN ({placeholders})
                    """, chunk).fetchall()

                    for row in rows:
                        filepath = cache_keys.get(row['cache_key'])
                        if filepath is not None:
                            results[filepath] = ImageInfo(
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
    
    def invalidate(self, filepath: str):
        """Remove a specific file from the cache."""
        try:
            with self._conn(exclusive=True) as conn:
                conn.execute("DELETE FROM images WHERE path = ?", (filepath,))
        except Exception as e:
            logger.debug(f"Failed to invalidate cache for {filepath}: {e}")
    
    def invalidate_directory(self, directory: str):
        """Remove all cached entries for files in a directory."""
        try:
            with self._conn(exclusive=True) as conn:
                conn.execute(
                    "DELETE FROM images WHERE path LIKE ?",
                    (f"{directory}%",)
                )
        except Exception as e:
            logger.debug(f"Failed to invalidate cache for directory {directory}: {e}")
    
    def cleanup_stale(self, max_age_days: int = 30):
        """
        Remove cache entries that haven't been accessed recently.

        Args:
            max_age_days: Remove entries not accessed in this many days
        """
        try:
            cutoff = time.time() - (max_age_days * 24 * 60 * 60)
            with self._conn(exclusive=True) as conn:
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
        # SQLite has a limit on SQL variables (typically 999)
        CHUNK_SIZE = 500

        try:
            with self._conn(exclusive=True) as conn:
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
        """Get cache statistics."""
        try:
            with self._conn(exclusive=False) as conn:
                total = conn.execute("SELECT COUNT(*) as cnt FROM images").fetchone()['cnt']

                # Size on disk
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

                return {
                    'total_entries': total,
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2),
                    'db_path': self.db_path,
                }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {
                'total_entries': 0,
                'db_size_bytes': 0,
                'db_size_mb': 0,
                'db_path': self.db_path,
            }
    
    def clear(self):
        """Clear all cached data."""
        try:
            with self._conn(exclusive=True) as conn:
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
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("VACUUM")
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to vacuum database: {e}")


# Global cache instance
_cache_instance: Optional[ImageCache] = None
_cache_lock = threading.Lock()


def get_cache() -> ImageCache:
    """Get or create the global cache instance (thread-safe)."""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            # Double-check after acquiring lock
            if _cache_instance is None:
                _cache_instance = ImageCache()
    return _cache_instance


def reset_cache():
    """Reset the global cache instance (mainly for testing)."""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None