#!/usr/bin/env python3
"""
Duplicate Image Finder - Command Line Interface
===============================================
A comprehensive tool for finding duplicate and visually similar images.

Features:
- Multi-stage detection: exact hash + perceptual hash
- Supports ALL common image formats
- Quality-based selection (keeps highest quality)
- Configurable similarity threshold
- Dry-run mode for safety
- Concurrent processing for speed

Usage:
    python -m dupefinder.cli /path/to/photos
    python -m dupefinder.cli /path/to/photos --action move --trash-dir ./duplicates

Author: Zach
"""

import argparse
import os
import sys
import shutil
import logging
import platform
from pathlib import Path
from typing import Optional

from .config import DEFAULT_THRESHOLD, DEFAULT_WORKERS
from .models import ImageInfo, DuplicateGroup, format_size
from .scanner import (
    find_image_files,
    analyze_images_parallel,
    find_exact_duplicates,
    find_perceptual_duplicates,
)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    return logging.getLogger(__name__)


def print_duplicate_report(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    logger: logging.Logger
):
    """Print a report of found duplicates."""
    print("\n" + "=" * 70)
    print("DUPLICATE IMAGE REPORT")
    print("=" * 70)
    
    total_exact = sum(len(g.images) - 1 for g in exact_groups)
    total_perceptual = sum(len(g.images) - 1 for g in perceptual_groups)
    
    print(f"\nExact duplicates found: {total_exact} files in {len(exact_groups)} groups")
    print(f"Perceptual duplicates found: {total_perceptual} files in {len(perceptual_groups)} groups")
    
    # Exact duplicates
    if exact_groups:
        print("\n" + "-" * 70)
        print("EXACT DUPLICATES (identical files)")
        print("-" * 70)
        
        for i, group in enumerate(exact_groups, 1):
            print(f"\nGroup {i} ({len(group.images)} files):")
            best = group.best_image
            
            for img in sorted(group.images, key=lambda x: -x.quality_score):
                marker = "  [KEEP]" if img == best else "  [DUPE]"
                print(f"{marker} {img.path}")
                print(f"         {img.width}x{img.height} | {format_size(img.file_size)} | "
                      f"Score: {img.quality_score:.1f}")
    
    # Perceptual duplicates
    if perceptual_groups:
        print("\n" + "-" * 70)
        print("PERCEPTUAL DUPLICATES (visually similar)")
        print("-" * 70)
        
        for i, group in enumerate(perceptual_groups, 1):
            print(f"\nGroup {i} ({len(group.images)} files):")
            best = group.best_image
            
            for img in sorted(group.images, key=lambda x: -x.quality_score):
                marker = "  [KEEP]" if img == best else "  [DUPE]"
                print(f"{marker} {img.path}")
                print(f"         {img.width}x{img.height} | {format_size(img.file_size)} | "
                      f"Score: {img.quality_score:.1f}")
    
    # Summary
    total_waste = sum(
        sum(img.file_size for img in g.duplicates) 
        for g in exact_groups + perceptual_groups
    )
    print("\n" + "=" * 70)
    print(f"Total space recoverable: {format_size(total_waste)}")
    print("=" * 70)


