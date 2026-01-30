"""
SQLite database backend for Duplicate Image Finder.

Provides persistent caching of image analysis results to enable:
- Incremental re-scans (only analyze new/changed files)
- Reduced memory usage for large collections
- Faster subsequent scans of the same directories

The cache uses file path + mtime + size as a cache key to detect changes.

Public API:
- ImageCache: Main cache class
- CacheStats: Statistics dataclass
- get_cache(): Get global cache instance
- reset_cache(): Reset global instance (testing)
"""

from __future__ import annotations

import threading
from typing import Optional

from .core import ImageCache
from .utils import CacheStats


# Global cache instance (singleton pattern)
_cache_instance: Optional[ImageCache] = None
_cache_lock = threading.Lock()


def get_cache() -> ImageCache:
    """
    Get or create the global cache instance (thread-safe).

    Returns:
        Singleton ImageCache instance

    Example:
        cache = get_cache()
        info = cache.get(filepath)
    """
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            # Double-check after acquiring lock
            if _cache_instance is None:
                _cache_instance = ImageCache()
    return _cache_instance


def reset_cache():
    """
    Reset the global cache instance (mainly for testing).

    Example:
        reset_cache()  # Clear singleton for next test
    """
    global _cache_instance
    with _cache_lock:
        _cache_instance = None


__all__ = [
    'ImageCache',
    'CacheStats',
    'get_cache',
    'reset_cache',
]
