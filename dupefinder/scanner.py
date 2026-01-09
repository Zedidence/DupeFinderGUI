"""
Image scanning and duplicate detection logic.

This module contains all the core functionality for:
- Finding image files in directories
- Analyzing image metadata
- Computing file and perceptual hashes
- Detecting exact and perceptual duplicates
"""

import hashlib
import os
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable
import logging

from .config import (
    IMAGE_EXTENSIONS,
    FORMAT_QUALITY_RANK,
    MODE_BIT_DEPTHS,
    DEFAULT_WORKERS,
)
from .models import ImageInfo, DuplicateGroup
from .database import get_cache, CacheStats

# Check for required dependencies
try:
    from PIL import Image
    import imagehash
except ImportError:
    raise ImportError(
        "Required packages not found!\n"
        "Install with: pip install Pillow imagehash"
    )

# Optional: tqdm for progress bars
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None


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
    images = []
    
    for ext in IMAGE_EXTENSIONS:
        if recursive:
            images.extend(root.rglob(f'*{ext}'))
            images.extend(root.rglob(f'*{ext.upper()}'))
        else:
            images.extend(root.glob(f'*{ext}'))
            images.extend(root.glob(f'*{ext.upper()}'))
    
    # Remove duplicates (case sensitivity issues on some filesystems)
    seen = set()
    unique = []
    for img in images:
        resolved = str(img.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    
    return unique


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
    except Exception:
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
            # Convert to RGB if necessary (handles transparency, etc.)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            phash = imagehash.phash(img, hash_size=hash_size)
            return str(phash)
    except Exception:
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


def analyze_image(filepath: str | Path, calculate_phash: bool = True) -> ImageInfo:
    """
    Analyze an image file and extract metadata.
    
    Args:
        filepath: Path to the image file
        calculate_phash: Whether to compute perceptual hash
        
    Returns:
        ImageInfo object with all extracted metadata
    """
    filepath = str(filepath)
    info = ImageInfo(path=filepath)
    
    try:
        # File size
        info.file_size = os.path.getsize(filepath)
        
        # Calculate file hash
        info.file_hash = calculate_file_hash(filepath)
        
        # Open image and extract metadata
        with Image.open(filepath) as img:
            info.width = img.width
            info.height = img.height
            info.pixel_count = img.width * img.height
            info.format = img.format or ""
            
            # Bit depth
            info.bit_depth = MODE_BIT_DEPTHS.get(img.mode, 24)
            
            # Perceptual hash
            if calculate_phash:
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                phash = imagehash.phash(img, hash_size=16)
                info.perceptual_hash = str(phash)
        
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
) -> tuple[list[ImageInfo], CacheStats]:
    """
    Analyze multiple images in parallel with optional caching.
    
    Args:
        filepaths: List of image paths to analyze
        max_workers: Number of parallel workers
        progress_callback: Optional callback(current, total) for progress updates
        show_progress: Whether to show tqdm progress bar
        logger: Optional logger for status messages
        use_cache: Whether to use database cache for results
        
    Returns:
        Tuple of (list of ImageInfo objects, CacheStats)
    """
    results = []
    total = len(filepaths)
    stats = CacheStats(total_files=total)
    
    # Check cache first if enabled
    cached_results = {}
    files_to_analyze = filepaths
    
    if use_cache:
        cache = get_cache()
        cached_results = cache.get_batch(filepaths)
        
        # Separate cache hits from misses
        files_to_analyze = []
        for fp in filepaths:
            if cached_results.get(fp) is not None:
                results.append(cached_results[fp])
                stats.cache_hits += 1
            else:
                files_to_analyze.append(fp)
                stats.cache_misses += 1
        
        if logger and stats.cache_hits > 0:
            logger.info(f"Cache: {stats.cache_hits} hits, {stats.cache_misses} misses "
                       f"({stats.hit_rate:.1f}% hit rate)")
    
    # Analyze uncached files
    if files_to_analyze:
        newly_analyzed = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(analyze_image, path): path 
                for path in files_to_analyze
            }
            
            # Use tqdm if available and requested
            if HAS_TQDM and show_progress:
                iterator = tqdm(
                    as_completed(future_to_path),
                    total=len(files_to_analyze),
                    desc="Analyzing images",
                    unit="img",
                    ncols=80,
                    initial=stats.cache_hits,
                )
            else:
                iterator = as_completed(future_to_path)
            
            completed = stats.cache_hits
            for future in iterator:
                completed += 1
                try:
                    info = future.result()
                    results.append(info)
                    newly_analyzed.append(info)
                    
                    # Progress callback
                    if progress_callback:
                        progress_callback(completed, total)
                    
                    # Fallback progress for non-tqdm
                    if not HAS_TQDM and logger and completed % 100 == 0:
                        logger.info(f"Analyzed {completed}/{total} images...")
                        
                except Exception as e:
                    path = future_to_path[future]
                    if logger:
                        logger.warning(f"Failed to analyze {path}: {e}")
        
        # Cache newly analyzed results
        if use_cache and newly_analyzed:
            cache.put_batch(newly_analyzed)
    
    return results, stats


