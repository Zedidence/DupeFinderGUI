# Duplicate Image Finder

A comprehensive tool for finding duplicate and visually similar images with both a web GUI and command-line interface. Features intelligent caching for fast re-scans and optimized handling of large collections.

## Features

- **Multi-stage detection**: Exact hash matching + perceptual hash for visually similar images
- **40+ image formats supported**: Including RAW formats (CR2, NEF, ARW, DNG, etc.)
- **Quality-based selection**: Automatically identifies the highest quality version to keep
- **SQLite caching**: Re-scans are 10-100x faster by caching analysis results
- **Large collection support**: Auto-optimizes for collections with 50K+ images
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
| `-a, --action ACTION` | Action: report, delete, move, hardlink, symlink |
| `--trash-dir PATH` | Directory for moved duplicates |
| `--no-dry-run` | Actually perform the action |
| `-w, --workers N` | Number of parallel workers. Default: 4 |
| `-e, --export PATH` | Export results to file |
| `--export-format FMT` | Export format: txt or csv |
| `--no-cache` | Disable SQLite caching |
| `-v, --verbose` | Verbose output |

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

## Large Collection Handling

For collections exceeding 50,000 images, perceptual matching is automatically disabled in the GUI to maintain responsiveness. This is because perceptual comparison is O(n²) — 50K images requires 1.25 billion comparisons.

### What Happens

1. **GUI auto-optimization**: Switches to exact-match-only mode
2. **Warning banner**: Displays with CLI command for full perceptual scan
3. **CLI recommendation**: Use the CLI for perceptual matching on large collections

### Running Full Perceptual Scan on Large Collections

```bash
# For large collections, use CLI with perceptual matching
python -m dupefinder cli /path/to/650k/photos --threshold 10

# The CLI shows progress with ETA
# Analyzing images: 45,230/650,000 (142/sec, ~71m remaining)
```

## Package Structure

```
dupefinder/
├── __init__.py      # Package exports
├── __main__.py      # Entry point for python -m dupefinder
├── config.py        # Configuration constants
├── models.py        # ImageInfo and DuplicateGroup data classes
├── scanner.py       # Core scanning and detection logic
├── database.py      # SQLite caching backend
├── state.py         # Session state management
├── routes.py        # Flask API routes
├── app.py           # GUI application entry point
├── cli.py           # Command-line interface
├── templates/
│   └── index.html   # Web GUI template
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
)

# Find all images
images = find_image_files("/path/to/photos")

# Analyze them (with caching enabled by default)
analyzed, cache_stats = analyze_images_parallel(images)
print(f"Cache: {cache_stats.hit_rate:.1f}% hit rate")

# Find duplicates
exact_groups = find_exact_duplicates(analyzed)
perceptual_groups = find_perceptual_duplicates(analyzed, threshold=10)

# Work with results
for group in exact_groups:
    print(f"Found {len(group.images)} identical files")
    print(f"Best quality: {group.best_image.path}")
    print(f"Can save: {group.potential_savings_formatted}")

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

### GUI becomes unresponsive with large collections
For 50K+ images, the GUI automatically switches to exact-match-only mode. Use the CLI for full perceptual matching on large collections.

### Cache is using too much disk space
Use the "Manage Cache" button in the GUI or run cleanup:
```bash
curl -X POST http://localhost:5000/api/cache/cleanup
```

### Images aren't being detected as duplicates
Try lowering the threshold (e.g., `--threshold 5`) for stricter matching, or raising it (e.g., `--threshold 15`) for looser matching.

## License

MIT License - feel free to use and modify!

## Author

Created by Zach

## Changelog

### v1.1.0
- Added SQLite caching for 10-100x faster re-scans
- Added automatic optimization for large collections (50K+ images)
- Added cache management UI in web interface
- Added cache-related API endpoints
- Improved progress messages with ETA and processing rate
- Added formatted numbers (commas) for better readability

### v1.0.0
- Initial release with GUI and CLI
- Multi-stage duplicate detection
- Quality-based image ranking
- Session recovery
