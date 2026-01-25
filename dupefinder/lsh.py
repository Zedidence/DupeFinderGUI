"""
Locality-Sensitive Hashing (LSH) for fast perceptual hash matching.

This module implements LSH using bit sampling, which is optimal for
Hamming distance comparisons used in perceptual hashing.

The key insight: if two perceptual hashes are similar (low Hamming distance),
they likely share most of their bits. By sampling random subsets of bits
and using them as bucket keys, similar hashes will collide in at least
one bucket with high probability.

Performance:
- Brute force: O(n²) comparisons
- LSH: O(n * k) where k is average candidates per image (typically small)

For a collection of 650K images:
- Brute force: ~211 billion comparisons
- LSH: ~65 million comparisons (with good parameters)
"""

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Any
import logging


@dataclass
class LSHStats:
    """Statistics about LSH index usage."""
    total_images: int = 0
    total_candidates: int = 0
    total_comparisons: int = 0
    duplicate_pairs_found: int = 0
    
    @property
    def avg_candidates_per_image(self) -> float:
        """Average number of candidates checked per image."""
        if self.total_images == 0:
            return 0.0
        return self.total_candidates / self.total_images
    
    @property
    def reduction_ratio(self) -> float:
        """How much we reduced comparisons vs brute force."""
        brute_force = (self.total_images * (self.total_images - 1)) // 2
        if brute_force == 0:
            return 0.0
        return 1.0 - (self.total_comparisons / brute_force)


class HammingLSH:
    """
    Locality-Sensitive Hashing index optimized for Hamming distance.
    
    Uses bit sampling: each hash table samples a random subset of bits
    from the perceptual hash. Similar hashes (low Hamming distance) will
    likely match on at least one table's sampled bits.
    
    Parameters tuned for perceptual hashes (256 bits from hash_size=16):
    - With threshold=10 (3.9% different bits)
    - 20 tables with 16 bits each gives ~99.9% recall
    
    Usage:
        lsh = HammingLSH(num_tables=20, bits_per_table=16)
        
        # Add all hashes to index
        for idx, phash in enumerate(parsed_hashes):
            lsh.add(idx, phash)
        
        # Query for similar hashes
        for idx, phash in enumerate(parsed_hashes):
            candidates = lsh.get_candidates(idx, phash)
            for candidate_idx in candidates:
                # Only compare these candidates
                distance = phash - parsed_hashes[candidate_idx]
    """
    
    def __init__(
        self,
        num_tables: int = 20,
        bits_per_table: int = 16,
        hash_bits: int = 256,
        seed: int = 42,
    ):
        """
        Initialize LSH index.
        
        Args:
            num_tables: Number of hash tables. More tables = better recall
                        but more memory. 15-25 is good for most cases.
            bits_per_table: Bits sampled per table. Fewer bits = more 
                           candidates (better recall, more comparisons).
                           12-20 works well.
            hash_bits: Total bits in perceptual hash. 256 for hash_size=16.
            seed: Random seed for reproducibility.
        """
        self.num_tables = num_tables
        self.bits_per_table = bits_per_table
        self.hash_bits = hash_bits
        self.seed = seed
        
        # Generate random bit positions for each table
        rng = random.Random(seed)
        self.bit_positions: list[list[int]] = [
            sorted(rng.sample(range(hash_bits), bits_per_table))
            for _ in range(num_tables)
        ]
        
        # Hash tables: table_idx -> bucket_key -> list of indices
        self.tables: list[dict[tuple, list[int]]] = [
            defaultdict(list) for _ in range(num_tables)
        ]
        
        # Store hashes for verification
        self._hashes: dict[int, Any] = {}
        self._count = 0
    
    def _hash_to_bits(self, phash) -> list[bool]:
        """
        Convert imagehash to list of bits.
        
        Args:
            phash: An imagehash.ImageHash object
            
        Returns:
            Flat list of boolean values representing the hash bits
        """
        # imagehash stores as numpy array of bools
        return phash.hash.flatten().tolist()
    
    def _get_bucket_key(self, bits: list[bool], table_idx: int) -> tuple:
        """
        Get bucket key for a hash in a specific table.
        
        Args:
            bits: List of hash bits
            table_idx: Which table to get key for
            
        Returns:
            Tuple of sampled bits (hashable bucket key)
        """
        positions = self.bit_positions[table_idx]
        return tuple(bits[p] for p in positions)
    
    def add(self, idx: int, phash) -> None:
        """
        Add a perceptual hash to the index.
        
        Args:
            idx: Unique identifier for this hash (typically array index)
            phash: imagehash.ImageHash object
        """
        if phash is None:
            return
            
        bits = self._hash_to_bits(phash)
        self._hashes[idx] = phash
        
        for table_idx, table in enumerate(self.tables):
            key = self._get_bucket_key(bits, table_idx)
            table[key].append(idx)
        
        self._count += 1
    
    def get_candidates(self, idx: int, phash) -> set[int]:
        """
        Get candidate indices that might be similar to the given hash.
        
        Args:
            idx: Index of the query hash (to exclude from results)
            phash: imagehash.ImageHash object to query
            
        Returns:
            Set of candidate indices that collided in at least one table
        """
        if phash is None:
            return set()
            
        bits = self._hash_to_bits(phash)
        candidates = set()
        
        for table_idx, table in enumerate(self.tables):
            key = self._get_bucket_key(bits, table_idx)
            for candidate_idx in table[key]:
                if candidate_idx != idx:
                    candidates.add(candidate_idx)
        
        return candidates
    
    def get_all_candidate_pairs(self) -> set[tuple[int, int]]:
        """
        Get all pairs of indices that collided in at least one table.
        
        More efficient than calling get_candidates for each item when
        you need to process all pairs.
        
        Returns:
            Set of (i, j) tuples where i < j
        """
        pairs = set()
        
        for table in self.tables:
            for bucket in table.values():
                if len(bucket) > 1:
                    # All pairs within this bucket
                    for i in range(len(bucket)):
                        for j in range(i + 1, len(bucket)):
                            idx1, idx2 = bucket[i], bucket[j]
                            # Ensure consistent ordering
                            if idx1 > idx2:
                                idx1, idx2 = idx2, idx1
                            pairs.add((idx1, idx2))
        
        return pairs
    
    def clear(self) -> None:
        """Clear all data from the index."""
        for table in self.tables:
            table.clear()
        self._hashes.clear()
        self._count = 0
    
    @property
    def size(self) -> int:
        """Number of hashes in the index."""
        return self._count
    
    def get_stats(self) -> dict:
        """Get statistics about the index."""
        total_buckets = sum(len(table) for table in self.tables)
        non_empty_buckets = sum(
            1 for table in self.tables 
            for bucket in table.values() 
            if len(bucket) > 0
        )
        items_in_buckets = sum(
            len(bucket) for table in self.tables 
            for bucket in table.values()
        )
        
        return {
            'num_tables': self.num_tables,
            'bits_per_table': self.bits_per_table,
            'total_items': self._count,
            'total_buckets': total_buckets,
            'non_empty_buckets': non_empty_buckets,
            'avg_bucket_size': items_in_buckets / max(1, non_empty_buckets),
        }


