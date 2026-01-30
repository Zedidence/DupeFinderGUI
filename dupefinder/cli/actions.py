"""
Duplicate file action handlers for the CLI interface.

Provides functions to perform actions on duplicate files including delete,
move, hardlink, and symlink operations with comprehensive error handling.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from ..models import DuplicateGroup
from ..utils.validators import validate_file_accessible
from ..utils.platform import check_hardlink_support, check_symlink_support


def _generate_unique_filename(dest: Path, base_path: Path) -> Path:
    """
    Generate a unique filename by appending a counter if file exists.

    Args:
        dest: Desired destination path
        base_path: Base path for generating alternatives

    Returns:
        Path that doesn't exist

    Examples:
        >>> _generate_unique_filename(Path('/trash/photo.jpg'), Path('/data/photo.jpg'))
        Path('/trash/photo_1.jpg')  # if photo.jpg exists
    """
    if not dest.exists():
        return dest

    stem = base_path.stem
    suffix = base_path.suffix
    counter = 1

    while dest.exists():
        dest = dest.parent / f"{stem}_{counter}{suffix}"
        counter += 1

    return dest


def _perform_delete(dupe_path: Path, logger: Optional[logging.Logger]) -> None:
    """
    Delete a duplicate file.

    Args:
        dupe_path: Path to the duplicate file
        logger: Optional logger instance

    Raises:
        PermissionError: If file cannot be deleted
    """
    try:
        dupe_path.unlink()
        if logger:
            logger.info(f"Deleted: {dupe_path}")
    except PermissionError:
        raise PermissionError(f"Cannot delete: file is read-only or locked")


def _perform_move(
    dupe_path: Path,
    trash_dir: Path,
    logger: Optional[logging.Logger]
) -> None:
    """
    Move a duplicate file to trash directory, handling name conflicts.

    Args:
        dupe_path: Path to the duplicate file
        trash_dir: Destination directory
        logger: Optional logger instance

    Raises:
        PermissionError: If file cannot be moved
    """
    # Handle name conflicts by generating unique filename
    dest = _generate_unique_filename(trash_dir / dupe_path.name, dupe_path)

    try:
        shutil.move(str(dupe_path), str(dest))
        if logger:
            logger.info(f"Moved: {dupe_path} -> {dest}")
    except PermissionError:
        raise PermissionError(f"Cannot move: source or destination permission denied")


def _perform_hardlink(
    dupe_path: Path,
    best_path: Path,
    logger: Optional[logging.Logger]
) -> None:
    """
    Replace duplicate with hardlink to best image.

    Args:
        dupe_path: Path to the duplicate file
        best_path: Path to the best (keep) image
        logger: Optional logger instance

    Raises:
        OSError: If hardlink operation fails
        ValueError: If hardlink is not supported (checked before calling)
    """
    # Check hardlink support
    supported, reason = check_hardlink_support(best_path, dupe_path.parent)
    if not supported:
        raise ValueError(f"Hardlink not supported: {reason}")

    try:
        dupe_path.unlink()
        os.link(str(best_path), str(dupe_path))
        if logger:
            logger.info(f"Hardlinked: {dupe_path} -> {best_path}")
    except OSError as e:
        raise OSError(f"Hardlink failed: {e}")


def _perform_symlink(
    dupe_path: Path,
    best_path: Path,
    logger: Optional[logging.Logger]
) -> None:
    """
    Replace duplicate with symlink to best image.

    Args:
        dupe_path: Path to the duplicate file
        best_path: Path to the best (keep) image
        logger: Optional logger instance

    Raises:
        OSError: If symlink operation fails
        ValueError: If symlink is not supported (checked before calling)
    """
    # Check symlink support
    supported, reason = check_symlink_support(dupe_path.parent)
    if not supported:
        raise ValueError(f"Symlink not supported: {reason}")

    try:
        dupe_path.unlink()
        rel_path = os.path.relpath(best_path, dupe_path.parent)
        dupe_path.symlink_to(rel_path)
        if logger:
            logger.info(f"Symlinked: {dupe_path} -> {rel_path}")
    except OSError as e:
        raise OSError(f"Symlink failed: {e}")


def handle_duplicates(
    groups: list[DuplicateGroup],
    action: str,
    trash_dir: Optional[Path] = None,
    dry_run: bool = True,
    logger: Optional[logging.Logger] = None
) -> dict:
    """
    Handle duplicate files based on action.

    Args:
        groups: List of DuplicateGroup objects
        action: One of 'delete', 'move', 'hardlink', 'symlink'
        trash_dir: Directory to move duplicates to (for 'move' action)
        dry_run: If True, only simulate actions
        logger: Optional logger instance

    Returns:
        Statistics dictionary with keys:
        - processed: Number of successfully processed files
        - errors: Number of errors encountered
        - skipped: Number of files skipped
        - space_saved: Total bytes saved
        - error_details: List of error dictionaries with 'path' and 'error' keys

    Examples:
        >>> groups = [group1, group2]
        >>> stats = handle_duplicates(groups, 'delete', dry_run=True)
        >>> stats['processed']
        42
    """
    stats = {
        'processed': 0,
        'errors': 0,
        'skipped': 0,
        'space_saved': 0,
        'error_details': [],
    }

    # Pre-check symlink support if needed
    if action == 'symlink' and not dry_run:
        if trash_dir:
            supported, reason = check_symlink_support(trash_dir)
            if not supported:
                if logger:
                    logger.error(f"Symlink not supported: {reason}")
                    logger.info("Tip: On Windows, run as Administrator or enable Developer Mode")
                return stats

    for group in groups:
        best = group.best_image

        for dupe in group.duplicates:
            try:
                # Validate file accessibility before operations
                if not dry_run:
                    is_valid, error_msg = validate_file_accessible(dupe.path)
                    if not is_valid:
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': error_msg
                        })
                        if logger:
                            logger.warning(f"Skipped {dupe.path}: {error_msg}")
                        continue

                # Dry run mode
                if dry_run:
                    if logger:
                        logger.info(f"[DRY RUN] Would {action}: {dupe.path}")
                    stats['processed'] += 1
                    stats['space_saved'] += dupe.file_size
                    continue

                # Perform the actual action
                dupe_path = Path(dupe.path)
                best_path = Path(best.path)

                if action == 'delete':
                    _perform_delete(dupe_path, logger)

                elif action == 'move':
                    if trash_dir:
                        _perform_move(dupe_path, trash_dir, logger)

                elif action == 'hardlink':
                    try:
                        _perform_hardlink(dupe_path, best_path, logger)
                    except ValueError as e:
                        # Hardlink not supported for this file
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': str(e)
                        })
                        if logger:
                            logger.warning(f"Skipped hardlink for {dupe.path}: {e}")
                        continue

                elif action == 'symlink':
                    try:
                        _perform_symlink(dupe_path, best_path, logger)
                    except ValueError as e:
                        # Symlink not supported for this file
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': str(e)
                        })
                        if logger:
                            logger.warning(f"Skipped symlink for {dupe.path}: {e}")
                        continue

                stats['processed'] += 1
                stats['space_saved'] += dupe.file_size

            except PermissionError as e:
                stats['errors'] += 1
                stats['error_details'].append({
                    'path': dupe.path,
                    'error': str(e)
                })
                if logger:
                    logger.error(f"Permission denied for {dupe.path}: {e}")
            except FileNotFoundError:
                stats['errors'] += 1
                stats['error_details'].append({
                    'path': dupe.path,
                    'error': 'File not found (may have been deleted)'
                })
                if logger:
                    logger.error(f"File not found: {dupe.path}")
            except OSError as e:
                stats['errors'] += 1
                stats['error_details'].append({
                    'path': dupe.path,
                    'error': str(e)
                })
                if logger:
                    logger.error(f"OS error handling {dupe.path}: {e}")
            except Exception as e:
                stats['errors'] += 1
                stats['error_details'].append({
                    'path': dupe.path,
                    'error': str(e)
                })
                if logger:
                    logger.error(f"Error handling {dupe.path}: {e}")

    return stats


__all__ = ['handle_duplicates']
