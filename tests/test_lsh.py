"""
Unit tests for LSH (Locality-Sensitive Hashing) module.
"""

import pytest
import imagehash
from PIL import Image
from dupefinder.lsh import HammingLSH, calculate_optimal_params, estimate_comparison_reduction


class TestHammingLSH:
    """Test HammingLSH class."""

    def test_initialization(self):
        """Test LSH initialization."""
        lsh = HammingLSH(num_tables=10, bits_per_table=16, hash_bits=256)
        assert lsh.num_tables == 10
        assert lsh.bits_per_table == 16
        assert lsh.size == 0

    def test_add_hash(self):
        """Test adding a hash to the index."""
        lsh = HammingLSH(num_tables=5, bits_per_table=8, hash_bits=64)

        # Create a simple hash
        img = Image.new('RGB', (100, 100), color='red')
        phash = imagehash.phash(img, hash_size=8)  # 64-bit hash

        lsh.add(0, phash)
        assert lsh.size == 1

    def test_get_candidates_same_hash(self):
        """Test that identical hashes are found as candidates."""
        lsh = HammingLSH(num_tables=10, bits_per_table=12, hash_bits=256)

        # Create identical images
        img1 = Image.new('RGB', (100, 100), color='blue')
        img2 = Image.new('RGB', (100, 100), color='blue')

        phash1 = imagehash.phash(img1, hash_size=16)
        phash2 = imagehash.phash(img2, hash_size=16)

        lsh.add(0, phash1)
        lsh.add(1, phash2)

        # Querying hash 0 should find hash 1
        candidates = lsh.get_candidates(0, phash1)
        assert 1 in candidates
        assert 0 not in candidates  # Should not include self

    def test_get_candidates_different_hashes(self):
        """Test that very different hashes may not collide."""
        lsh = HammingLSH(num_tables=5, bits_per_table=20, hash_bits=256)

        # Create very different images
        img1 = Image.new('RGB', (100, 100), color='black')
        img2 = Image.new('RGB', (100, 100), color='white')

        phash1 = imagehash.phash(img1, hash_size=16)
        phash2 = imagehash.phash(img2, hash_size=16)

        lsh.add(0, phash1)
        lsh.add(1, phash2)

        candidates = lsh.get_candidates(0, phash1)
        # May or may not find it depending on parameters, but shouldn't crash
        assert isinstance(candidates, set)

    def test_get_all_candidate_pairs(self):
        """Test getting all candidate pairs."""
        lsh = HammingLSH(num_tables=10, bits_per_table=12, hash_bits=256)

        # Create similar images
        img = Image.new('RGB', (100, 100), color='red')
        phash = imagehash.phash(img, hash_size=16)

        lsh.add(0, phash)
        lsh.add(1, phash)
        lsh.add(2, phash)

        pairs = lsh.get_all_candidate_pairs()

        # Should find pairs between similar hashes
        assert isinstance(pairs, set)
        assert len(pairs) > 0
        # Pairs should be tuples of (smaller_id, larger_id)
        for p in pairs:
            assert p[0] < p[1]

    def test_clear(self):
        """Test clearing the index."""
        lsh = HammingLSH(num_tables=5, bits_per_table=8, hash_bits=64)

        img = Image.new('RGB', (100, 100), color='green')
        phash = imagehash.phash(img, hash_size=8)

        lsh.add(0, phash)
        assert lsh.size == 1

        lsh.clear()
        assert lsh.size == 0

    def test_get_stats(self):
        """Test getting index statistics."""
        lsh = HammingLSH(num_tables=5, bits_per_table=8, hash_bits=64)

        img = Image.new('RGB', (100, 100), color='yellow')
        phash = imagehash.phash(img, hash_size=8)

        lsh.add(0, phash)
        lsh.add(1, phash)

        stats = lsh.get_stats()
        assert stats['num_tables'] == 5
        assert stats['bits_per_table'] == 8
        assert stats['total_items'] == 2

    def test_none_hash_handling(self):
        """Test that None hashes are handled gracefully."""
        lsh = HammingLSH(num_tables=5, bits_per_table=8, hash_bits=64)

        lsh.add(0, None)
        assert lsh.size == 0  # Should not add

        candidates = lsh.get_candidates(0, None)
        assert len(candidates) == 0  # Should return empty set


class TestCalculateOptimalParams:
    """Test calculate_optimal_params function."""

    def test_small_collection(self):
        """Test parameters for small collection."""
        tables, bits = calculate_optimal_params(5000, threshold=10)
        assert isinstance(tables, int)
        assert isinstance(bits, int)
        assert tables > 0
        assert bits > 0

    def test_medium_collection(self):
        """Test parameters for medium collection."""
        tables, bits = calculate_optimal_params(30000, threshold=10)
        assert isinstance(tables, int)
        assert isinstance(bits, int)

    def test_large_collection(self):
        """Test parameters for large collection."""
        tables, bits = calculate_optimal_params(200000, threshold=10)
        assert isinstance(tables, int)
        assert isinstance(bits, int)

    def test_very_large_collection(self):
        """Test parameters for very large collection."""
        tables, bits = calculate_optimal_params(500000, threshold=10)
        assert isinstance(tables, int)
        assert isinstance(bits, int)
        # Larger collections should get more tables for better recall
        tables_small, _ = calculate_optimal_params(5000, threshold=10)
        assert tables > tables_small


class TestEstimateComparisonReduction:
    """Test estimate_comparison_reduction function."""

    def test_basic_estimation(self):
        """Test basic comparison estimation."""
        result = estimate_comparison_reduction(10000, num_tables=20, bits_per_table=16)

        assert 'brute_force_comparisons' in result
        assert 'estimated_lsh_comparisons' in result
        assert 'estimated_reduction' in result
        assert 'speedup_factor' in result

        # LSH should reduce comparisons significantly
        assert result['estimated_lsh_comparisons'] < result['brute_force_comparisons']
        assert result['speedup_factor'] > 1
        assert 0 <= result['estimated_reduction'] <= 1

    def test_larger_collection(self):
        """Test that larger collections see bigger speedups."""
        result_small = estimate_comparison_reduction(1000, num_tables=20, bits_per_table=16)
        result_large = estimate_comparison_reduction(100000, num_tables=20, bits_per_table=16)

        # Larger collection should have higher speedup factor
        assert result_large['speedup_factor'] > result_small['speedup_factor']
