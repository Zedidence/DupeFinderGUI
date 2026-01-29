"""
Image analysis module for the scanner package.

Provides single-image analysis functionality with comprehensive error handling,
metadata extraction, and hash calculation.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import MODE_BIT_DEPTHS
from ..models import ImageInfo
from .dependencies import Image, imagehash, HAS_HEIF_SUPPORT, _logger
from .hashing import calculate_file_hash, calculate_quality_score


def analyze_image(
    filepath: str | Path,
    calculate_phash: bool = True,
    calculate_hash: bool = True,
) -> ImageInfo:
    """
    Analyze an image file and extract metadata.

    Args:
        filepath: Path to the image file
        calculate_phash: Whether to compute perceptual hash
        calculate_hash: Whether to compute file hash (SHA-256)

    Returns:
        ImageInfo object with all extracted metadata
    """
    filepath = str(filepath)
    info = ImageInfo(path=filepath)

    try:
        # File size - check file exists and is accessible first
        if not os.path.exists(filepath):
            info.error = "File not found"
            return info

        if not os.access(filepath, os.R_OK):
            info.error = "File not readable (permission denied)"
            return info

        info.file_size = os.path.getsize(filepath)

        # Calculate file hash (only if needed for exact duplicate detection)
        if calculate_hash:
            info.file_hash = calculate_file_hash(filepath)

        # Check for HEIC without support
        ext = os.path.splitext(filepath)[1].lower()
        if ext in {'.heic', '.heif'} and not HAS_HEIF_SUPPORT:
            info.error = "HEIC/HEIF support not installed (pip install pillow-heif)"
            return info

        # Open image and extract metadata
        # FIXED #6: Wrap in try-except to handle corrupt/truncated files
        try:
            with Image.open(filepath) as img:
                # Force load to detect truncated images early
                try:
                    img.load()
                except Exception as load_err:
                    info.error = f"Corrupt or truncated image: {load_err}"
                    return info

                # Now safe to access attributes
                info.width = img.width
                info.height = img.height
                info.pixel_count = img.width * img.height
                info.format = img.format or ""

                # Bit depth
                info.bit_depth = MODE_BIT_DEPTHS.get(img.mode, 24)

                # Perceptual hash
                if calculate_phash:
                    try:
                        if img.mode not in ('RGB', 'L'):
                            img = img.convert('RGB')
                        phash = imagehash.phash(img, hash_size=16)
                        info.perceptual_hash = str(phash)
                    except Exception as phash_err:
                        # FIXED #4: Log but don't fail the whole analysis
                        _logger.debug(f"Perceptual hash failed for {filepath}: {phash_err}")
                        info.perceptual_hash = ""

        except Image.UnidentifiedImageError as e:
            info.error = f"Not a valid image file: {e}"
            return info
        except Exception as e:
            info.error = f"Failed to open image: {e}"
            return info

        # Calculate quality score
        info.quality_score = calculate_quality_score(info)

    except Exception as e:
        info.error = str(e)

    return info


__all__ = ['analyze_image']
