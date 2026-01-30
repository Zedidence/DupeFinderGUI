"""
Argument parsing for the CLI interface.

Provides functions to create and configure the argument parser for the
duplicate finder command-line interface.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import DEFAULT_THRESHOLD, DEFAULT_WORKERS


def create_parser() -> argparse.ArgumentParser:
    """
    Create and configure the argument parser for the CLI.

    Returns:
        Configured ArgumentParser instance

    Notes:
        - Includes comprehensive help text with examples
        - Platform-specific notes for hardlink/symlink actions
        - Mutually exclusive groups for LSH control
    """
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

    # Positional argument
    parser.add_argument(
        'directory',
        type=Path,
        nargs='?',
        default=None,
        help='Directory to scan for duplicate images'
    )

    # Scanning options
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

    # LSH control (mutually exclusive)
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

    # Caching
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable SQLite caching (analyze all images fresh)'
    )

    # Action options
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

    # Performance options
    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=DEFAULT_WORKERS,
        help=f'Number of parallel workers. Default: {DEFAULT_WORKERS}'
    )

    # Export options
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

    # Output options
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

    return parser


def parse_arguments(argv=None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: List of argument strings (default: sys.argv)

    Returns:
        Parsed arguments as Namespace object

    Examples:
        >>> args = parse_arguments(['/path/to/photos', '--threshold', '5'])
        >>> args.directory
        Path('/path/to/photos')
        >>> args.threshold
        5
    """
    parser = create_parser()
    return parser.parse_args(argv)


__all__ = [
    'create_parser',
    'parse_arguments',
]
