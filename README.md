# Duplicate Image Finder

A comprehensive tool for finding duplicate and visually similar images with both a web GUI and command-line interface. Features intelligent caching for fast re-scans, LSH-accelerated perceptual matching for large collections, and optimized handling of 650K+ image libraries.

## Features

- **Multi-stage detection**: Exact hash matching + perceptual hash for visually similar images
- **LSH acceleration**: O(n) perceptual matching instead of O(n²) for large collections
- **45+ image formats supported**: Including RAW formats (CR2, NEF, ARW, DNG, etc.) and modern formats (HEIC/HEIF)
- **Quality-based selection**: Automatically identifies the highest quality version to keep
- **SQLite caching**: Re-scans are 10-100x faster by caching analysis results
- **Large collection support**: Handles 650K+ images efficiently
- **Web GUI**: Easy-to-use browser interface for reviewing and managing duplicates
- **Command-line interface**: For automation and scripting
- **Safe by default**: Dry-run mode, moves to trash instead of permanent deletion
- **Session recovery**: GUI remembers your progress if you close the browser

## Installation

### From source

```bash
# Clone or download the package
cd dupefinder

# Install dependencies
pip install -r requirements.txt

# Or install as a package
pip install -e .
```

### Dependencies

- Python 3.9+
- Pillow
- imagehash
- Flask (for GUI)
- numpy (required by imagehash)
- pillow-heif (for HEIC/HEIF support)
- tqdm (optional, for progress bars)

## Usage

### Web GUI (Recommended for most users)

```bash
# Launch the GUI
python -m dupefinder

# Or explicitly
python -m dupefinder gui
```

This opens a browser at `http://localhost:5000` where you can:
1. Enter a directory to scan
2. Configure similarity threshold
3. Review duplicate groups with image previews
4. Select which images to keep
5. Move duplicates to a trash folder
6. Manage the analysis cache

### Command Line Interface

```bash
# Basic scan (report only, no changes)
python -m dupefinder cli /path/to/photos

# Move duplicates to a separate folder
python -m dupefinder cli /path/to/photos --action move --trash-dir ./duplicates

# Actually delete duplicates (BE CAREFUL!)
python -m dupefinder cli /path/to/photos --action delete --no-dry-run

# Strict matching only
python -m dupefinder cli /path/to/photos --threshold 5 --exact-only

# Force LSH on or off
python -m dupefinder cli /path/to/photos --lsh      # Force LSH on
python -m dupefinder cli /path/to/photos --no-lsh   # Force brute-force

# Export results to CSV
python -m dupefinder cli /path/to/photos --export results.csv --export-format csv

# Disable caching (analyze everything fresh)
python -m dupefinder cli /path/to/photos --no-cache
```

### CLI Options

| Option | Description |
|--------|-------------|
| `-r, --no-recursive` | Don't scan subdirectories |
| `-t, --threshold N` | Perceptual hash threshold (0-64, lower=stricter). Default: 10 |
| `--exact-only` | Only find exact duplicates |
| `--perceptual-only` | Only find perceptual duplicates |
| `--lsh` | Force LSH acceleration on |
| `--no-lsh` | Force brute-force comparison (disable LSH) |
| `-a, --action ACTION` | Action: report, delete, move, hardlink, symlink |
| `--trash-dir PATH` | Directory for moved duplicates |
| `--no-dry-run` | Actually perform the action |
| `-w, --workers N` | Number of parallel workers. Default: 4 |
| `-e, --export PATH` | Export results to file |
| `--export-format FMT` | Export format: txt or csv |
| `--no-cache` | Disable SQLite caching |
| `-v, --verbose` | Verbose output |

## HEIC/HEIF Support

DupeFinder supports Apple's HEIC/HEIF image formats through the `pillow-heif` library:

```bash
# Install HEIC support
pip install pillow-heif
```

If `pillow-heif` is not installed, HEIC/HEIF files will be skipped with a warning. All other formats will continue to work normally.

**Supported modern formats:**
- HEIC/HEIF (requires pillow-heif)
- WebP
- AVIF
- JPEG XL

## LSH Acceleration

For large collections, perceptual duplicate detection uses Locality-Sensitive Hashing (LSH) to achieve near-linear performance instead of the quadratic brute-force approach.

### How It Works

Traditional perceptual matching compares every pair of images, resulting in O(n²) comparisons. For 650K images, this means **211 billion comparisons** - completely impractical.

