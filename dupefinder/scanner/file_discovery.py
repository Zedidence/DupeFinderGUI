"""
File discovery module for the scanner package.

Provides functionality to find and enumerate image files in directories,
with support for recursive scanning and HEIC/HEIF format detection.
"""

from __future__ import annotations

from pathlib import Path

from ..config import IMAGE_EXTENSIONS
from .dependencies import HAS_HEIF_SUPPORT


def find_image_files(root_path: str | Path, recursive: bool = True) -> list[str]:
    """
    Find all image files in the given directory.

    Args:
        root_path: Directory path to search for images
        recursive: If True, search subdirectories recursively

    Returns:
        List of absolute file paths as strings

    Notes:
        - Automatically filters out HEIC/HEIF files if pillow-heif is not installed
        - Handles symlinks by resolving to canonical paths
        - Deduplicates files that may be encountered via multiple paths
    """
    root = Path(root_path)

    # Determine which extensions to scan based on HEIF support
    extensions_to_scan = IMAGE_EXTENSIONS
    if not HAS_HEIF_SUPPORT:
        extensions_to_scan = {ext for ext in IMAGE_EXTENSIONS if ext not in {'.heic', '.heif'}}

    images = []
    seen = set()  # Track resolved paths to avoid duplicates

    # Choose iterator based on recursive flag
    iterator = root.rglob('*') if recursive else root.glob('*')

    for filepath in iterator:
        if filepath.is_file():
            ext_lower = filepath.suffix.lower()
            if ext_lower in extensions_to_scan:
                # Resolve to absolute path and deduplicate
                resolved = str(filepath.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    images.append(resolved)

    return images


__all__ = ['find_image_files']
