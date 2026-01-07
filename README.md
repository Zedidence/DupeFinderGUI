# Duplicate Image Finder

A comprehensive tool for finding duplicate and visually similar images with both a web GUI and command-line interface.

## Features

- **Multi-stage detection**: Exact hash matching + perceptual hash for visually similar images
- **40+ image formats supported**: Including RAW formats (CR2, NEF, ARW, DNG, etc.)
- **Quality-based selection**: Automatically identifies the highest quality version to keep
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
| `-v, --verbose` | Verbose output |

## Package Structure

```
dupefinder/
├── __init__.py      # Package exports
├── __main__.py      # Entry point for python -m dupefinder
├── config.py        # Configuration constants
├── models.py        # ImageInfo and DuplicateGroup data classes
├── scanner.py       # Core scanning and detection logic
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
    find_exact_duplicates,
    find_perceptual_duplicates,
)

# Find all images
images = find_image_files("/path/to/photos")

# Analyze them
from dupefinder.scanner import analyze_images_parallel
analyzed = analyze_images_parallel(images)

# Find duplicates
exact_groups = find_exact_duplicates(analyzed)
perceptual_groups = find_perceptual_duplicates(analyzed, threshold=10)

# Work with results
for group in exact_groups:
    print(f"Found {len(group.images)} identical files")
    print(f"Best quality: {group.best_image.path}")
    print(f"Can save: {group.potential_savings_formatted}")
```

## License

MIT License - feel free to use and modify!

## Author

Created by Claude (for Zach)