LSH uses a clever indexing technique:
1. **Build index**: Sample random bits from each perceptual hash to create bucket keys
2. **Query candidates**: Only images that share at least one bucket are compared
3. **Verify matches**: Check actual Hamming distance only for candidate pairs

This reduces comparisons to approximately O(n), with typical speedups of **20-1000x**.

### Performance Impact

| Collection Size | Brute Force Comparisons | LSH Comparisons | Speedup |
|----------------|------------------------|-----------------|---------|
| 1,000 images | 500K | ~50K | ~10x |
| 10,000 images | 50M | ~500K | ~100x |
| 100,000 images | 5B | ~10M | ~500x |
| 650,000 images | 211B | ~200M | ~1000x |

### Auto-Selection

LSH is automatically enabled when:
- Collection has **≥5,000 images** (configurable via `LSH_AUTO_THRESHOLD`)
- Perceptual matching is enabled (not `--exact-only`)

You can override this with `--lsh` or `--no-lsh`.

### LSH Parameters

The implementation automatically tunes parameters based on collection size:

| Collection Size | Tables | Bits/Table | Expected Recall |
|----------------|--------|------------|-----------------|
| < 10K | 15 | 20 | >99.9% |
| 10K-50K | 18 | 18 | >99.9% |
| 50K-200K | 20 | 16 | >99.9% |
| > 200K | 25 | 14 | >99.9% |

## Caching System

DupeFinder uses SQLite to cache image analysis results, dramatically speeding up subsequent scans.

### How It Works

- **Cache location**: `~/.duplicate_finder_cache.db`
- **Cache key**: File path + modification time + file size
- **Invalidation**: Automatic when files are modified, moved, or deleted

### Performance Impact

| Scenario | Typical Time (650K images) |
|----------|---------------------------|
| First scan (empty cache) | 15-30 minutes |
| Re-scan (100% cache hits) | 30-60 seconds |
| Re-scan after adding 1K photos | 1-2 minutes |

### Cache Management (GUI)

After a scan completes, you'll see a cache info banner:
- **View stats**: Number of cached images and database size
- **Cleanup**: Remove entries for deleted files and stale data
- **Clear**: Wipe the entire cache to force fresh analysis

### Cache Management (API)

```bash
# Get cache statistics
curl http://localhost:5000/api/cache/stats

# Clear all cached data
curl -X POST http://localhost:5000/api/cache/clear

# Cleanup stale entries (files deleted, entries older than 30 days)
curl -X POST http://localhost:5000/api/cache/cleanup \
  -H "Content-Type: application/json" \
  -d '{"max_age_days": 30}'
```

## Package Structure

```
DupeFinderGUI/
├── dupefinder/
│   ├── __init__.py      # Package exports
│   ├── __main__.py      # Entry point for python -m dupefinder
│   ├── config.py        # Configuration constants
│   ├── user_config.py   # User configuration management
│   ├── models.py        # ImageInfo and DuplicateGroup data classes
│   ├── scanner.py       # Core scanning and detection logic
│   ├── lsh.py           # Locality-Sensitive Hashing implementation
│   ├── database.py      # SQLite caching backend
│   ├── state.py         # Session state management
│   ├── routes.py        # Flask API routes
│   ├── app.py           # GUI application entry point
│   ├── cli.py           # Command-line interface
│   └── templates/
│       └── index.html   # Web GUI template
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_scanner.py
│   ├── test_lsh.py
│   └── test_database.py
├── requirements.txt
├── setup.py
└── README.md
```

## How It Works

### Detection Methods

1. **Exact Matching**: Uses SHA-256 file hash to find byte-for-byte identical files
2. **Perceptual Matching**: Uses pHash algorithm to find visually similar images even with:
   - Different resolutions
   - Different compression levels
   - Minor edits or crops
   - Format conversions

### Quality Scoring

When duplicates are found, the tool scores each image based on:
- **Resolution** (pixel count) - up to 50 points
- **File size** - up to 30 points
- **Bit depth** - up to 10 points
- **Format quality** - up to 20 points (RAW > lossless > lossy)

The highest-scoring image is recommended to keep.

### Threshold Guide

The perceptual hash threshold determines how similar images must be:

| Threshold | Meaning | Use Case |
|-----------|---------|----------|
| 0 | Identical | Only exact perceptual matches |
| 5 | Very similar | Same image, minor differences |
| 10 | Similar (default) | Good balance |
| 15 | Somewhat similar | May catch resized/cropped versions |
| 20+ | Loose | May have false positives |

## API Usage

You can also use the scanner as a library:

