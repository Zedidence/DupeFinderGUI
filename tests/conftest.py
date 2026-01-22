"""
Pytest configuration and shared fixtures for test suite.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from PIL import Image
import os


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_images(temp_dir):
    """
    Create a set of sample images for testing.

    Returns:
        dict with paths to:
        - identical1.png, identical2.png (exact duplicates)
        - similar1.png, similar2.png (perceptual duplicates - same but different quality)
        - unique.png (unique image)
        - corrupted.txt (not an image)
    """
    images = {}

    # Create identical images (100x100 red square)
    img1 = Image.new('RGB', (100, 100), color='red')
    path1 = temp_dir / "identical1.png"
    img1.save(path1, 'PNG')
    images['identical1'] = str(path1)

    # Exact copy
    path2 = temp_dir / "identical2.png"
    img1.save(path2, 'PNG')
    images['identical2'] = str(path2)

    # Similar image - same content, different compression
    img2 = Image.new('RGB', (100, 100), color='red')
    path3 = temp_dir / "similar1.png"
    img2.save(path3, 'PNG', optimize=False)
    images['similar1'] = str(path3)

    path4 = temp_dir / "similar2.png"
    img2.save(path4, 'PNG', optimize=True, compress_level=9)
    images['similar2'] = str(path4)

    # Unique image (100x100 blue square)
    img3 = Image.new('RGB', (100, 100), color='blue')
    path5 = temp_dir / "unique.png"
    img3.save(path5, 'PNG')
    images['unique'] = str(path5)

    # Corrupted file
    path6 = temp_dir / "corrupted.txt"
    path6.write_text("not an image")
    images['corrupted'] = str(path6)

    # Higher resolution version of red square (perceptually similar)
    img4 = Image.new('RGB', (200, 200), color='red')
    path7 = temp_dir / "red_large.png"
    img4.save(path7, 'PNG')
    images['red_large'] = str(path7)

    return images


@pytest.fixture
def temp_cache_db(temp_dir):
    """Create a temporary database file for cache tests."""
    db_path = temp_dir / "test_cache.db"
    return str(db_path)


@pytest.fixture
def mock_image_info():
    """Create a mock ImageInfo object for testing."""
    from dupefinder.models import ImageInfo

    return ImageInfo(
        path="/test/image.jpg",
        file_size=1024000,
        width=1920,
        height=1080,
        pixel_count=1920*1080,
        bit_depth=24,
        format="JPEG",
        file_hash="abc123",
        perceptual_hash="0123456789abcdef",
        quality_score=75.5
    )