def _validate_file_accessible(filepath: str) -> tuple[bool, str]:
    """
    FIXED #2: Validate that a file exists and is accessible before operations.
    
    Args:
        filepath: Path to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not os.path.exists(filepath):
        return False, "File does not exist"
    
    if not os.path.isfile(filepath):
        return False, "Path is not a file"
    
    if not os.access(filepath, os.R_OK):
        return False, "File is not readable"
    
    # For delete/move, check write access to parent directory
    parent_dir = os.path.dirname(filepath)
    if not os.access(parent_dir, os.W_OK):
        return False, "Cannot write to parent directory"
    
    return True, ""


def _check_hardlink_support(source: Path, dest_dir: Path) -> tuple[bool, str]:
    """
    FIXED #11: Check if hardlinks are supported between source and destination.
    
    Hardlinks require:
    - Same filesystem
    - Admin privileges on Windows (usually)
    - Source and dest on same mount point
    
    Args:
        source: Source file path
        dest_dir: Destination directory
        
    Returns:
        Tuple of (is_supported, reason_if_not)
    """
    # Check if both paths are on the same filesystem
    try:
        source_dev = os.stat(source).st_dev
        dest_dev = os.stat(dest_dir).st_dev
        
        if source_dev != dest_dev:
            return False, "Source and destination are on different filesystems"
    except OSError as e:
        return False, f"Cannot check filesystem: {e}"
    
    # Windows-specific checks
    if platform.system() == 'Windows':
        # On Windows, hardlinks typically require admin privileges
        # or Developer Mode enabled in Windows 10+
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                return False, "Hardlinks on Windows require administrator privileges"
        except Exception:
            pass  # Assume it might work
    
    return True, ""


def _check_symlink_support(dest_dir: Path) -> tuple[bool, str]:
    """
    FIXED #11: Check if symlinks are supported in the destination directory.
    
    Symlinks require:
    - Admin privileges on Windows (usually)
    - Developer Mode on Windows 10+ (for unprivileged symlinks)
    
    Args:
        dest_dir: Destination directory
        
    Returns:
        Tuple of (is_supported, reason_if_not)
    """
    if platform.system() == 'Windows':
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                # Check for Developer Mode (Windows 10+)
                # This is a simplified check - the actual implementation
                # would need to query the registry
                return False, (
                    "Symlinks on Windows require administrator privileges "
                    "or Developer Mode enabled"
                )
        except Exception:
            pass  # Assume it might work
    
    return True, ""


def handle_duplicates(
    groups: list[DuplicateGroup],
    action: str,
    trash_dir: Optional[Path] = None,
    dry_run: bool = True,
    logger: logging.Logger = None
) -> dict:
    """
    Handle duplicate files based on action.
    
    Args:
        groups: List of DuplicateGroup objects
        action: One of 'delete', 'move', 'hardlink', 'symlink'
        trash_dir: Directory to move duplicates to (for 'move' action)
        dry_run: If True, only simulate actions
        logger: Logger instance
    
    Returns:
        Statistics dict with 'processed', 'errors', 'skipped', 'space_saved'
    """
    stats = {
        'processed': 0,
        'errors': 0,
        'skipped': 0,
        'space_saved': 0,
        'error_details': [],
    }
    
    # FIXED #11: Pre-check platform support for hardlink/symlink
    if action == 'hardlink' and not dry_run:
        # We'll check per-file since filesystem can vary
        pass
    elif action == 'symlink' and not dry_run:
        # Check overall symlink support
        if trash_dir:
            supported, reason = _check_symlink_support(trash_dir)
            if not supported:
                if logger:
                    logger.error(f"Symlink not supported: {reason}")
                    logger.info("Tip: On Windows, run as Administrator or enable Developer Mode")
                return stats
    
    for group in groups:
        best = group.best_image
        
        for dupe in group.duplicates:
            try:
                # FIXED #2: Validate file accessibility before operations
                if not dry_run:
                    is_valid, error_msg = _validate_file_accessible(dupe.path)
                    if not is_valid:
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': error_msg
                        })
                        if logger:
                            logger.warning(f"Skipped {dupe.path}: {error_msg}")
                        continue
                
                if dry_run:
                    if logger:
                        logger.info(f"[DRY RUN] Would {action}: {dupe.path}")
                    stats['processed'] += 1
                    stats['space_saved'] += dupe.file_size
                    continue
                
                dupe_path = Path(dupe.path)
                best_path = Path(best.path)
                
                if action == 'delete':
                    try:
                        dupe_path.unlink()
                        if logger:
                            logger.info(f"Deleted: {dupe.path}")
                    except PermissionError:
                        raise PermissionError(f"Cannot delete: file is read-only or locked")
                
                elif action == 'move':
                    if trash_dir:
                        # Handle name conflicts
                        dest = trash_dir / dupe_path.name
                        counter = 1
                        while dest.exists():
                            stem = dupe_path.stem
                            suffix = dupe_path.suffix
                            dest = trash_dir / f"{stem}_{counter}{suffix}"
                            counter += 1
                        
                        try:
                            shutil.move(str(dupe_path), str(dest))
                            if logger:
                                logger.info(f"Moved: {dupe.path} -> {dest}")
                        except PermissionError:
                            raise PermissionError(f"Cannot move: source or destination permission denied")
                
                elif action == 'hardlink':
                    # FIXED #11: Check hardlink support before attempting
                    supported, reason = _check_hardlink_support(best_path, dupe_path.parent)
                    if not supported:
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': f"Hardlink not supported: {reason}"
                        })
                        if logger:
                            logger.warning(f"Skipped hardlink for {dupe.path}: {reason}")
                        continue
                    
                    # Replace duplicate with hardlink to best
                    try:
                        dupe_path.unlink()
                        os.link(str(best_path), str(dupe_path))
                        if logger:
                            logger.info(f"Hardlinked: {dupe.path} -> {best.path}")
                    except OSError as e:
                        raise OSError(f"Hardlink failed: {e}")
                
                elif action == 'symlink':
                    # FIXED #11: Check symlink support before attempting
                    supported, reason = _check_symlink_support(dupe_path.parent)
                    if not supported:
                        stats['skipped'] += 1
                        stats['error_details'].append({
                            'path': dupe.path,
                            'error': f"Symlink not supported: {reason}"
                        })
                        if logger:
                            logger.warning(f"Skipped symlink for {dupe.path}: {reason}")
                        continue
                    
                    # Replace duplicate with symlink to best
                    try:
                        dupe_path.unlink()
                        rel_path = os.path.relpath(best_path, dupe_path.parent)
                        dupe_path.symlink_to(rel_path)
                        if logger:
                            logger.info(f"Symlinked: {dupe.path} -> {rel_path}")
                    except OSError as e:
                        raise OSError(f"Symlink failed: {e}")
                
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


def export_results(
    exact_groups: list[DuplicateGroup],
    perceptual_groups: list[DuplicateGroup],
    output_path: Path,
    export_format: str = 'txt'
):
    """Export duplicate results to a file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        if export_format == 'txt':
            f.write("DUPLICATE IMAGE REPORT\n")
            f.write("=" * 70 + "\n\n")
            
            f.write("EXACT DUPLICATES\n")
            f.write("-" * 70 + "\n")
            for i, group in enumerate(exact_groups, 1):
                f.write(f"\nGroup {i}:\n")
                best = group.best_image
                for img in group.images:
                    marker = "[KEEP]" if img == best else "[DUPE]"
                    f.write(f"  {marker} {img.path}\n")
            
            f.write("\n\nPERCEPTUAL DUPLICATES\n")
            f.write("-" * 70 + "\n")
            for i, group in enumerate(perceptual_groups, 1):
                f.write(f"\nGroup {i}:\n")
                best = group.best_image
                for img in group.images:
                    marker = "[KEEP]" if img == best else "[DUPE]"
                    f.write(f"  {marker} {img.path}\n")
        
        elif export_format == 'csv':
            f.write("group_id,match_type,status,path,width,height,file_size,quality_score\n")
            
            for i, group in enumerate(exact_groups, 1):
                best = group.best_image
                for img in group.images:
                    status = "keep" if img == best else "duplicate"
                    f.write(f'{i},exact,{status},"{img.path}",{img.width},{img.height},'
                            f'{img.file_size},{img.quality_score:.1f}\n')
            
            for i, group in enumerate(perceptual_groups, len(exact_groups) + 1):
                best = group.best_image
                for img in group.images:
                    status = "keep" if img == best else "duplicate"
                    f.write(f'{i},perceptual,{status},"{img.path}",{img.width},{img.height},'
                            f'{img.file_size},{img.quality_score:.1f}\n')