```python
from dupefinder import (
    find_image_files,
    analyze_image,
    analyze_images_parallel,
    find_exact_duplicates,
    find_perceptual_duplicates,
    get_cache,
    HammingLSH,
    LSH_AUTO_THRESHOLD,
    has_heif_support,
)

# Check for HEIC support
if not has_heif_support():
    print("Warning: HEIC/HEIF support not available")

# Find all images
images = find_image_files("/path/to/photos")

# Analyze them (with caching enabled by default)
analyzed, cache_stats = analyze_images_parallel(images)
print(f"Cache: {cache_stats.hit_rate:.1f}% hit rate")

# Find duplicates (auto-selects LSH for large collections)
exact_groups = find_exact_duplicates(analyzed)
perceptual_groups = find_perceptual_duplicates(
    analyzed, 
    threshold=10,
    use_lsh=None,  # Auto-select, or True/False to force
)

# Work with results
for group in exact_groups:
    print(f"Found {len(group.images)} identical files")
    print(f"Best quality: {group.best_image.path}")
    print(f"Can save: {group.potential_savings_formatted}")

# Direct LSH usage for custom applications
from dupefinder import HammingLSH, calculate_optimal_params

num_tables, bits_per_table = calculate_optimal_params(len(images), threshold=10)
lsh = HammingLSH(num_tables=num_tables, bits_per_table=bits_per_table)
# ... add hashes, query candidates

# Cache management
cache = get_cache()
print(cache.get_stats())  # {'total_entries': 1000, 'db_size_mb': 2.5, ...}
cache.cleanup_missing()   # Remove entries for deleted files
cache.cleanup_stale(30)   # Remove entries not accessed in 30 days
```

## REST API Endpoints

The GUI exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scan` | POST | Start a new scan |
| `/api/status` | GET | Get scan progress |
| `/api/groups` | GET | Get duplicate groups |
| `/api/selections` | POST | Save keep/delete selections |
| `/api/delete` | POST | Move files to trash |
| `/api/image` | GET | Serve image for preview |
| `/api/history` | GET | Get directory scan history |
| `/api/cache/stats` | GET | Get cache statistics |
| `/api/cache/clear` | POST | Clear all cache |
| `/api/cache/cleanup` | POST | Remove stale cache entries |

## Troubleshooting

### Scan is slow on first run
This is normal. The first scan must analyze every image. Subsequent scans will be much faster due to caching.

### Perceptual matching is slow
For collections under 5,000 images, brute-force is used by default. For larger collections, LSH should automatically activate. Check with `--verbose` to see which mode is being used. You can force LSH with `--lsh`.

### Cache is using too much disk space
Use the "Manage Cache" button in the GUI or run cleanup:
```bash
curl -X POST http://localhost:5000/api/cache/cleanup
```

### Images aren't being detected as duplicates
Try lowering the threshold (e.g., `--threshold 5`) for stricter matching, or raising it (e.g., `--threshold 15`) for looser matching.

### LSH is missing some duplicates
LSH is probabilistic and may occasionally miss edge-case duplicates at exactly the threshold distance. For critical applications, use `--no-lsh` to force brute-force comparison, or lower the threshold slightly.

### HEIC files not being processed
Install HEIC support:
```bash
pip install pillow-heif
```

Or if already installed, verify it's working:
```python
from dupefinder import has_heif_support
print(has_heif_support())  # Should print True
```

## License

MIT License - feel free to use and modify!

## Author

Created by Zach

GitHub Repository: [Zedidence/DupeFinderGUI](https://github.com/Zedidence/DupeFinderGUI)

## Changelog

### v2.1.0 (Current)
- **HEIC/HEIF format support** via pillow-heif
- Added `has_heif_support()` API function
- Updated dependencies to include pillow-heif
- Graceful fallback when HEIC support not installed
- Support for modern image formats (WebP, AVIF, JPEG XL)
- Improved error handling for corrupt/truncated images
- **LSH acceleration for perceptual matching** - O(n) instead of O(n²)
- **SQLite caching** for 10-100x faster re-scans
- Auto-enables LSH for collections ≥5,000 images
- 20-1000x speedup for large collections
- Automatic optimization for large collections (50K+ images)
- Cache management UI in web interface
- Cache-related API endpoints
- Improved progress messages with ETA and processing rate
- Formatted numbers (commas) for better readability
- New `--lsh` and `--no-lsh` CLI options
- Updated GUI to show LSH status
- Added Python testing suite
- Security and performance improvements

### v1.0.0
- Initial release with GUI and CLI
- Multi-stage duplicate detection
- Quality-based image ranking
- Session recovery