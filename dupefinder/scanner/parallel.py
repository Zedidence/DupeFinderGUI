"""
Parallel processing module for the scanner package.

Provides parallel image analysis with caching, progress tracking, and callback support.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable, Any

from ..config import DEFAULT_WORKERS
from ..database import get_cache, CacheStats
from ..models import ImageInfo
from .analysis import analyze_image
from .dependencies import HAS_TQDM, _tqdm_class


def analyze_images_parallel(
    filepaths: list[str],
    max_workers: int = DEFAULT_WORKERS,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
    logger: Optional[logging.Logger] = None,
    use_cache: bool = True,
    calculate_hash: bool = True,
) -> tuple[list[ImageInfo], CacheStats]:
    """
    Analyze multiple images in parallel with optional caching.

    Args:
        filepaths: List of image paths to analyze
        max_workers: Number of parallel workers
        progress_callback: Optional callback(current, total) for progress updates
        show_progress: Whether to show tqdm progress bar
        logger: Optional logger for status messages
        use_cache: Whether to use SQLite caching
        calculate_hash: Whether to compute file hash (for exact duplicate detection)

    Returns:
        Tuple of (list of ImageInfo objects, CacheStats)
    """
    if not filepaths:
        return [], CacheStats()

    results: list[ImageInfo] = []
    stats = CacheStats(total_files=len(filepaths))

    # Try to get cached results first
    cache = get_cache() if use_cache else None
    to_analyze: list[str] = []

    if cache:
        cached_results = cache.get_batch(filepaths)
        for filepath in filepaths:
            cached = cached_results.get(filepath)
            if cached is not None:
                results.append(cached)
                stats.cache_hits += 1
            else:
                to_analyze.append(filepath)
                stats.cache_misses += 1

        if logger and stats.cache_hits > 0:
            logger.info(
                f"Cache: {stats.cache_hits:,} hits, {stats.cache_misses:,} misses "
                f"({stats.hit_rate:.1f}% hit rate)"
            )
    else:
        to_analyze = list(filepaths)
        stats.cache_misses = len(filepaths)

    # Analyze uncached files
    if to_analyze:
        pbar: Optional[Any] = None
        if HAS_TQDM and show_progress and _tqdm_class is not None:
            pbar = _tqdm_class(
                total=len(to_analyze),
                desc="Analyzing images",
                unit="img",
                ncols=80,
            )

        newly_analyzed: list[ImageInfo] = []

        # Batch progress callbacks to reduce overhead (every 1000 files or 1 second)
        last_callback_time = time.time()
        callback_batch_size = 1000
        callback_interval = 1.0  # seconds

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(analyze_image, path, True, calculate_hash): path
                for path in to_analyze
            }

            for i, future in enumerate(as_completed(futures)):
                try:
                    info = future.result()
                    results.append(info)
                    newly_analyzed.append(info)
                except Exception as e:
                    filepath = futures[future]
                    info = ImageInfo(path=filepath, error=str(e))
                    results.append(info)
                    newly_analyzed.append(info)

                if pbar is not None:
                    pbar.update(1)

                # Batch progress callbacks to reduce overhead
                if progress_callback:
                    current_time = time.time()
                    should_callback = (
                        (i + 1) % callback_batch_size == 0 or
                        current_time - last_callback_time >= callback_interval or
                        i == len(to_analyze) - 1  # Always callback on last item
                    )
                    if should_callback:
                        progress_callback(stats.cache_hits + i + 1, len(filepaths))
                        last_callback_time = current_time

        if pbar is not None:
            pbar.close()

        # Cache newly analyzed results
        if cache and newly_analyzed:
            cache.put_batch(newly_analyzed)

    return results, stats


__all__ = ['analyze_images_parallel']
