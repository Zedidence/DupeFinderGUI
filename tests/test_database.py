"""
Unit tests for database/caching module.
"""

import pytest
import time
import os
from pathlib import Path
from dupefinder.database import ImageCache, CacheStats
from dupefinder.models import ImageInfo


class TestCacheStats:
    """Test CacheStats dataclass."""

    def test_hit_rate_calculation(self):
        """Test hit rate percentage calculation."""
        stats = CacheStats(cache_hits=75, cache_misses=25, total_files=100)
        assert stats.hit_rate == 75.0

    def test_hit_rate_no_files(self):
        """Test hit rate when no files."""
        stats = CacheStats(cache_hits=0, cache_misses=0, total_files=0)
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_misses(self):
        """Test hit rate with all cache misses."""
        stats = CacheStats(cache_hits=0, cache_misses=100, total_files=100)
        assert stats.hit_rate == 0.0


class TestImageCache:
    """Test ImageCache class."""

    def test_initialization(self, temp_cache_db):
        """Test cache initialization creates database."""
        cache = ImageCache(db_path=temp_cache_db)
        assert os.path.exists(temp_cache_db)

    def test_put_and_get(self, temp_cache_db, sample_images):
        """Test caching and retrieving an image."""
        cache = ImageCache(db_path=temp_cache_db)

        # Create ImageInfo for a real file
        img_path = sample_images['unique']
        original_info = ImageInfo(
            path=img_path,
            file_size=os.path.getsize(img_path),
            width=100,
            height=100,
            pixel_count=10000,
            format="PNG",
            file_hash="test_hash_123",
            perceptual_hash="abcdef123456",
            quality_score=75.5
        )

        # Cache it
        result = cache.put(original_info)
        assert result is True

        # Retrieve it
        cached_info = cache.get(img_path)
        assert cached_info is not None
        assert cached_info.path == original_info.path
        assert cached_info.file_hash == original_info.file_hash
        assert cached_info.perceptual_hash == original_info.perceptual_hash
        assert cached_info.quality_score == original_info.quality_score

    def test_get_nonexistent(self, temp_cache_db):
        """Test getting non-existent entry returns None."""
        cache = ImageCache(db_path=temp_cache_db)
        result = cache.get("/nonexistent/file.jpg")
        assert result is None

    def test_cache_invalidation_on_modification(self, temp_cache_db, temp_dir):
        """Test that cache is invalidated when file is modified."""
        cache = ImageCache(db_path=temp_cache_db)

        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("original")

        original_info = ImageInfo(
            path=str(test_file),
            file_size=os.path.getsize(test_file),
            file_hash="hash1"
        )

        cache.put(original_info)

        # Modify the file
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_text("modified content")

        # Should not return cached version (mtime changed)
        cached_info = cache.get(str(test_file))
        assert cached_info is None

    def test_put_batch(self, temp_cache_db, sample_images):
        """Test batch caching."""
        cache = ImageCache(db_path=temp_cache_db)

        images = [
            ImageInfo(path=sample_images['unique'], file_size=os.path.getsize(sample_images['unique']),
                     file_hash="hash1"),
            ImageInfo(path=sample_images['identical1'], file_size=os.path.getsize(sample_images['identical1']),
                     file_hash="hash2"),
        ]

        count = cache.put_batch(images)
        assert count == 2

    def test_get_batch(self, temp_cache_db, sample_images):
        """Test batch retrieval."""
        cache = ImageCache(db_path=temp_cache_db)

        # Cache some images
        images = [
            ImageInfo(path=sample_images['unique'], file_size=os.path.getsize(sample_images['unique']),
                     file_hash="hash1"),
            ImageInfo(path=sample_images['identical1'], file_size=os.path.getsize(sample_images['identical1']),
                     file_hash="hash2"),
        ]
        cache.put_batch(images)

        # Retrieve them
        paths = [sample_images['unique'], sample_images['identical1']]
        results = cache.get_batch(paths)

        assert results[sample_images['unique']] is not None
        assert results[sample_images['identical1']] is not None
        assert results[sample_images['unique']].file_hash == "hash1"

    def test_invalidate(self, temp_cache_db, sample_images):
        """Test invalidating a specific file."""
        cache = ImageCache(db_path=temp_cache_db)

        img_path = sample_images['unique']
        info = ImageInfo(path=img_path, file_size=os.path.getsize(img_path), file_hash="hash1")

        cache.put(info)
        assert cache.get(img_path) is not None

        cache.invalidate(img_path)
        # After re-caching with same data, should work again
        cache.put(info)
        cached = cache.get(img_path)
        assert cached is not None

    def test_cleanup_missing(self, temp_cache_db, temp_dir):
        """Test cleanup of entries for deleted files."""
        cache = ImageCache(db_path=temp_cache_db)

        # Create and cache a temporary file
        temp_file = temp_dir / "temp.txt"
        temp_file.write_text("test")

        info = ImageInfo(path=str(temp_file), file_size=os.path.getsize(temp_file))
        cache.put(info)

        # Delete the file
        temp_file.unlink()

        # Cleanup should remove the entry
        removed = cache.cleanup_missing()
        assert removed >= 1

    def test_get_stats(self, temp_cache_db, sample_images):
        """Test getting cache statistics."""
        cache = ImageCache(db_path=temp_cache_db)

        # Add some entries
        info = ImageInfo(path=sample_images['unique'], file_size=os.path.getsize(sample_images['unique']))
        cache.put(info)

        stats = cache.get_stats()
        assert 'total_entries' in stats
        assert 'db_size_mb' in stats
        assert 'db_path' in stats
        assert stats['total_entries'] >= 1

    def test_clear(self, temp_cache_db, sample_images):
        """Test clearing all cache data."""
        cache = ImageCache(db_path=temp_cache_db)

        # Add entries
        info = ImageInfo(path=sample_images['unique'], file_size=os.path.getsize(sample_images['unique']))
        cache.put(info)

        stats_before = cache.get_stats()
        assert stats_before['total_entries'] > 0

        # Clear
        cache.clear()

        stats_after = cache.get_stats()
        assert stats_after['total_entries'] == 0

    def test_put_nonexistent_file(self, temp_cache_db):
        """Test that putting info for nonexistent file fails gracefully."""
        cache = ImageCache(db_path=temp_cache_db)

        info = ImageInfo(path="/nonexistent/file.jpg", file_size=1000)
        result = cache.put(info)
        assert result is False