def main():
    parser = argparse.ArgumentParser(
        description='Find and manage duplicate images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/photos
      Scan for duplicates (report only, no changes)
  
  %(prog)s /path/to/photos --action move --trash-dir ./duplicates
      Move duplicates to a separate folder
  
  %(prog)s /path/to/photos --action delete --no-dry-run
      Actually delete duplicates (BE CAREFUL!)
  
  %(prog)s /path/to/photos --threshold 5 --exact-only
      Strict matching: exact duplicates + very similar perceptual matches
  
  %(prog)s /path/to/photos --export results.csv --export-format csv
      Export results to CSV for external review

Platform Notes:
  --action hardlink: Requires same filesystem. On Windows, needs admin privileges.
  --action symlink:  On Windows, needs admin privileges or Developer Mode.
        """
    )
    
    parser.add_argument(
        'directory',
        type=Path,
        nargs='?',
        default=None,
        help='Directory to scan for duplicate images'
    )
    
    parser.add_argument(
        '-r', '--no-recursive',
        action='store_true',
        help='Do not scan subdirectories'
    )
    
    parser.add_argument(
        '-t', '--threshold',
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f'Perceptual hash threshold (0-64, lower=stricter). Default: {DEFAULT_THRESHOLD}'
    )
    
    parser.add_argument(
        '--exact-only',
        action='store_true',
        help='Only find exact duplicates (skip perceptual matching)'
    )
    
    parser.add_argument(
        '--perceptual-only',
        action='store_true',
        help='Only find perceptual duplicates (skip exact matching)'
    )
<<<<<<< HEAD

    parser.add_argument(
        '--lsh',
        action='store_true',
        help='Force LSH acceleration on (overrides auto-selection)'
    )

    parser.add_argument(
        '--no-lsh',
        action='store_true',
        help='Force brute-force comparison, disable LSH (overrides auto-selection)'
    )

    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable SQLite caching (analyze all images fresh)'
    )

=======
    
    # FIXED #11: Add LSH control arguments
    lsh_group = parser.add_mutually_exclusive_group()
    lsh_group.add_argument(
        '--lsh',
        action='store_true',
        dest='force_lsh',
        help='Force LSH acceleration on (useful for 1K-5K images)'
    )
    lsh_group.add_argument(
        '--no-lsh',
        action='store_true',
        dest='no_lsh',
        help='Force brute-force comparison (disable LSH auto-selection)'
    )
    
>>>>>>> f8c4006cf8c5d119685f476d166eba4b77ed3780
    parser.add_argument(
        '-a', '--action',
        choices=['report', 'delete', 'move', 'hardlink', 'symlink'],
        default='report',
        help='Action to take on duplicates. Default: report'
    )
    
    parser.add_argument(
        '--trash-dir',
        type=Path,
        help='Directory to move duplicates to (for --action move)'
    )
    
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually perform the action (default is dry-run)'
    )
    
    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=DEFAULT_WORKERS,
        help=f'Number of parallel workers. Default: {DEFAULT_WORKERS}'
    )
    
    parser.add_argument(
        '-e', '--export',
        type=Path,
        help='Export results to file'
    )
    
    parser.add_argument(
        '--export-format',
        choices=['txt', 'csv'],
        default='txt',
        help='Export format. Default: txt'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable SQLite caching (analyze everything fresh)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )
    
    parser.add_argument(
        '--no-progress',
        action='store_true',
        help='Disable progress bars (useful for piping output)'
    )
    
    args = parser.parse_args()
    
    # Setup
    logger = setup_logging(args.verbose)
    dry_run = not args.no_dry_run
    
    # Interactive directory prompt if not provided
    if args.directory is None:
        print("\n" + "=" * 50)
        print("  DUPLICATE IMAGE FINDER")
        print("=" * 50)
        while True:
            dir_input = input("\nEnter the directory path to scan: ").strip()
            if not dir_input:
                print("Please enter a valid path.")
                continue
            
            # Handle quotes around path
            dir_input = dir_input.strip('"\'')
            args.directory = Path(dir_input)
            
            if args.directory.exists() and args.directory.is_dir():
                break
            else:
                print(f"Directory not found: {args.directory}")
                print("Please try again.")
    
    # Validate
    if not args.directory.exists():
        logger.error(f"Directory not found: {args.directory}")
        sys.exit(1)

    if args.action == 'move' and not args.trash_dir:
        logger.error("--trash-dir required for 'move' action")
        sys.exit(1)
<<<<<<< HEAD

    if args.trash_dir and not args.trash_dir.exists():
        args.trash_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created trash directory: {args.trash_dir}")

    # Validate mutually exclusive flags
    if args.lsh and args.no_lsh:
        logger.error("Cannot use both --lsh and --no-lsh")
        sys.exit(1)

    # Determine LSH usage
    use_lsh = None  # Auto-select by default
    if args.lsh:
        use_lsh = True
        logger.info("LSH acceleration forced on")
    elif args.no_lsh:
        use_lsh = False
        logger.info("LSH disabled (brute-force mode)")

    # Determine cache usage
    use_cache = not args.no_cache
    if args.no_cache:
        logger.info("Cache disabled - analyzing all images fresh")

=======
    
    # FIXED #2: Better error handling for trash directory creation
    if args.trash_dir:
        try:
            if not args.trash_dir.exists():
                args.trash_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created trash directory: {args.trash_dir}")
        except PermissionError:
            logger.error(f"Cannot create trash directory (permission denied): {args.trash_dir}")
            sys.exit(1)
        except OSError as e:
            logger.error(f"Cannot create trash directory: {e}")
            sys.exit(1)
    
    # FIXED #11: Pre-check platform support for hardlink/symlink
    if args.action == 'hardlink' and not dry_run:
        if platform.system() == 'Windows':
            logger.warning(
                "Note: Hardlinks on Windows require administrator privileges "
                "and source/destination must be on the same volume."
            )
    elif args.action == 'symlink' and not dry_run:
        if platform.system() == 'Windows':
            supported, reason = _check_symlink_support(args.directory)
            if not supported:
                logger.error(f"Symlinks not supported: {reason}")
                logger.info("Tip: Run as Administrator or enable Developer Mode in Windows Settings")
                sys.exit(1)
    
>>>>>>> f8c4006cf8c5d119685f476d166eba4b77ed3780
    show_progress = not args.no_progress
    use_cache = not args.no_cache
    
    # Determine LSH mode
    use_lsh = None  # Auto
    if args.force_lsh:
        use_lsh = True
    elif args.no_lsh:
        use_lsh = False
    
    # Find images
    logger.info(f"Scanning {args.directory} for images...")
    if show_progress:
        print("Scanning for image files...", end=" ", flush=True)
    recursive = not args.no_recursive
    image_files = find_image_files(args.directory, recursive=recursive)
    if show_progress:
        print(f"done!")
    logger.info(f"Found {len(image_files):,} image files")
    
    if not image_files:
        logger.info("No images found. Exiting.")
        sys.exit(0)
    
    # Analyze images
    logger.info("Analyzing images (this may take a while)...")
    images, cache_stats = analyze_images_parallel(
<<<<<<< HEAD
        image_files,
        max_workers=args.workers,
        logger=logger,
        show_progress=show_progress,
        use_cache=use_cache
    )

    # Show cache stats if cache was used
    if use_cache and cache_stats.cache_hits > 0:
        logger.info(f"Cache: {cache_stats.cache_hits:,} hits, {cache_stats.cache_misses:,} misses "
                   f"({cache_stats.hit_rate:.1f}% hit rate)")

=======
        image_files, 
        max_workers=args.workers,
        logger=logger,
        show_progress=show_progress,
        use_cache=use_cache,
    )
    
    # Show cache stats
    if use_cache and cache_stats.cache_hits > 0:
        logger.info(
            f"Cache: {cache_stats.cache_hits:,} hits, {cache_stats.cache_misses:,} misses "
            f"({cache_stats.hit_rate:.1f}% hit rate)"
        )
    
>>>>>>> f8c4006cf8c5d119685f476d166eba4b77ed3780
    # Filter out errors
    valid_images = [img for img in images if not img.error]
    error_count = len(images) - len(valid_images)
    if error_count:
        logger.warning(f"Could not analyze {error_count:,} files")
    
    # Find duplicates
    exact_groups = []
    perceptual_groups = []
    exact_hashes = set()
    
    if not args.perceptual_only:
        logger.info("Finding exact duplicates...")
        exact_groups = find_exact_duplicates(valid_images)
        exact_hashes = {img.file_hash for g in exact_groups for img in g.images}
        logger.info(f"Found {len(exact_groups):,} exact duplicate groups")
    
    if not args.exact_only:
        logger.info(f"Finding perceptual duplicates (threshold={args.threshold})...")
        perceptual_groups = find_perceptual_duplicates(
            valid_images,
            threshold=args.threshold,
            exclude_hashes=exact_hashes,
            start_id=len(exact_groups) + 1,
            show_progress=show_progress,
            use_lsh=use_lsh,
<<<<<<< HEAD
            logger=logger
=======
            logger=logger,
>>>>>>> f8c4006cf8c5d119685f476d166eba4b77ed3780
        )
        logger.info(f"Found {len(perceptual_groups):,} perceptual duplicate groups")
    
    # Report
    print_duplicate_report(exact_groups, perceptual_groups, logger)
    
    # Export if requested
    if args.export:
        export_results(exact_groups, perceptual_groups, args.export, args.export_format)
        logger.info(f"Results exported to: {args.export}")
    
    # Handle duplicates
    if args.action != 'report':
        all_groups = exact_groups + perceptual_groups
        
        if dry_run:
            logger.info("\n[DRY RUN MODE - No files will be modified]")
        else:
            # Confirmation
            total_dupes = sum(len(g.duplicates) for g in all_groups)
            confirm = input(f"\nThis will {args.action} {total_dupes:,} files. Continue? [y/N]: ")
            if confirm.lower() != 'y':
                logger.info("Aborted.")
                sys.exit(0)
        
        stats = handle_duplicates(
            all_groups,
            action=args.action,
            trash_dir=args.trash_dir,
            dry_run=dry_run,
            logger=logger
        )
        
        logger.info(f"\nProcessed: {stats['processed']:,} files")
        if stats['skipped'] > 0:
            logger.info(f"Skipped: {stats['skipped']:,} files")
        logger.info(f"Errors: {stats['errors']}")
        logger.info(f"Space {'would be ' if dry_run else ''}saved: {format_size(stats['space_saved'])}")


if __name__ == '__main__':
    main()