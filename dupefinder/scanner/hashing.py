"""
Hashing module for the scanner package.

Provides functions for calculating cryptographic hashes, perceptual hashes,
and quality scores for images.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from ..config import FORMAT_QUALITY_RANK
from ..models import ImageInfo
from .dependencies import Image, imagehash, _logger


def calculate_file_hash(filepath: str | Path, algorithm: str = 'sha256') -> str:
    """
    Calculate cryptographic hash of a file.

    Args:
        filepath: Path to the file
        algorithm: Hash algorithm to use (default: sha256)

    Returns:
        Hex digest of the file hash, or empty string on error
    """
    hasher = hashlib.new(algorithm)
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        _logger.debug(f"File hash calculation failed for {filepath}: {e}")
        return ""


def calculate_perceptual_hash(filepath: str | Path, hash_size: int = 16) -> Optional[str]:
    """
    Calculate perceptual hash of an image.

    Uses pHash algorithm which is most accurate for photos.

    Args:
        filepath: Path to the image
        hash_size: Size of the hash (default 16, resulting in 256-bit hash)

    Returns:
        String representation of the perceptual hash, or None on error
    """
    try:
        with Image.open(filepath) as img:
            # FIXED #6: Verify image can be loaded before accessing attributes
            img.load()  # Force load to detect truncated/corrupt images early

            # Convert to RGB if necessary (handles transparency, etc.)
            if img.mode not in ('RGB', 'L'):
                try:
                    img = img.convert('RGB')
                except Exception as conv_err:
                    # FIXED #4: Log conversion failures instead of silent None
                    _logger.debug(f"Image mode conversion failed for {filepath} (mode={img.mode}): {conv_err}")
                    return None

            phash = imagehash.phash(img, hash_size=hash_size)
            return str(phash)
    except Exception as e:
        # FIXED #4: Log perceptual hash failures instead of silently returning None
        _logger.debug(f"Perceptual hash calculation failed for {filepath}: {e}")
        return None


def calculate_quality_score(info: ImageInfo) -> float:
    """
    Calculate a quality score for an image.
    Higher score = better quality.

    Factors considered:
    - Resolution (pixel count) - up to 50 points
    - File size (larger often means more detail) - up to 30 points
    - Bit depth - up to 10 points
    - Format quality ranking - up to 20 points

    Args:
        info: ImageInfo object with metadata

    Returns:
        Quality score (typically 0-110 range)
    """
    score = 0.0

    # Resolution score (normalized, max ~50 points for 50MP+)
    if info.pixel_count > 0:
        # Log scale to prevent huge images from dominating
        resolution_score = min(50, (info.pixel_count / 1_000_000) * 2)
        score += resolution_score

    # File size score (normalized, max ~30 points)
    if info.file_size > 0:
        size_mb = info.file_size / (1024 * 1024)
        size_score = min(30, size_mb * 3)
        score += size_score

    # Bit depth score (max 10 points)
    if info.bit_depth > 0:
        depth_score = min(10, info.bit_depth / 3.2)
        score += depth_score

    # Format quality score (max 20 points)
    ext = os.path.splitext(info.path)[1].lower()
    format_rank = FORMAT_QUALITY_RANK.get(ext, 50)
    format_score = format_rank / 5  # Scale to 0-20
    score += format_score

    return score


__all__ = [
    'calculate_file_hash',
    'calculate_perceptual_hash',
    'calculate_quality_score',
]
