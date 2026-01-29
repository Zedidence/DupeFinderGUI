"""
Scanner package for the Duplicate Image Finder.

Provides comprehensive image scanning, analysis, and duplicate detection
functionality with support for exact and perceptual matching.

Public API:
- find_image_files: Discover image files in directories
- calculate_file_hash: Calculate SHA-256 hash of files
- calculate_perceptual_hash: Calculate perceptual (pHash) of images
- calculate_quality_score: Score image quality based on multiple factors
- analyze_image: Analyze single image and extract metadata
- analyze_images_parallel: Analyze multiple images in parallel with caching
- find_exact_duplicates: Find exact duplicates by file hash
- find_perceptual_duplicates: Find perceptually similar images
- has_heif_support: Check if HEIC/HEIF support is available
"""

from __future__ import annotations

# Import public functions from submodules
from .file_discovery import find_image_files
from .hashing import (
    calculate_file_hash,
    calculate_perceptual_hash,
    calculate_quality_score,
)
from .analysis import analyze_image
from .parallel import analyze_images_parallel
from .deduplication import (
    find_exact_duplicates,
    find_perceptual_duplicates,
)

# Import dependencies for has_heif_support function
from .dependencies import HAS_HEIF_SUPPORT


def has_heif_support() -> bool:
    """Check if HEIC/HEIF support is available."""
    return HAS_HEIF_SUPPORT


# Public API exports
__all__ = [
    # File discovery
    'find_image_files',
    # Hashing functions
    'calculate_file_hash',
    'calculate_perceptual_hash',
    'calculate_quality_score',
    # Image analysis
    'analyze_image',
    'analyze_images_parallel',
    # Duplicate detection
    'find_exact_duplicates',
    'find_perceptual_duplicates',
    # Feature detection
    'has_heif_support',
]
