"""
Unit tests for scanner module functions.
"""

import pytest
from pathlib import Path
from dupefinder.scanner import (
    find_image_files,
    calculate_file_hash,
    calculate_quality_score,
    analyze_image,
    find_exact_duplicates,
)
from dupefinder.models import ImageInfo


class TestFindImageFiles:
    """Test find_image_files function."""

    def test_find_png_files(self, sample_images, temp_dir):
        """Test finding PNG files in directory."""
        files = find_image_files(temp_dir, recursive=False)
        # Should find PNG files but not TXT
        assert len(files) >= 5  # All our sample PNGs
        assert all(f.endswith('.png') for f in files)

    def test_recursive_search(self, temp_dir):
        """Test recursive directory search."""
        # Create subdirectory with images
        subdir = temp_dir / "subdir"
        subdir.mkdir()

        from PIL import Image
        img = Image.new('RGB', (10, 10), color='green')
        img.save(subdir / "test.png")

        # Recursive should find both
        files = find_image_files(temp_dir, recursive=True)
        assert len(files) >= 1

        # Non-recursive should only find root level (if any)
        files_non_recursive = find_image_files(temp_dir, recursive=False)
        assert (subdir / "test.png").resolve() not in [Path(f) for f in files_non_recursive]

    def test_empty_directory(self, temp_dir):
        """Test scanning empty directory."""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()
        files = find_image_files(empty_dir)
        assert len(files) == 0


class TestCalculateFileHash:
    """Test calculate_file_hash function."""

    def test_identical_files_same_hash(self, sample_images):
        """Test that identical files have same hash."""
        hash1 = calculate_file_hash(sample_images['identical1'])
        hash2 = calculate_file_hash(sample_images['identical2'])
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_different_files_different_hash(self, sample_images):
        """Test that different files have different hashes."""
        hash1 = calculate_file_hash(sample_images['identical1'])
        hash2 = calculate_file_hash(sample_images['unique'])
        assert hash1 != hash2

    def test_nonexistent_file(self):
        """Test hash of nonexistent file returns empty string."""
        hash_val = calculate_file_hash("/nonexistent/file.jpg")
        assert hash_val == ""


class TestCalculateQualityScore:
    """Test calculate_quality_score function."""

    def test_higher_resolution_better_score(self):
        """Test that higher resolution gets better score."""
        img1 = ImageInfo(
            path="/test1.jpg",
            pixel_count=1920*1080,  # 2MP
            file_size=1000000,
            bit_depth=24,
            format="JPEG"
        )
        img2 = ImageInfo(
            path="/test2.jpg",
            pixel_count=3840*2160,  # 8MP
            file_size=1000000,
            bit_depth=24,
            format="JPEG"
        )

        score1 = calculate_quality_score(img1)
        score2 = calculate_quality_score(img2)
        assert score2 > score1

    def test_larger_file_better_score(self):
        """Test that larger file size contributes to score."""
        img1 = ImageInfo(
            path="/test1.jpg",
            pixel_count=1000000,
            file_size=500000,  # 500KB
            bit_depth=24,
            format="JPEG"
        )
        img2 = ImageInfo(
            path="/test2.jpg",
            pixel_count=1000000,
            file_size=2000000,  # 2MB
            bit_depth=24,
            format="JPEG"
        )

        score1 = calculate_quality_score(img1)
        score2 = calculate_quality_score(img2)
        assert score2 > score1

    def test_raw_format_better_than_jpeg(self):
        """Test that RAW format scores higher than JPEG."""
        img_jpeg = ImageInfo(path="/test.jpeg", pixel_count=1000000, file_size=1000000, bit_depth=24)
        img_raw = ImageInfo(path="/test.cr2", pixel_count=1000000, file_size=1000000, bit_depth=24)

        score_jpeg = calculate_quality_score(img_jpeg)
        score_raw = calculate_quality_score(img_raw)
        assert score_raw > score_jpeg


class TestAnalyzeImage:
    """Test analyze_image function."""

    def test_analyze_valid_image(self, sample_images):
        """Test analyzing a valid image file."""
        info = analyze_image(sample_images['unique'])

        assert info.path == sample_images['unique']
        assert info.width == 100
        assert info.height == 100
        assert info.pixel_count == 10000
        assert info.format == "PNG"
        assert info.file_hash != ""
        assert info.perceptual_hash != ""
        assert info.error is None

    def test_analyze_corrupted_file(self, sample_images):
        """Test analyzing corrupted/invalid file."""
        info = analyze_image(sample_images['corrupted'])

        assert info.path == sample_images['corrupted']
        assert info.error is not None  # Should have error message

    def test_analyze_nonexistent_file(self):
        """Test analyzing nonexistent file."""
        info = analyze_image("/nonexistent/image.jpg")
        assert info.error is not None


class TestFindExactDuplicates:
    """Test find_exact_duplicates function."""

    def test_find_exact_duplicates(self, sample_images):
        """Test finding exact duplicate files."""
        # Analyze the identical images
        img1 = analyze_image(sample_images['identical1'])
        img2 = analyze_image(sample_images['identical2'])
        img3 = analyze_image(sample_images['unique'])

        groups = find_exact_duplicates([img1, img2, img3])

        # Should find one group with 2 identical images
        assert len(groups) == 1
        assert groups[0].image_count == 2
        assert groups[0].match_type == "exact"

    def test_no_duplicates(self, sample_images):
        """Test when there are no duplicates."""
        img1 = analyze_image(sample_images['unique'])
        img2 = analyze_image(sample_images['red_large'])

        groups = find_exact_duplicates([img1, img2])
        assert len(groups) == 0

    def test_empty_list(self):
        """Test with empty image list."""
        groups = find_exact_duplicates([])
        assert len(groups) == 0

    def test_filters_errors(self, sample_images):
        """Test that images with errors are filtered out."""
        img1 = analyze_image(sample_images['identical1'])
        img2 = ImageInfo(path="/fake.jpg", error="Test error")

        groups = find_exact_duplicates([img1, img2])
        # Should not crash, img2 should be ignored
        assert len(groups) == 0
