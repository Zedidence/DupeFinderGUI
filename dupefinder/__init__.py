"""
Duplicate Image Finder
======================
A comprehensive tool for finding duplicate and visually similar images.

Features:
- Multi-stage detection: exact hash + perceptual hash
- Supports ALL common image formats
- Quality-based selection (keeps highest quality)
- Configurable similarity threshold
- Web GUI for easy review
- CLI for automation
- SQLite cache for fast re-scans

Author: Zach
"""

__version__ = "1.1.0"
__author__ = "Zedidence"

from .models import ImageInfo, DuplicateGroup
from .config import IMAGE_EXTENSIONS, FORMAT_QUALITY_RANK
from .scanner import (
    analyze_image,
    analyze_images_parallel,
    find_image_files,
    calculate_file_hash,
    calculate_quality_score,
    find_exact_duplicates,
    find_perceptual_duplicates,
)
from .database import ImageCache, get_cache, CacheStats

__all__ = [
    "ImageInfo",
    "DuplicateGroup",
    "IMAGE_EXTENSIONS",
    "FORMAT_QUALITY_RANK",
    "analyze_image",
    "analyze_images_parallel",
    "find_image_files",
    "calculate_file_hash",
    "calculate_quality_score",
    "find_exact_duplicates",
    "find_perceptual_duplicates",
    "ImageCache",
    "get_cache",
    "CacheStats",
]