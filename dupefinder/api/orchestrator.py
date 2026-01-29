"""
Scan orchestration for the Duplicate Image Finder.

Provides the ScanOrchestrator class that coordinates the scanning process,
including file discovery, image analysis, duplicate detection, and progress tracking.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime
from typing import Callable, Optional

from ..state import ScanState, HistoryManager
from ..scanner import (
    find_image_files,
    analyze_images_parallel,
    find_exact_duplicates,
    find_perceptual_duplicates,
)
from ..models import ImageInfo, DuplicateGroup
from ..database import CacheStats
from ..config import LSH_AUTO_THRESHOLD
from ..utils import formatters, selection

# Module logger
_logger = logging.getLogger(__name__)

# Threshold for auto-disabling perceptual matching in GUI
# Perceptual matching is O(n²), so 50K images = 1.25 billion comparisons
PERCEPTUAL_AUTO_DISABLE_THRESHOLD = 50000


class ProgressTracker:
    """
    Tracks and updates scan progress through various stages.

    Handles progress callbacks, cancel/pause checks, and state updates
    with optimized update frequency to reduce overhead.
    """

    def __init__(self, scan_state: ScanState, save_callback: Callable[[], None]):
        """
        Initialize the progress tracker.

        Args:
            scan_state: Shared scan state object
            save_callback: Callback to save state (thread-safe)
        """
        self.scan_state = scan_state
        self.save_callback = save_callback
        self.last_save_time = time.time()
        self.last_progress_update = time.time()

    def check_cancelled(self) -> bool:
        """Check if scan has been cancelled."""
        return self.scan_state.cancel_requested

    def handle_pause(self) -> None:
        """Block while scan is paused."""
        while self.scan_state.paused and not self.scan_state.cancel_requested:
            time.sleep(0.5)

    def update_analysis_progress(
        self,
        current: int,
        total: int,
        analysis_start_time: float
    ) -> None:
        """
        Update progress during image analysis phase.

        Args:
            current: Current image number
            total: Total images to analyze
            analysis_start_time: Timestamp when analysis started
        """
        # Check for cancel
        if self.check_cancelled():
            return

        # Handle pause
        self.handle_pause()

        current_time = time.time()

        # Optimized: Only update when 0.5 seconds have passed or final update
        should_update = (current_time - self.last_progress_update >= 0.5) or (current == total)

        if should_update:
            self.scan_state.analyzed = current
            self.scan_state.progress = int(current / total * 50)  # 0-50% for analysis
            self.scan_state.stage_progress = int(current / total * 100)

            elapsed = current_time - analysis_start_time

            # Update progress details
            self.scan_state.progress_details['elapsed_seconds'] = current_time - self.scan_state.progress_details['start_time']

            # Update message every 2 seconds
            if current_time - self.last_progress_update >= 2:
                rate = current / elapsed if elapsed > 0 else 0
                remaining = total - current

                self.scan_state.progress_details['rate'] = round(rate, 1)

                if rate > 0:
                    eta_seconds = remaining / rate
                    self.scan_state.progress_details['eta_seconds'] = int(eta_seconds)
                    eta_str = formatters.format_time_estimate(eta_seconds)
                    self.scan_state.message = (
                        f'Analyzing images: {formatters.format_number(current)}/{formatters.format_number(total)} '
                        f'({int(rate)}/sec, ~{eta_str} remaining)'
                    )
                else:
                    self.scan_state.message = (
                        f'Analyzing images: {formatters.format_number(current)}/{formatters.format_number(total)}'
                    )
                self.last_progress_update = current_time

            # Save state every 5 seconds
            if current_time - self.last_save_time > 5:
                self.save_callback()
                self.last_save_time = current_time

    def update_comparison_progress(
        self,
        current: int,
        total: int,
        comparison_start_time: float
    ) -> None:
        """
        Update progress during comparison phase.

        Args:
            current: Current comparison number
            total: Total comparisons to perform
            comparison_start_time: Timestamp when comparisons started
        """
        # Check for cancel
        if self.check_cancelled():
            return

        # Handle pause
        self.handle_pause()

        current_time = time.time()

        # Optimized: Only update when 0.5 seconds have passed or final update
        should_update = (current_time - self.last_progress_update >= 0.5) or (current == total)

        if should_update:
            self.scan_state.progress = 60 + int(current / total * 35)
            self.scan_state.stage_progress = int(current / total * 100)
            self.scan_state.progress_details['comparisons_done'] = current
            self.scan_state.progress_details['elapsed_seconds'] = time.time() - self.scan_state.progress_details['start_time']

            # Update message every 2 seconds with progress
            if current_time - self.last_progress_update >= 2:
                elapsed = current_time - comparison_start_time
                rate = current / elapsed if elapsed > 0 else 0
                remaining = total - current

                self.scan_state.progress_details['rate'] = round(rate, 1)

                if rate > 0:
                    eta_seconds = remaining / rate
                    self.scan_state.progress_details['eta_seconds'] = int(eta_seconds)
                    eta_str = formatters.format_time_estimate(eta_seconds)
                    self.scan_state.message = (
                        f'Comparing images: {formatters.format_number(current)}/{formatters.format_number(total)} '
                        f'({formatters.format_number(int(rate))}/sec, ~{eta_str} remaining)'
                    )
                self.last_progress_update = current_time


class ScanOrchestrator:
    """
    Orchestrates the complete scanning process.

    Coordinates file discovery, image analysis, duplicate detection,
    and result finalization with progress tracking and error handling.
    """

    def __init__(
        self,
        scan_state: ScanState,
        directory: str,
        threshold: int,
        exact_only: bool,
        perceptual_only: bool,
        recursive: bool = True,
        use_cache: bool = True,
        use_lsh: Optional[bool] = None,
        workers: int = 4,
        auto_select_strategy: str = 'quality',
        save_callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the scan orchestrator.

        Args:
            scan_state: Shared scan state object
            directory: Directory to scan
            threshold: Perceptual hash threshold
            exact_only: Only find exact duplicates
            perceptual_only: Only find perceptual duplicates
            recursive: Scan subdirectories
            use_cache: Use SQLite caching
            use_lsh: Force LSH on/off (None = auto)
            workers: Number of parallel workers
            auto_select_strategy: Selection strategy
            save_callback: Callback to save state (thread-safe)
        """
        self.scan_state = scan_state
        self.directory = directory
        self.threshold = threshold
        self.exact_only = exact_only
        self.perceptual_only = perceptual_only
        self.recursive = recursive
        self.use_cache = use_cache
        self.use_lsh = use_lsh
        self.workers = workers
        self.auto_select_strategy = auto_select_strategy
        self.save_callback = save_callback or (lambda: None)

        # Track if we auto-disabled perceptual
        self.auto_disabled_perceptual = False

    def run(self) -> None:
        """
        Execute the complete scan process.

        This is the main entry point that orchestrates all scan phases.
        """
        try:
            # Initialize scan state
            self.scan_state.reset()
            self.scan_state.status = 'scanning'
            self.scan_state.stage = 'scanning'
            self.scan_state.directory = self.directory
            self.scan_state.message = 'Scanning for image files...'
            self.scan_state.settings = {
                'threshold': self.threshold,
                'exact_only': self.exact_only,
                'perceptual_only': self.perceptual_only,
                'recursive': self.recursive,
                'use_cache': self.use_cache,
                'use_lsh': self.use_lsh,
                'workers': self.workers,
                'auto_select_strategy': self.auto_select_strategy,
            }
            self.scan_state.progress_details['start_time'] = time.time()

            # Save to history
            HistoryManager.save_directory(self.directory)

            # Phase 1: Find images
            image_files = self._find_images()
            if image_files is None:
                return  # Cancelled or no images found

            # Phase 2: Analyze images
            images, cache_stats = self._analyze_images(image_files)
            if images is None:
                return  # Cancelled or error

            # Phase 3: Find exact duplicates
            exact_groups, exact_hashes = self._find_exact_dupes(images)
            if exact_groups is None:
                return  # Cancelled

            # Phase 4: Find perceptual duplicates
            perceptual_groups = self._find_perceptual_dupes(images, exact_hashes)
            if perceptual_groups is None:
                return  # Cancelled

            # Phase 5: Finalize results
            self._finalize_results(exact_groups, perceptual_groups)

        except Exception as e:
            self.scan_state.status = 'error'
            self.scan_state.message = f'Error: {str(e)}'
            _logger.exception(f"Scan error: {e}")
            self.save_callback()

    def _find_images(self) -> Optional[list[str]]:
        """
        Phase 1: Find image files in the directory.

        Returns:
            List of image file paths, or None if cancelled/empty
        """
        # Check for cancel
        if self.scan_state.cancel_requested:
            self.scan_state.status = 'cancelled'
            self.scan_state.message = 'Scan cancelled by user'
            self.save_callback()
            return None

        # Find images
        image_files = find_image_files(self.directory, recursive=self.recursive)
        self.scan_state.total_files = len(image_files)
        self.scan_state.progress_details['elapsed_seconds'] = time.time() - self.scan_state.progress_details['start_time']

        if not image_files:
            self.scan_state.status = 'complete'
            self.scan_state.message = 'No images found in directory'
            self.save_callback()
            return None

        # Check if we should auto-disable perceptual matching
        if (not self.exact_only and not self.perceptual_only and
            len(image_files) > PERCEPTUAL_AUTO_DISABLE_THRESHOLD and self.use_lsh is not True):
            self.auto_disabled_perceptual = True
            self.exact_only = True

            warning_msg = (
                f'⚠️ LARGE COLLECTION DETECTED ({formatters.format_number(len(image_files))} images). '
                f'Perceptual matching has been automatically disabled. '
                f'Enable LSH in Advanced Options to process large collections with perceptual matching.'
            )
            self.scan_state.message = warning_msg
            self.scan_state.settings['exact_only'] = True
            self.scan_state.settings['auto_disabled_perceptual'] = True
            self.save_callback()
            time.sleep(3)

        return image_files

    def _analyze_images(self, filepaths: list[str]) -> Optional[tuple[list[ImageInfo], CacheStats]]:
        """
        Phase 2: Analyze images with progress tracking.

        Args:
            filepaths: List of image file paths

        Returns:
            Tuple of (valid images, cache stats), or None if cancelled
        """
        # Check for cancel
        if self.scan_state.cancel_requested:
            self.scan_state.status = 'cancelled'
            self.scan_state.message = 'Scan cancelled by user'
            self.save_callback()
            return None

        # Analyze images
        self.scan_state.status = 'analyzing'
        self.scan_state.stage = 'analyzing'
        self.scan_state.message = f'Analyzing {formatters.format_number(len(filepaths))} images...'
        self.save_callback()

        analysis_start_time = time.time()

        # Create progress tracker
        progress_tracker = ProgressTracker(self.scan_state, self.save_callback)

        def analysis_progress_callback(current: int, total: int):
            progress_tracker.update_analysis_progress(current, total, analysis_start_time)

        # Use the cached parallel analyzer
        images, cache_stats = analyze_images_parallel(
            filepaths=filepaths,
            max_workers=self.workers,
            progress_callback=analysis_progress_callback,
            show_progress=False,
            use_cache=self.use_cache,
        )

        # Update cache stats in progress details
        self.scan_state.progress_details['cache_hits'] = cache_stats.cache_hits
        self.scan_state.progress_details['cache_misses'] = cache_stats.cache_misses

        # Check for cancel
        if self.scan_state.cancel_requested:
            self.scan_state.status = 'cancelled'
            self.scan_state.message = f'Scan cancelled (analyzed {formatters.format_number(len(images))} images)'
            self.save_callback()
            return None

        # Log cache stats
        if cache_stats.cache_hits > 0:
            _logger.info(f"Cache: {cache_stats.cache_hits:,} hits, {cache_stats.cache_misses:,} misses "
                         f"({cache_stats.hit_rate:.1f}% hit rate)")

        # Separate valid images from errors
        valid_images = [img for img in images if not img.error]
        error_images = [img for img in images if img.error]
        error_count = len(error_images)

        self.scan_state.error_images = error_images

        if not valid_images:
            self.scan_state.status = 'complete'
            self.scan_state.message = f'No valid images could be analyzed ({error_count} errors)'
            self.save_callback()
            return None

        if error_count > 0:
            _logger.warning(f"Warning: {error_count} images could not be analyzed")

        return valid_images, cache_stats

    def _find_exact_dupes(self, images: list[ImageInfo]) -> Optional[tuple[list[DuplicateGroup], set[str]]]:
        """
        Phase 3: Find exact duplicates.

        Args:
            images: List of valid images

        Returns:
            Tuple of (exact groups, exact hashes), or None if cancelled
        """
        exact_groups = []
        exact_hashes = set()

        if not self.perceptual_only:
            self.scan_state.status = 'comparing'
            self.scan_state.stage = 'exact_matching'
            self.scan_state.message = f'Finding exact duplicates among {formatters.format_number(len(images))} images...'
            self.scan_state.stage_progress = 0

            # Check for cancel
            if self.scan_state.cancel_requested:
                self.scan_state.status = 'cancelled'
                self.scan_state.message = 'Scan cancelled by user'
                self.save_callback()
                return None

            exact_groups = find_exact_duplicates(images)
            exact_hashes = {img.file_hash for g in exact_groups for img in g.images}

            self.scan_state.progress_details['exact_groups'] = len(exact_groups)
            exact_dupe_count = sum(len(g.images) - 1 for g in exact_groups)
            self.scan_state.message = (
                f'Found {formatters.format_number(exact_dupe_count)} exact duplicates '
                f'in {formatters.format_number(len(exact_groups))} groups'
            )
            self.scan_state.stage_progress = 100

        self.scan_state.progress = 60
        self.save_callback()

        return exact_groups, exact_hashes

    def _find_perceptual_dupes(
        self,
        images: list[ImageInfo],
        exclude_hashes: set[str]
    ) -> Optional[list[DuplicateGroup]]:
        """
        Phase 4: Find perceptual duplicates.

        Args:
            images: List of valid images
            exclude_hashes: File hashes to exclude (exact duplicates)

        Returns:
            List of perceptual duplicate groups, or None if cancelled
        """
        perceptual_groups = []

        if not self.exact_only:
            # Calculate expected comparisons for progress
            candidates_count = len([img for img in images
                                   if img.perceptual_hash and img.file_hash not in exclude_hashes])

            # Determine if we'll use LSH
            if self.use_lsh is None:
                # Auto-select based on collection size
                will_use_lsh = candidates_count >= LSH_AUTO_THRESHOLD
            else:
                will_use_lsh = self.use_lsh

            self.scan_state.progress_details['using_lsh'] = will_use_lsh

            if will_use_lsh:
                self.scan_state.message = (
                    f'Finding visually similar images using LSH ({formatters.format_number(candidates_count)} candidates)...'
                )
            else:
                total_comparisons = (candidates_count * (candidates_count - 1)) // 2
                self.scan_state.progress_details['total_comparisons'] = total_comparisons
                self.scan_state.message = (
                    f'Finding visually similar images ({formatters.format_number(candidates_count)} candidates, '
                    f'{formatters.format_number(total_comparisons)} comparisons)...'
                )

            self.scan_state.stage = 'perceptual_matching'
            self.scan_state.stage_progress = 0

            # Check for cancel
            if self.scan_state.cancel_requested:
                self.scan_state.status = 'cancelled'
                self.scan_state.message = 'Scan cancelled by user'
                self.save_callback()
                return None

            comparison_start_time = time.time()

            # Create progress tracker
            progress_tracker = ProgressTracker(self.scan_state, self.save_callback)

            def comparison_progress_callback(current: int, total: int):
                progress_tracker.update_comparison_progress(current, total, comparison_start_time)

            perceptual_groups = find_perceptual_duplicates(
                images,
                threshold=self.threshold,
                exclude_hashes=exclude_hashes,
                start_id=len(self.scan_state.groups) + 1 if hasattr(self, 'exact_groups') else 1,
                progress_callback=comparison_progress_callback,
                show_progress=False,
                use_lsh=self.use_lsh,
            )

            self.scan_state.progress_details['perceptual_groups'] = len(perceptual_groups)

        return perceptual_groups

    def _finalize_results(
        self,
        exact_groups: list[DuplicateGroup],
        perceptual_groups: list[DuplicateGroup]
    ) -> None:
        """
        Phase 5: Finalize results and build summary.

        Args:
            exact_groups: List of exact duplicate groups
            perceptual_groups: List of perceptual duplicate groups
        """
        # Check for cancel one last time
        if self.scan_state.cancel_requested:
            self.scan_state.status = 'cancelled'
            self.scan_state.message = 'Scan cancelled by user'
            self.save_callback()
            return

        self.scan_state.groups = exact_groups + perceptual_groups
        self.scan_state.progress = 100
        self.scan_state.stage = 'complete'
        self.scan_state.stage_progress = 100
        self.scan_state.status = 'complete'

        # Apply auto-selection strategy
        self.scan_state.selections = selection.apply_selection_strategy(
            self.scan_state.groups,
            self.auto_select_strategy
        )

        # Build final summary message
        total_dupes = sum(len(g.images) - 1 for g in self.scan_state.groups)
        exact_count = sum(len(g.images) - 1 for g in exact_groups)
        perceptual_count = sum(len(g.images) - 1 for g in perceptual_groups)

        elapsed_total = time.time() - self.scan_state.progress_details['start_time']
        self.scan_state.progress_details['elapsed_seconds'] = elapsed_total
        elapsed_str = formatters.format_time_estimate(elapsed_total)

        summary_parts = [f'Found {formatters.format_number(total_dupes)} duplicates in {formatters.format_number(len(self.scan_state.groups))} groups']

        if exact_count > 0 and perceptual_count > 0:
            summary_parts.append(f'({formatters.format_number(exact_count)} exact, {formatters.format_number(perceptual_count)} similar)')
        elif exact_count > 0:
            summary_parts.append('(exact matches)')
        elif perceptual_count > 0:
            summary_parts.append('(visually similar)')

        summary_parts.append(f'• Completed in {elapsed_str}')

        error_count = len(self.scan_state.error_images) if self.scan_state.error_images else 0
        if error_count > 0:
            summary_parts.append(f'• {formatters.format_number(error_count)} files had errors')

        if self.auto_disabled_perceptual:
            summary_parts.append('• ⚠️ Perceptual matching was skipped for large collection')

        self.scan_state.message = ' '.join(summary_parts)
        self.scan_state.last_updated = datetime.now().isoformat()

        self.save_callback()


__all__ = ['ScanOrchestrator', 'ProgressTracker', 'PERCEPTUAL_AUTO_DISABLE_THRESHOLD']
