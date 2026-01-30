"""
Export functionality for the Duplicate Image Finder.

Provides functions to export duplicate detection results to various file formats
including TXT and CSV.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ..models import DuplicateGroup


def _export_txt(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    file_handle: TextIO
) -> None:
    """
    Export duplicate results to TXT format.

    Args:
        exact_groups: List of exact duplicate groups
        perceptual_groups: List of perceptual duplicate groups
        file_handle: Open file handle to write to
    """
    file_handle.write("DUPLICATE IMAGE REPORT\n")
    file_handle.write("=" * 70 + "\n\n")

    # Exact duplicates section
    file_handle.write("EXACT DUPLICATES\n")
    file_handle.write("-" * 70 + "\n")
    for i, group in enumerate(exact_groups, 1):
        file_handle.write(f"\nGroup {i}:\n")
        best = group.best_image
        for img in group.images:
            marker = "[KEEP]" if img == best else "[DUPE]"
            file_handle.write(f"  {marker} {img.path}\n")

    # Perceptual duplicates section
    file_handle.write("\n\nPERCEPTUAL DUPLICATES\n")
    file_handle.write("-" * 70 + "\n")
    for i, group in enumerate(perceptual_groups, 1):
        file_handle.write(f"\nGroup {i}:\n")
        best = group.best_image
        for img in group.images:
            marker = "[KEEP]" if img == best else "[DUPE]"
            file_handle.write(f"  {marker} {img.path}\n")


def _export_csv(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    file_handle: TextIO
) -> None:
    """
    Export duplicate results to CSV format.

    Args:
        exact_groups: List of exact duplicate groups
        perceptual_groups: List of perceptual duplicate groups
        file_handle: Open file handle to write to

    Notes:
        CSV includes: group_id, match_type, status, path, width, height,
                     file_size, quality_score
    """
    # CSV header
    file_handle.write("group_id,match_type,status,path,width,height,file_size,quality_score\n")

    # Exact duplicates
    for i, group in enumerate(exact_groups, 1):
        best = group.best_image
        for img in group.images:
            status = "keep" if img == best else "duplicate"
            file_handle.write(
                f'{i},exact,{status},"{img.path}",{img.width},{img.height},'
                f'{img.file_size},{img.quality_score:.1f}\n'
            )

    # Perceptual duplicates (continue numbering from exact groups)
    for i, group in enumerate(perceptual_groups, len(exact_groups) + 1):
        best = group.best_image
        for img in group.images:
            status = "keep" if img == best else "duplicate"
            file_handle.write(
                f'{i},perceptual,{status},"{img.path}",{img.width},{img.height},'
                f'{img.file_size},{img.quality_score:.1f}\n'
            )


def export_results(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    output_path: Path,
    export_format: str = 'txt'
) -> None:
    """
    Export duplicate detection results to a file.

    Args:
        exact_groups: List of exact duplicate groups
        perceptual_groups: List of perceptual duplicate groups
        output_path: Path to output file
        export_format: Export format ('txt' or 'csv'). Default: 'txt'

    Raises:
        ValueError: If export_format is not 'txt' or 'csv'
        IOError: If file cannot be written

    Examples:
        >>> exact_groups = [group1, group2]
        >>> perceptual_groups = [group3, group4]
        >>> export_results(exact_groups, perceptual_groups, Path('results.txt'), 'txt')
        >>> export_results(exact_groups, perceptual_groups, Path('results.csv'), 'csv')
    """
    if export_format not in ('txt', 'csv'):
        raise ValueError(f"Unsupported export format: {export_format}. Use 'txt' or 'csv'.")

    with open(output_path, 'w', encoding='utf-8') as f:
        if export_format == 'txt':
            _export_txt(exact_groups, perceptual_groups, f)
        elif export_format == 'csv':
            _export_csv(exact_groups, perceptual_groups, f)


__all__ = ['export_results']