def analyze_images_parallel_legacy(
    filepaths: list[str],
    max_workers: int = DEFAULT_WORKERS,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
    logger: Optional[logging.Logger] = None,
) -> list[ImageInfo]:
    """
    Legacy version without cache support for backward compatibility.
    
    Args:
        filepaths: List of image paths to analyze
        max_workers: Number of parallel workers
        progress_callback: Optional callback(current, total) for progress updates
        show_progress: Whether to show tqdm progress bar
        logger: Optional logger for status messages
        
    Returns:
        List of ImageInfo objects
    """
    results, _ = analyze_images_parallel(
        filepaths=filepaths,
        max_workers=max_workers,
        progress_callback=progress_callback,
        show_progress=show_progress,
        logger=logger,
        use_cache=False,
    )
    return results


def find_exact_duplicates(images: list[ImageInfo]) -> list[DuplicateGroup]:
    """
    Find exact duplicates using file hash.
    
    Args:
        images: List of ImageInfo objects to check
        
    Returns:
        List of DuplicateGroup objects for groups with 2+ identical files
    """
    hash_groups = defaultdict(list)
    
    for img in images:
        if img.file_hash and not img.error:
            hash_groups[img.file_hash].append(img)
    
    # Filter to only groups with duplicates
    duplicate_groups = []
    group_id = 1
    for file_hash, group_images in hash_groups.items():
        if len(group_images) > 1:
            group = DuplicateGroup(
                id=group_id,
                images=group_images,
                match_type="exact"
            )
            duplicate_groups.append(group)
            group_id += 1
    
    return duplicate_groups


def find_perceptual_duplicates(
    images: list[ImageInfo],
    threshold: int = 10,
    exclude_hashes: Optional[set[str]] = None,
    start_id: int = 1,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    show_progress: bool = True,
) -> list[DuplicateGroup]:
    """
    Find perceptually similar images using pHash.
    
    Uses Union-Find algorithm for efficient grouping.
    
    Args:
        images: List of ImageInfo objects to check
        threshold: Maximum hamming distance to consider as duplicate (0-64)
                   Lower = stricter matching. Recommended: 5-15
        exclude_hashes: Set of file hashes to skip (e.g., exact duplicates)
        start_id: Starting ID for duplicate groups
        progress_callback: Optional callback(current, total) for progress updates
        show_progress: Whether to show tqdm progress bar
        
    Returns:
        List of DuplicateGroup objects
    """
    # Filter candidates
    candidates = []
    for img in images:
        if not img.perceptual_hash or img.error:
            continue
        if exclude_hashes and img.file_hash in exclude_hashes:
            continue
        candidates.append(img)
    
    if len(candidates) < 2:
        return []
    
    # Parse perceptual hashes
    parsed_hashes = []
    for img in candidates:
        try:
            parsed_hashes.append(imagehash.hex_to_hash(img.perceptual_hash))
        except Exception:
            parsed_hashes.append(None)
    
    # Union-Find for efficient grouping
    parent = list(range(len(candidates)))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])  # Path compression
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # Compare all pairs (O(n²) but necessary for perceptual matching)
    total_comparisons = (len(candidates) * (len(candidates) - 1)) // 2
    
    if HAS_TQDM and show_progress and total_comparisons > 1000:
        pbar = tqdm(total=total_comparisons, desc="Comparing images", unit="cmp", ncols=80)
    else:
        pbar = None
    
    comparison_count = 0
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if parsed_hashes[i] is not None and parsed_hashes[j] is not None:
                # Hamming distance
                distance = parsed_hashes[i] - parsed_hashes[j]
                
                if distance <= threshold:
                    union(i, j)
            
            comparison_count += 1
            if pbar and comparison_count % 1000 == 0:
                pbar.update(1000)
            if progress_callback and comparison_count % 10000 == 0:
                progress_callback(comparison_count, total_comparisons)
    
    if pbar:
        pbar.close()
    
    # Collect groups
    groups = defaultdict(list)
    for i, img in enumerate(candidates):
        root = find(i)
        groups[root].append(img)
    
    # Filter to only duplicates and create DuplicateGroup objects
    duplicate_groups = []
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