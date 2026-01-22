"""
Unit tests for data models (ImageInfo and DuplicateGroup).
"""

import pytest
from dupefinder.models import ImageInfo, DuplicateGroup, format_size


class TestFormatSize:
    """Test the format_size utility function."""

    def test_bytes(self):
        assert format_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_size(5242880) == "5.0 MB"

    def test_gigabytes(self):
        assert format_size(3221225472) == "3.0 GB"

    def test_zero(self):
        assert format_size(0) == "0.0 B"


class TestImageInfo:
    """Test ImageInfo data class."""

    def test_creation(self):
        info = ImageInfo(
            path="/test/image.jpg",
            file_size=1024,
            width=800,
            height=600
        )
        assert info.path == "/test/image.jpg"
        assert info.file_size == 1024
        assert info.width == 800
        assert info.height == 600

    def test_filename_property(self):
        info = ImageInfo(path="/path/to/image.jpg")
        assert info.filename == "image.jpg"

    def test_directory_property(self):
        info = ImageInfo(path="/path/to/image.jpg")
        assert info.directory == "/path/to"

    def test_resolution_property(self):
        info = ImageInfo(path="/test.jpg", width=1920, height=1080)
        assert info.resolution == "1920x1080"

    def test_megapixels_property(self):
        info = ImageInfo(path="/test.jpg", pixel_count=2073600)
        assert info.megapixels == 2.07

    def test_file_size_formatted(self):
        info = ImageInfo(path="/test.jpg", file_size=1048576)
        assert info.file_size_formatted == "1.0 MB"

    def test_to_dict(self):
        info = ImageInfo(
            path="/test/image.jpg",
            file_size=1024,
            width=800,
            height=600,
            format="JPEG",
            quality_score=75.5
        )
        data = info.to_dict()
        assert data['path'] == "/test/image.jpg"
        assert data['filename'] == "image.jpg"
        assert data['file_size'] == 1024
        assert data['width'] == 800
        assert data['height'] == 600
        assert data['format'] == "JPEG"
        assert data['quality_score'] == 75.5

    def test_from_dict(self):
        data = {
            'path': '/test/image.jpg',
            'file_size': 1024,
            'width': 800,
            'height': 600,
            'format': 'JPEG',
            'quality_score': 75.5
        }
        info = ImageInfo.from_dict(data)
        assert info.path == "/test/image.jpg"
        assert info.file_size == 1024
        assert info.width == 800

    def test_hash_and_equality(self):
        info1 = ImageInfo(path="/test/image.jpg")
        info2 = ImageInfo(path="/test/image.jpg")
        info3 = ImageInfo(path="/test/other.jpg")

        assert info1 == info2
        assert info1 != info3
        assert hash(info1) == hash(info2)


class TestDuplicateGroup:
    """Test DuplicateGroup data class."""

    def test_creation(self):
        group = DuplicateGroup(id=1, match_type="exact")
        assert group.id == 1
        assert group.match_type == "exact"
        assert len(group.images) == 0

    def test_best_image(self):
        img1 = ImageInfo(path="/img1.jpg", quality_score=50.0)
        img2 = ImageInfo(path="/img2.jpg", quality_score=75.0)
        img3 = ImageInfo(path="/img3.jpg", quality_score=60.0)

        group = DuplicateGroup(id=1, images=[img1, img2, img3])
        assert group.best_image == img2  # Highest quality score

    def test_best_image_empty_group(self):
        group = DuplicateGroup(id=1)
        assert group.best_image is None

    def test_duplicates(self):
        img1 = ImageInfo(path="/img1.jpg", quality_score=50.0)
        img2 = ImageInfo(path="/img2.jpg", quality_score=75.0)
        img3 = ImageInfo(path="/img3.jpg", quality_score=60.0)

        group = DuplicateGroup(id=1, images=[img1, img2, img3])
        dupes = group.duplicates

        assert len(dupes) == 2
        assert img2 not in dupes  # Best image excluded
        assert img1 in dupes
        assert img3 in dupes

    def test_image_count(self):
        img1 = ImageInfo(path="/img1.jpg")
        img2 = ImageInfo(path="/img2.jpg")

        group = DuplicateGroup(id=1, images=[img1, img2])
        assert group.image_count == 2

    def test_potential_savings(self):
        img1 = ImageInfo(path="/img1.jpg", quality_score=50.0, file_size=1000)
        img2 = ImageInfo(path="/img2.jpg", quality_score=75.0, file_size=2000)
        img3 = ImageInfo(path="/img3.jpg", quality_score=60.0, file_size=1500)

        group = DuplicateGroup(id=1, images=[img1, img2, img3])
        # Best is img2 (2000), duplicates are img1 (1000) + img3 (1500) = 2500
        assert group.potential_savings == 2500

    def test_potential_savings_formatted(self):
        img1 = ImageInfo(path="/img1.jpg", quality_score=50.0, file_size=1048576)
        img2 = ImageInfo(path="/img2.jpg", quality_score=75.0, file_size=2097152)

        group = DuplicateGroup(id=1, images=[img1, img2])
        assert "MB" in group.potential_savings_formatted

    def test_to_dict(self):
        img1 = ImageInfo(path="/img1.jpg", quality_score=50.0)
        img2 = ImageInfo(path="/img2.jpg", quality_score=75.0)

        group = DuplicateGroup(id=1, images=[img1, img2], match_type="exact")
        data = group.to_dict()

        assert data['id'] == 1
        assert data['match_type'] == "exact"
        assert data['image_count'] == 2
        assert len(data['images']) == 2

    def test_from_dict(self):
        data = {
            'id': 1,
            'match_type': 'perceptual',
            'images': [
                {'path': '/img1.jpg', 'quality_score': 50.0},
                {'path': '/img2.jpg', 'quality_score': 75.0}
            ]
        }
        group = DuplicateGroup.from_dict(data)
        assert group.id == 1
        assert group.match_type == "perceptual"
        assert len(group.images) == 2
