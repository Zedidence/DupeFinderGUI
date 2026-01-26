"""
Image scanning and duplicate detection logic.

This module contains all the core functionality for:
- Finding image files in directories
- Analyzing image metadata
- Computing file and perceptual hashes
- Detecting exact and perceptual duplicates
"""

from __future__ import annotations

import hashlib
import os
import time
import warnings
import logging
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable, Any

from .config import (
    IMAGE_EXTENSIONS,
    FORMAT_QUALITY_RANK,
    MODE_BIT_DEPTHS,
    DEFAULT_WORKERS,
    LSH_AUTO_THRESHOLD,
)
from .models import ImageInfo, DuplicateGroup
from .database import get_cache, CacheStats
from .lsh import HammingLSH, LSHStats, calculate_optimal_params, estimate_comparison_reduction

# Module-level logger for hash failures and analysis issues
_logger = logging.getLogger(__name__)

# Check for required dependencies
try:
    from PIL import Image
    import imagehash
except ImportError:
    raise ImportError(
        "Required packages not found!\n"
        "Install with: pip install Pillow imagehash"
    )

# Register HEIC/HEIF support via pillow-heif
# This must be done before opening any HEIC files
HAS_HEIF_SUPPORT = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HAS_HEIF_SUPPORT = True
    _logger.debug("HEIC/HEIF support enabled via pillow-heif")
except ImportError:
    _logger.warning(
        "pillow-heif not installed - HEIC/HEIF files will not be processed. "
        "Install with: pip install pillow-heif"
    )

# Increase PIL's decompression bomb limit for large images
# Default is ~89MP (178 million pixels), we increase to 500MP for photo management
# This handles legitimate large images like high-resolution scans and panoramas
Image.MAX_IMAGE_PIXELS = 500_000_000  # 500 megapixels

# Suppress specific PIL warnings that we handle gracefully
# - DecompressionBombWarning: We've increased the limit appropriately
# - Palette transparency warnings: We convert to RGB anyway
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

# Optional: tqdm for progress bars
# Store as Optional[Any] to satisfy type checkers when tqdm is not installed
HAS_TQDM = False
_tqdm_class: Optional[Any] = None

try:
    from tqdm import tqdm as _tqdm_import
    HAS_TQDM = True
    _tqdm_class = _tqdm_import
except ImportError:
    pass


