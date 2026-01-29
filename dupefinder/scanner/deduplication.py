"""
Deduplication module for the scanner package.

Provides algorithms for finding exact and perceptual duplicate images using
Union-Find data structures and optional LSH acceleration.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional, Callable, Any

from ..config import LSH_AUTO_THRESHOLD
from ..lsh import HammingLSH, calculate_optimal_params, estimate_comparison_reduction
from ..models import ImageInfo, DuplicateGroup
from .dependencies import imagehash, HAS_TQDM, _tqdm_class


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


__all__ = [
    'find_exact_duplicates',
    'find_perceptual_duplicates',
]
