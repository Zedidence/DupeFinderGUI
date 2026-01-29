"""
Selection strategy utilities for the Duplicate Image Finder.

Provides automatic selection strategies to determine which images to keep
vs delete when duplicates are found.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from ..models import DuplicateGroup


class SelectionStrategy(str, Enum):
    """
    Strategy for selecting which duplicate images to keep.

    Attributes:
        QUALITY: Keep the highest quality image (best resolution, format, etc.)
        LARGEST: Keep the largest file size
        SMALLEST: Keep the smallest file size
        NEWEST: Keep the most recently modified file
        OLDEST: Keep the oldest file
    """
    QUALITY = 'quality'
    LARGEST = 'largest'
    SMALLEST = 'smallest'
    NEWEST = 'newest'
    OLDEST = 'oldest'


def _get_mtime(img: Any) -> float:
    """
    Get modification time of an image file.

    Args:
        img: ImageInfo object

    Returns:
        Modification time as float timestamp, or 0 on error
    """
    try:
        return os.path.getmtime(img.path)
    except OSError:
        return 0.0


def _get_mtime_reverse(img: Any) -> float:
    """
    Get modification time (for reverse sorting - oldest first).

    Args:
        img: ImageInfo object

    Returns:
        Modification time as float timestamp, or infinity on error
    """
    try:
        return os.path.getmtime(img.path)
    except OSError:
        return float('inf')


def apply_selection_strategy(groups: list[DuplicateGroup], strategy: str) -> dict[str, str]:
    """
    Apply auto-selection strategy to determine which images to keep/delete.

    Args:
        groups: List of duplicate groups
        strategy: One of 'quality', 'largest', 'smallest', 'newest', 'oldest'

    Returns:
        Dict mapping image path to 'keep' or 'delete'

    Examples:
        >>> groups = [DuplicateGroup(...)]
        >>> selections = apply_selection_strategy(groups, 'quality')
        >>> selections['/path/to/image.jpg']
        'keep'

    Raises:
        ValueError: If strategy is not recognized
    """
    # Validate strategy
    try:
        strategy_enum = SelectionStrategy(strategy)
    except ValueError:
        # Fallback to quality for unknown strategies
        strategy_enum = SelectionStrategy.QUALITY

    selections = {}

    for group in groups:
        if not group.images:
            continue

        # Sort images based on strategy
        if strategy_enum == SelectionStrategy.QUALITY:
            # Default: highest quality score
            sorted_images = sorted(group.images, key=lambda x: -x.quality_score)

        elif strategy_enum == SelectionStrategy.LARGEST:
            sorted_images = sorted(group.images, key=lambda x: -x.file_size)

        elif strategy_enum == SelectionStrategy.SMALLEST:
            sorted_images = sorted(group.images, key=lambda x: x.file_size)

        elif strategy_enum == SelectionStrategy.NEWEST:
            # Sort by mtime (newest first)
            sorted_images = sorted(group.images, key=lambda x: -_get_mtime(x))

        elif strategy_enum == SelectionStrategy.OLDEST:
            # Sort by mtime (oldest first)
            sorted_images = sorted(group.images, key=_get_mtime_reverse)

        else:
            # Fallback to quality
            sorted_images = sorted(group.images, key=lambda x: -x.quality_score)

        # First image is kept, rest are deleted
        for idx, img in enumerate(sorted_images):
            selections[img.path] = 'keep' if idx == 0 else 'delete'

    return selections


__all__ = ['SelectionStrategy', 'apply_selection_strategy']