def find_image_files(root_path: str | Path, recursive: bool = True) -> list[str]:
    """
    Find all image files in the given directory.

    Args:
        root_path: Directory to scan
        recursive: If True, scan subdirectories

    Returns:
        List of absolute paths to image files
    """
    root = Path(root_path)

    # Filter out HEIC extensions if support not available
    extensions_to_scan = IMAGE_EXTENSIONS
    if not HAS_HEIF_SUPPORT:
        extensions_to_scan = {ext for ext in IMAGE_EXTENSIONS if ext not in {'.heic', '.heif'}}

    # Single traversal with case-insensitive extension matching
    # This is much faster than calling rglob once per extension
    images = []
    seen = set()

    iterator = root.rglob('*') if recursive else root.glob('*')

    for filepath in iterator:
        if filepath.is_file():
            ext_lower = filepath.suffix.lower()
            if ext_lower in extensions_to_scan:
                resolved = str(filepath.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    images.append(resolved)

    return images


def calculate_file_hash(filepath: str | Path, algorithm: str = 'sha256') -> str:
    """
    Calculate cryptographic hash of a file.

    Args:
        filepath: Path to the file
        algorithm: Hash algorithm to use (default: sha256)

    Returns:
        Hex digest of the file hash, or empty string on error
    """
    hasher = hashlib.new(algorithm)
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        _logger.debug(f"File hash calculation failed for {filepath}: {e}")
        return ""


def calculate_perceptual_hash(filepath: str | Path, hash_size: int = 16) -> Optional[str]:
    """
    Calculate perceptual hash of an image.

    Uses pHash algorithm which is most accurate for photos.

    Args:
        filepath: Path to the image
        hash_size: Size of the hash (default 16, resulting in 256-bit hash)

    Returns:
        String representation of the perceptual hash, or None on error
    """
    try:
        with Image.open(filepath) as img:
            # FIXED #6: Verify image can be loaded before accessing attributes
            img.load()  # Force load to detect truncated/corrupt images early
            
            # Convert to RGB if necessary (handles transparency, etc.)
            if img.mode not in ('RGB', 'L'):
                try:
                    img = img.convert('RGB')
                except Exception as conv_err:
                    # FIXED #4: Log conversion failures instead of silent None
                    _logger.debug(f"Image mode conversion failed for {filepath} (mode={img.mode}): {conv_err}")
                    return None
            
            phash = imagehash.phash(img, hash_size=hash_size)
            return str(phash)
    except Exception as e:
        # FIXED #4: Log perceptual hash failures instead of silently returning None
        _logger.debug(f"Perceptual hash calculation failed for {filepath}: {e}")
        return None


def calculate_quality_score(info: ImageInfo) -> float:
    """
    Calculate a quality score for an image.
    Higher score = better quality.
    
    Factors considered:
    - Resolution (pixel count) - up to 50 points
    - File size (larger often means more detail) - up to 30 points
    - Bit depth - up to 10 points
    - Format quality ranking - up to 20 points
    
    Args:
        info: ImageInfo object with metadata
        
    Returns:
        Quality score (typically 0-110 range)
    """
    score = 0.0
    
    # Resolution score (normalized, max ~50 points for 50MP+)
    if info.pixel_count > 0:
        # Log scale to prevent huge images from dominating
        resolution_score = min(50, (info.pixel_count / 1_000_000) * 2)
        score += resolution_score
    
    # File size score (normalized, max ~30 points)
    if info.file_size > 0:
        size_mb = info.file_size / (1024 * 1024)
        size_score = min(30, size_mb * 3)
        score += size_score
    
    # Bit depth score (max 10 points)
    if info.bit_depth > 0:
        depth_score = min(10, info.bit_depth / 3.2)
        score += depth_score
    
    # Format quality score (max 20 points)
    ext = os.path.splitext(info.path)[1].lower()
    format_rank = FORMAT_QUALITY_RANK.get(ext, 50)
    format_score = format_rank / 5  # Scale to 0-20
    score += format_score
    
    return score


def analyze_image(
    filepath: str | Path,
    calculate_phash: bool = True,
    calculate_hash: bool = True,
) -> ImageInfo:
    """
    Analyze an image file and extract metadata.

    Args:
        filepath: Path to the image file
        calculate_phash: Whether to compute perceptual hash
        calculate_hash: Whether to compute file hash (SHA-256)

    Returns:
        ImageInfo object with all extracted metadata
    """
    filepath = str(filepath)
    info = ImageInfo(path=filepath)

    try:
        # File size - check file exists and is accessible first
        if not os.path.exists(filepath):
            info.error = "File not found"
            return info

        if not os.access(filepath, os.R_OK):
            info.error = "File not readable (permission denied)"
            return info

        info.file_size = os.path.getsize(filepath)

        # Calculate file hash (only if needed for exact duplicate detection)
        if calculate_hash:
            info.file_hash = calculate_file_hash(filepath)
        
        # Check for HEIC without support
        ext = os.path.splitext(filepath)[1].lower()
        if ext in {'.heic', '.heif'} and not HAS_HEIF_SUPPORT:
            info.error = "HEIC/HEIF support not installed (pip install pillow-heif)"
            return info
        
        # Open image and extract metadata
        # FIXED #6: Wrap in try-except to handle corrupt/truncated files
        try:
            with Image.open(filepath) as img:
                # Force load to detect truncated images early
                try:
                    img.load()
                except Exception as load_err:
                    info.error = f"Corrupt or truncated image: {load_err}"
                    return info
                
                # Now safe to access attributes
                info.width = img.width
                info.height = img.height
                info.pixel_count = img.width * img.height
                info.format = img.format or ""
                
                # Bit depth
                info.bit_depth = MODE_BIT_DEPTHS.get(img.mode, 24)
                
                # Perceptual hash
                if calculate_phash:
                    try:
                        if img.mode not in ('RGB', 'L'):
                            img = img.convert('RGB')
                        phash = imagehash.phash(img, hash_size=16)
                        info.perceptual_hash = str(phash)
                    except Exception as phash_err:
                        # FIXED #4: Log but don't fail the whole analysis
                        _logger.debug(f"Perceptual hash failed for {filepath}: {phash_err}")
                        info.perceptual_hash = ""
        
        except Image.UnidentifiedImageError as e:
            info.error = f"Not a valid image file: {e}"
            return info
        except Exception as e:
            info.error = f"Failed to open image: {e}"
            return info
        
        # Calculate quality score
        info.quality_score = calculate_quality_score(info)
        
    except Exception as e:
        info.error = str(e)
    
    return info


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


def find_exact_duplicates(
    images: list[ImageInfo],
    start_id: int = 1,
) -> list[DuplicateGroup]:
    """
    Find exact duplicate images based on file hash.
    
    Args:
        images: List of ImageInfo objects to check
        start_id: Starting ID for duplicate groups
        
    Returns:
        List of DuplicateGroup objects containing exact duplicates
    """
    # Group by file hash
    hash_groups: dict[str, list[ImageInfo]] = defaultdict(list)
    
    for img in images:
        if img.file_hash:
            hash_groups[img.file_hash].append(img)
    
    # Create duplicate groups
    groups = []
    group_id = start_id
    
    for file_hash, group_images in hash_groups.items():
        if len(group_images) > 1:
            group = DuplicateGroup(
                id=group_id,
                images=group_images,
                match_type="exact"
            )
            groups.append(group)
            group_id += 1
    
    return groups


def find_perceptual_duplicates(
    images: list[ImageInfo],
    threshold: int = 10,
    exclude_hashes: Optional[set[str]] = None,
    start_id: int = 1,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
    use_lsh: Optional[bool] = None,
    logger: Optional[logging.Logger] = None,
) -> list[DuplicateGroup]:
    """
    Find perceptually similar images using pHash.
    
    Args:
        images: List of ImageInfo objects to check
        threshold: Maximum Hamming distance for similarity (0-64)
        exclude_hashes: Set of file hashes to skip (e.g., exact duplicates)
        start_id: Starting ID for duplicate groups
        progress_callback: Optional callback(current, total) for progress
        show_progress: Whether to show tqdm progress bar
        use_lsh: Force LSH on/off, or None for auto-select based on collection size
        logger: Optional logger for status messages
        
    Returns:
        List of DuplicateGroup objects containing similar images
    """
    exclude_hashes = exclude_hashes or set()
    
    # Filter to images with perceptual hashes that aren't already exact duplicates
    candidates = [
        img for img in images 
        if img.perceptual_hash and img.file_hash not in exclude_hashes
    ]
    
    if len(candidates) < 2:
        return []
    
    # Auto-select LSH for large collections
    if use_lsh is None:
        use_lsh = len(candidates) >= LSH_AUTO_THRESHOLD
        if use_lsh and logger:
            logger.info(f"Using LSH optimization for {len(candidates):,} images")
    
    if use_lsh:
        return _find_perceptual_duplicates_lsh(
            candidates=candidates,
            threshold=threshold,
            start_id=start_id,
            progress_callback=progress_callback,
            show_progress=show_progress,
            logger=logger,
        )
    else:
        return _find_perceptual_duplicates_bruteforce(
            candidates=candidates,
            threshold=threshold,
            start_id=start_id,
            progress_callback=progress_callback,
            show_progress=show_progress,
        )


def _find_perceptual_duplicates_bruteforce(
    candidates: list[ImageInfo],
    threshold: int = 10,
    start_id: int = 1,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
) -> list[DuplicateGroup]:
    """
    Brute-force O(n^2) perceptual duplicate finding.
    
    Best for small collections (< 5000 images).
    """
    # Parse perceptual hashes
    parsed_hashes = []
    for img in candidates:
        try:
            parsed_hashes.append(imagehash.hex_to_hash(img.perceptual_hash))
        except Exception:
            parsed_hashes.append(None)
    
    # Union-Find for efficient grouping
    parent = list(range(len(candidates)))
    
    def find(x: int) -> int:
        if parent[x] != x:
            parent[x] = find(parent[x])  # Path compression
        return parent[x]
    
    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # Compare all pairs O(n^2)
    total_comparisons = (len(candidates) * (len(candidates) - 1)) // 2
    
    pbar: Optional[Any] = None
    if HAS_TQDM and show_progress and total_comparisons > 1000 and _tqdm_class is not None:
        pbar = _tqdm_class(total=total_comparisons, desc="Comparing images", unit="cmp", ncols=80)
    
    comparison_count = 0
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if parsed_hashes[i] is not None and parsed_hashes[j] is not None:
                # Hamming distance
                distance = parsed_hashes[i] - parsed_hashes[j]
                
                if distance <= threshold:
                    union(i, j)
            
            comparison_count += 1
            if pbar is not None and comparison_count % 1000 == 0:
                pbar.update(1000)
            if progress_callback and comparison_count % 10000 == 0:
                progress_callback(comparison_count, total_comparisons)
    
    if pbar is not None:
        pbar.close()
    
    # Collect groups
    return _collect_duplicate_groups(candidates, parent, start_id)


def _find_perceptual_duplicates_lsh(
    candidates: list[ImageInfo],
    threshold: int = 10,
    start_id: int = 1,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
    logger: Optional[logging.Logger] = None,
) -> list[DuplicateGroup]:
    """
    LSH-accelerated perceptual duplicate finding.
    
    Uses Locality-Sensitive Hashing to reduce comparisons from O(n^2) to O(n).
    Best for large collections (>= 5000 images).
    """
    n = len(candidates)
    
    # Parse perceptual hashes
    parsed_hashes = []
    for img in candidates:
        try:
            parsed_hashes.append(imagehash.hex_to_hash(img.perceptual_hash))
        except Exception:
            parsed_hashes.append(None)
    
    # Calculate optimal LSH parameters based on collection size
    num_tables, bits_per_table = calculate_optimal_params(n, threshold)
    
    if logger:
        estimate = estimate_comparison_reduction(n, num_tables, bits_per_table)
        logger.info(
            f"LSH params: {num_tables} tables, {bits_per_table} bits/table "
            f"(~{estimate['speedup_factor']:.0f}x speedup expected)"
        )
    
    # Build LSH index
    pbar_build: Optional[Any] = None
    if HAS_TQDM and show_progress and _tqdm_class is not None:
        pbar_build = _tqdm_class(total=n, desc="Building LSH index", unit="img", ncols=80)
    
    lsh = HammingLSH(
        num_tables=num_tables,
        bits_per_table=bits_per_table,
        hash_bits=256,  # hash_size=16 produces 256-bit hashes
    )
    
    for idx, phash in enumerate(parsed_hashes):
        if phash is not None:
            lsh.add(idx, phash)
        if pbar_build is not None:
            pbar_build.update(1)
    
    if pbar_build is not None:
        pbar_build.close()

    # Union-Find for grouping (defined early so we can use it for deduplication)
    parent = list(range(len(candidates)))
    rank = [0] * len(candidates)  # Union by rank for better performance

    def find(x: int) -> int:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            # Union by rank
            if rank[px] < rank[py]:
                parent[px] = py
            elif rank[px] > rank[py]:
                parent[py] = px
            else:
                parent[py] = px
                rank[px] += 1

    # Estimate candidate pairs for progress reporting (without materializing)
    estimated_candidates = lsh.estimate_candidate_pairs()
    brute_force_comparisons = (n * (n - 1)) // 2

    if logger:
        estimated_reduction = 1 - (estimated_candidates / max(1, brute_force_comparisons))
        logger.info(
            f"LSH estimated comparisons: {brute_force_comparisons:,} -> ~{estimated_candidates:,} "
            f"(~{estimated_reduction:.1%} reduction)"
        )

    # Compare only LSH candidates using memory-efficient iterator
    # The iterator may yield duplicate pairs across tables, but we skip pairs
    # that are already in the same Union-Find group for efficiency
    pbar: Optional[Any] = None
    if HAS_TQDM and show_progress and estimated_candidates > 1000 and _tqdm_class is not None:
        pbar = _tqdm_class(total=estimated_candidates, desc="Comparing candidates", unit="cmp", ncols=80)

    comparison_count = 0
    actual_comparisons = 0
    matches_found = 0

    for i, j in lsh.iter_candidate_pairs():
        comparison_count += 1

        # Skip if already in the same group (handles duplicates across tables)
        if find(i) == find(j):
            if pbar is not None and comparison_count % 1000 == 0:
                pbar.update(1000)
            continue

        if parsed_hashes[i] is not None and parsed_hashes[j] is not None:
            distance = parsed_hashes[i] - parsed_hashes[j]
            actual_comparisons += 1

            if distance <= threshold:
                union(i, j)
                matches_found += 1

        if pbar is not None and comparison_count % 1000 == 0:
            pbar.update(1000)
        if progress_callback and comparison_count % 10000 == 0:
            # Report progress relative to candidate pairs, not brute force
            progress_callback(comparison_count, estimated_candidates)
    
    if pbar is not None:
        # Update remaining
        remaining = comparison_count % 1000
        if remaining > 0:
            pbar.update(remaining)
        pbar.close()

    if logger:
        logger.info(
            f"Found {matches_found:,} matching pairs "
            f"({actual_comparisons:,} actual comparisons, {comparison_count - actual_comparisons:,} skipped as already grouped)"
        )
    
    # Collect groups
    return _collect_duplicate_groups(candidates, parent, start_id)


def _collect_duplicate_groups(
    candidates: list[ImageInfo],
    parent: list[int],
    start_id: int,
) -> list[DuplicateGroup]:
    """
    Collect duplicate groups from Union-Find parent array.
    
    Helper function shared by brute-force and LSH implementations.
    """
    # Find with path compression
    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        # Path compression
        while parent[x] != root:
            next_x = parent[x]
            parent[x] = root
            x = next_x
        return root
    
    # Collect groups
    groups: dict[int, list[ImageInfo]] = defaultdict(list)
    for i, img in enumerate(candidates):
        root = find(i)
        groups[root].append(img)
    
    # Filter to only duplicates and create DuplicateGroup objects
    duplicate_groups: list[DuplicateGroup] = []
    group_id = start_id
    for group_images in groups.values():
        if len(group_images) > 1:
            group = DuplicateGroup(
                id=group_id,
                images=group_images,
                match_type="perceptual"
            )
            duplicate_groups.append(group)
            group_id += 1
    
    return duplicate_groups


def has_heif_support() -> bool:
    """Check if HEIC/HEIF support is available."""
    return HAS_HEIF_SUPPORT