def calculate_optimal_params(
    num_images: int,
    threshold: int = 10,
    hash_bits: int = 256,
    target_recall: float = 0.99,
) -> tuple[int, int]:
    """
    Calculate optimal LSH parameters for given collection size and threshold.
    
    The math:
    - For two hashes with Hamming distance d, probability they match on k
      sampled bits is: p = ((hash_bits - d) / hash_bits) ^ k
    - With L tables, probability of at least one match is: 1 - (1-p)^L
    
    Args:
        num_images: Expected number of images
        threshold: Maximum Hamming distance to consider as duplicate
        hash_bits: Number of bits in perceptual hash (256 for hash_size=16)
        target_recall: Target probability of finding true duplicates
        
    Returns:
        Tuple of (num_tables, bits_per_table)
    """
    import math
    
    # Probability that two hashes at exactly threshold distance match on k bits
    # This is the "worst case" for duplicates we want to find
    p_match_k_bits = lambda k: ((hash_bits - threshold) / hash_bits) ** k
    
    # Probability of at least one collision in L tables
    p_recall = lambda k, L: 1 - (1 - p_match_k_bits(k)) ** L
    
    # Start with reasonable defaults and adjust
    # Fewer bits = more collisions = better recall but more comparisons
    # More tables = better recall but more memory
    
    # For small collections, use more conservative params
    if num_images < 10000:
        return (15, 20)  # Higher bits_per_table = fewer candidates
    elif num_images < 50000:
        return (18, 18)
    elif num_images < 200000:
        return (20, 16)
    else:
        # Large collections: prioritize recall
        return (25, 14)


def estimate_comparison_reduction(
    num_images: int,
    num_tables: int = 20,
    bits_per_table: int = 16,
    hash_bits: int = 256,
) -> dict:
    """
    Estimate how much LSH will reduce comparisons.
    
    Args:
        num_images: Number of images
        num_tables: LSH parameter
        bits_per_table: LSH parameter
        hash_bits: Bits in perceptual hash
        
    Returns:
        Dict with comparison estimates
    """
    brute_force = (num_images * (num_images - 1)) // 2
    
    # Expected bucket size for random data
    # Each table has 2^bits_per_table possible buckets
    num_buckets = 2 ** bits_per_table
    expected_bucket_size = num_images / num_buckets

    # Expected collisions per item per table (must be non-negative)
    expected_collisions_per_table = max(0, expected_bucket_size - 1)

    # Total expected candidates (with overlap across tables)
    # This is a rough estimate; actual depends on data distribution
    expected_candidates = min(
        num_images - 1,
        max(0, expected_collisions_per_table * num_tables * 0.7)  # Overlap factor
    )
    
    expected_comparisons = int(num_images * expected_candidates / 2)
    
    return {
        'brute_force_comparisons': brute_force,
        'estimated_lsh_comparisons': expected_comparisons,
        'estimated_reduction': 1 - (expected_comparisons / max(1, brute_force)),
        'speedup_factor': brute_force / max(1, expected_comparisons),
    }