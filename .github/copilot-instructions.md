# Duplicate Image Finder - AI Coding Guidelines

## Architecture Overview
This is a Python package for finding duplicate images with CLI and web GUI interfaces. Core components:
- `scanner.py`: Image discovery, parallel analysis, duplicate detection (exact via SHA256, perceptual via pHash)
- `models.py`: Data structures (`ImageInfo`, `DuplicateGroup`) with quality scoring
- `database.py`: SQLite cache for incremental scans (`ImageCache`, `CacheStats`)
- `cli.py`: Command-line interface with actions (report/move/delete/hardlink/symlink)
- `routes.py` + `app.py`: Flask web API and GUI server
- `state.py`: Session persistence for GUI recovery
- `__main__.py`: Entry point routing to CLI or GUI

## Key Patterns & Conventions

### Quality Scoring
Images are ranked by quality score (0-110) for automatic "keep best" decisions:
- Resolution: up to 50 points (pixel count / 1M * 2)
- File size: up to 30 points (MB * 3)  
- Bit depth: up to 10 points (depth / 3.2)
- Format: up to 20 points (RAW=100, JPEG=60, PNG=85)

Example: `score = min(50, pixel_count / 1_000_000 * 2) + min(30, file_size_mb * 3) + ...`

### Two-Stage Duplicate Detection
1. **Exact duplicates**: Group by SHA256 file hash
2. **Perceptual duplicates**: Group by pHash similarity (Hamming distance ≤ threshold), excluding exact matches

Example workflow in `scanner.py`:
```python
exact_groups = find_exact_duplicates(images)
exact_hashes = {img.file_hash for g in exact_groups for img in g.images}
perceptual_groups = find_perceptual_duplicates(images, threshold=10, exclude_hashes=exact_hashes)
```

### SQLite Caching
Use `ImageCache` for incremental scans. Cache key: path + mtime + size. Reduces re-analysis time.

Example: `cache = get_cache(); info = cache.get_or_analyze(filepath, analyze_image)`

### Parallel Processing
Use `ThreadPoolExecutor` for image analysis. Default 4 workers, configurable.

Example: `analyze_images_parallel(filepaths, max_workers=4, show_progress=True)`

### Safety First
- Dry-run mode by default (`--no-dry-run` to actually modify files)
- Actions: `report` (safe), `move` (to trash dir), `delete`, `hardlink`, `symlink`
- Session recovery: State saved to `~/.duplicate_finder_state.json`

### Image Format Support
40+ formats including RAW (.cr2, .nef, .dng). Quality ranking favors lossless/RAW formats.

### Web GUI Architecture
- Flask API endpoints return JSON data
- Frontend polls `/api/status` for progress updates
- Images served via `/api/image?path=...` for previews
- User selections persisted in `scan_state.selections`
- History manager tracks recent directories

## Development Workflow
- **Run GUI**: `python -m dupefinder` (opens browser)
- **Run CLI**: `python -m dupefinder cli /path/to/dir --action move --trash-dir ./dupes`
- **Install**: `pip install -e .` (editable install)
- **Test**: No formal tests yet, but validate with sample images
- **Package**: `python setup.py sdist bdist_wheel`

## Common Tasks
- Adding new image formats: Update `IMAGE_EXTENSIONS` and `FORMAT_QUALITY_RANK` in `config.py`
- Modifying quality scoring: Edit `calculate_quality_score()` in `scanner.py`
- Adding CLI options: Extend argparse in `cli.py` and pass to scanner functions
- GUI features: Add routes in `routes.py`, update frontend JavaScript in `templates/index.html`