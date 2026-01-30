"""
CLI workflow orchestration for the Duplicate Image Finder.

Provides the CLIOrchestrator class that coordinates the entire CLI scanning
workflow from argument parsing through final reporting.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from ..scanner import (
    find_image_files,
    analyze_images_parallel,
    find_exact_duplicates,
    find_perceptual_duplicates,
)
from ..models import format_size
from ..utils.exporters import export_results
from ..utils.platform import check_symlink_support
from .arg_parser import parse_arguments
from .interactive import prompt_for_directory, confirm_action
from .reporting import print_duplicate_report
from .actions import handle_duplicates


def setup_logging(verbose: bool = False) -> logging.Logger:
    """
    Configure logging for the CLI.

    Args:
        verbose: Enable verbose (DEBUG level) logging

    Returns:
        Configured logger instance
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    return logging.getLogger(__name__)


class CLIOrchestrator:
    """
    Orchestrates the CLI scanning workflow.

    Manages the complete lifecycle from argument parsing through duplicate
    detection, reporting, and action execution.
    """

    def __init__(self):
        """Initialize the orchestrator."""
        self.logger = None
        self.args = None
        self.image_files = []
        self.images = []
        self.exact_groups = []
        self.perceptual_groups = []

    def run(self) -> int:
        """
        Execute the complete CLI workflow.

        Returns:
            Exit code (0 for success, 1 for error)

        Workflow phases:
        1. Setup & argument parsing
        2. Interactive prompts (if needed)
        3. Validation
        4. Configuration
        5. File scanning
        6. Image analysis
        7. Duplicate detection & reporting
        8. Action execution & cleanup
        """
        # Phase 1: Setup
        exit_code = self._setup_phase()
        if exit_code != 0:
            return exit_code

        # Phase 2: Interactive prompts
        exit_code = self._interactive_phase()
        if exit_code != 0:
            return exit_code

        # Phase 3: Validation
        exit_code = self._validate_phase()
        if exit_code != 0:
            return exit_code

        # Phase 4: Configuration
        self._configure_phase()

        # Phase 5: Scanning
        exit_code = self._scan_phase()
        if exit_code != 0:
            return exit_code

        # Phase 6: Analysis
        exit_code = self._analyze_phase()
        if exit_code != 0:
            return exit_code

        # Phase 7: Detection & Reporting
        self._detect_phase()
        self._report_phase()

        # Phase 8: Actions
        if self.args.action != 'report':
            self._action_phase()

        return 0

    def _setup_phase(self) -> int:
        """
        Phase 1: Parse arguments and setup logging.

        Returns:
            0 for success, non-zero for error
        """
        self.args = parse_arguments()
        self.logger = setup_logging(self.args.verbose)
        return 0

    def _interactive_phase(self) -> int:
        """
        Phase 2: Handle interactive directory prompt if needed.

        Returns:
            0 for success, non-zero for error
        """
        if self.args.directory is None:
            self.args.directory = prompt_for_directory()
        return 0

    def _validate_phase(self) -> int:
        """
        Phase 3: Validate arguments and check prerequisites.

        Returns:
            0 for success, 1 for validation error
        """
        # Validate directory exists
        if not self.args.directory.exists():
            self.logger.error(f"Directory not found: {self.args.directory}")
            return 1

        # Validate trash-dir for move action
        if self.args.action == 'move' and not self.args.trash_dir:
            self.logger.error("--trash-dir required for 'move' action")
            return 1

        # Create trash directory if needed
        if self.args.trash_dir:
            try:
                if not self.args.trash_dir.exists():
                    self.args.trash_dir.mkdir(parents=True, exist_ok=True)
                    self.logger.info(f"Created trash directory: {self.args.trash_dir}")
            except PermissionError:
                self.logger.error(f"Cannot create trash directory (permission denied): {self.args.trash_dir}")
                return 1
            except OSError as e:
                self.logger.error(f"Cannot create trash directory: {e}")
                return 1

        # Platform-specific checks for hardlink/symlink
        dry_run = not self.args.no_dry_run

        if self.args.action == 'hardlink' and not dry_run:
            import platform as platform_module
            if platform_module.system() == 'Windows':
                self.logger.warning(
                    "Note: Hardlinks on Windows require administrator privileges "
                    "and source/destination must be on the same volume."
                )

        elif self.args.action == 'symlink' and not dry_run:
            import platform as platform_module
            if platform_module.system() == 'Windows':
                supported, reason = check_symlink_support(self.args.directory)
                if not supported:
                    self.logger.error(f"Symlinks not supported: {reason}")
                    self.logger.info("Tip: Run as Administrator or enable Developer Mode in Windows Settings")
                    return 1

        return 0

    def _configure_phase(self) -> None:
        """Phase 4: Configure runtime options."""
        # Determine cache usage
        self.use_cache = not self.args.no_cache
        if self.args.no_cache:
            self.logger.info("Cache disabled - analyzing all images fresh")

        # Determine LSH mode
        self.use_lsh = None  # Auto-select by default
        if self.args.force_lsh:
            self.use_lsh = True
            self.logger.info("LSH acceleration forced on")
        elif self.args.no_lsh:
            self.use_lsh = False
            self.logger.info("LSH disabled (brute-force mode)")

        # Progress display
        self.show_progress = not self.args.no_progress

    def _scan_phase(self) -> int:
        """
        Phase 5: Scan for image files.

        Returns:
            0 for success, non-zero if no images found
        """
        self.logger.info(f"Scanning {self.args.directory} for images...")
        if self.show_progress:
            print("Scanning for image files...", end=" ", flush=True)

        recursive = not self.args.no_recursive
        self.image_files = find_image_files(self.args.directory, recursive=recursive)

        if self.show_progress:
            print("done!")

        self.logger.info(f"Found {len(self.image_files):,} image files")

        if not self.image_files:
            self.logger.info("No images found. Exiting.")
            return 1

        return 0

    def _analyze_phase(self) -> int:
        """
        Phase 6: Analyze images in parallel.

        Returns:
            0 for success
        """
        self.logger.info("Analyzing images (this may take a while)...")
        self.images, cache_stats = analyze_images_parallel(
            self.image_files,
            max_workers=self.args.workers,
            logger=self.logger,
            show_progress=self.show_progress,
            use_cache=self.use_cache,
        )

        # Show cache stats
        if self.use_cache and cache_stats.cache_hits > 0:
            self.logger.info(
                f"Cache: {cache_stats.cache_hits:,} hits, {cache_stats.cache_misses:,} misses "
                f"({cache_stats.hit_rate:.1f}% hit rate)"
            )

        # Filter out errors
        valid_images = [img for img in self.images if not img.error]
        error_count = len(self.images) - len(valid_images)
        if error_count:
            self.logger.warning(f"Could not analyze {error_count:,} files")

        self.images = valid_images
        return 0

    def _detect_phase(self) -> None:
        """Phase 7: Detect exact and perceptual duplicates."""
        exact_hashes = set()

        # Find exact duplicates
        if not self.args.perceptual_only:
            self.logger.info("Finding exact duplicates...")
            self.exact_groups = find_exact_duplicates(self.images)
            exact_hashes = {img.file_hash for g in self.exact_groups for img in g.images}
            self.logger.info(f"Found {len(self.exact_groups):,} exact duplicate groups")

        # Find perceptual duplicates
        if not self.args.exact_only:
            self.logger.info(f"Finding perceptual duplicates (threshold={self.args.threshold})...")
            self.perceptual_groups = find_perceptual_duplicates(
                self.images,
                threshold=self.args.threshold,
                exclude_hashes=exact_hashes,
                start_id=len(self.exact_groups) + 1,
                show_progress=self.show_progress,
                use_lsh=self.use_lsh,
                logger=self.logger,
            )
            self.logger.info(f"Found {len(self.perceptual_groups):,} perceptual duplicate groups")

    def _report_phase(self) -> None:
        """Phase 7b: Generate and display report, handle exports."""
        # Print report
        print_duplicate_report(self.exact_groups, self.perceptual_groups, self.logger)

        # Export if requested
        if self.args.export:
            export_results(
                self.exact_groups,
                self.perceptual_groups,
                self.args.export,
                self.args.export_format
            )
            self.logger.info(f"Results exported to: {self.args.export}")

    def _action_phase(self) -> None:
        """Phase 8: Execute action on duplicates and show statistics."""
        all_groups = self.exact_groups + self.perceptual_groups
        dry_run = not self.args.no_dry_run

        if dry_run:
            self.logger.info("\n[DRY RUN MODE - No files will be modified]")
        else:
            # Confirmation
            total_dupes = sum(len(g.duplicates) for g in all_groups)
            if not confirm_action(self.args.action, total_dupes):
                self.logger.info("Aborted.")
                sys.exit(0)

        stats = handle_duplicates(
            all_groups,
            action=self.args.action,
            trash_dir=self.args.trash_dir,
            dry_run=dry_run,
            logger=self.logger
        )

        self.logger.info(f"\nProcessed: {stats['processed']:,} files")
        if stats['skipped'] > 0:
            self.logger.info(f"Skipped: {stats['skipped']:,} files")
        self.logger.info(f"Errors: {stats['errors']}")
        self.logger.info(f"Space {'would be ' if dry_run else ''}saved: {format_size(stats['space_saved'])}")


__all__ = ['CLIOrchestrator', 'setup_logging']
