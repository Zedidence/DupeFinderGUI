"""
Report formatting and display for the CLI interface.

Provides functions to format and print duplicate detection results in a
human-readable format.
"""

from __future__ import annotations

import logging

from ..models import DuplicateGroup, format_size


def _format_group_header(group_number: int, group: DuplicateGroup, match_type: str) -> str:
    """
    Format a group header line.

    Args:
        group_number: The group number (1-indexed)
        group: The duplicate group
        match_type: 'exact' or 'perceptual'

    Returns:
        Formatted header string
    """
    return f"\nGroup {group_number} ({len(group.images)} files):"


def _print_image_in_group(img, is_best: bool) -> None:
    """
    Print a single image entry in a duplicate group.

    Args:
        img: ImageInfo object
        is_best: True if this is the best (recommended to keep) image
    """
    marker = "  [KEEP]" if is_best else "  [DUPE]"
    print(f"{marker} {img.path}")
    print(f"         {img.width}x{img.height} | {format_size(img.file_size)} | "
          f"Score: {img.quality_score:.1f}")


def _calculate_statistics(groups: list[DuplicateGroup]) -> dict[str, int]:
    """
    Calculate statistics for duplicate groups.

    Args:
        groups: List of duplicate groups

    Returns:
        Dictionary with statistics:
        - total_duplicates: Number of duplicate files (excludes best in each group)
        - total_groups: Number of groups
        - total_waste: Total file size of duplicates (bytes)
    """
    total_duplicates = sum(len(g.images) - 1 for g in groups)
    total_groups = len(groups)
    total_waste = sum(
        sum(img.file_size for img in g.duplicates)
        for g in groups
    )

    return {
        'total_duplicates': total_duplicates,
        'total_groups': total_groups,
        'total_waste': total_waste,
    }


def _print_section_header(title: str) -> None:
    """Print a section header with divider lines."""
    print("\n" + "-" * 70)
    print(title)
    print("-" * 70)


def _print_duplicate_groups(
    groups: list[DuplicateGroup],
    section_title: str
) -> None:
    """
    Print a section of duplicate groups.

    Args:
        groups: List of duplicate groups to print
        section_title: Title for the section (e.g., "EXACT DUPLICATES")
    """
    if not groups:
        return

    _print_section_header(section_title)

    for i, group in enumerate(groups, 1):
        print(_format_group_header(i, group, ""))
        best = group.best_image

        # Sort by quality score (highest first)
        for img in sorted(group.images, key=lambda x: -x.quality_score):
            _print_image_in_group(img, img == best)


def print_duplicate_report(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    logger: logging.Logger
) -> None:
    """
    Print a comprehensive report of found duplicates.

    Args:
        exact_groups: List of exact duplicate groups
        perceptual_groups: List of perceptual duplicate groups
        logger: Logger instance (currently unused, kept for compatibility)

    Notes:
        - Prints to stdout with formatted sections
        - Shows statistics summary at top
        - Groups are numbered starting from 1
        - Images sorted by quality score within each group
        - Best image marked with [KEEP], others with [DUPE]
    """
    # Header
    print("\n" + "=" * 70)
    print("DUPLICATE IMAGE REPORT")
    print("=" * 70)

    # Statistics summary
    exact_stats = _calculate_statistics(exact_groups)
    perceptual_stats = _calculate_statistics(perceptual_groups)

    print(f"\nExact duplicates found: {exact_stats['total_duplicates']} files in "
          f"{exact_stats['total_groups']} groups")
    print(f"Perceptual duplicates found: {perceptual_stats['total_duplicates']} files in "
          f"{perceptual_stats['total_groups']} groups")

    # Exact duplicates section
    _print_duplicate_groups(exact_groups, "EXACT DUPLICATES (identical files)")

    # Perceptual duplicates section
    _print_duplicate_groups(perceptual_groups, "PERCEPTUAL DUPLICATES (visually similar)")

    # Footer with total space recoverable
    total_waste = exact_stats['total_waste'] + perceptual_stats['total_waste']
    print("\n" + "=" * 70)
    print(f"Total space recoverable: {format_size(total_waste)}")
    print("=" * 70)


__all__ = ['print_duplicate_report']
