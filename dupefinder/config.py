"""
Configuration constants for Duplicate Image Finder.

This module contains all configurable settings including:
- Supported image extensions
- Format quality rankings for determining which image to keep
"""

# All supported image extensions (comprehensive list)
IMAGE_EXTENSIONS = {
    # Common formats
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
    # RAW formats
    '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2',
    '.pef', '.srw', '.raf', '.3fr', '.dcr', '.kdc', '.mrw', '.nrw',
    # Other formats
    '.ico', '.icns', '.psd', '.psb', '.xcf', '.svg', '.eps',
    '.heic', '.heif', '.avif', '.jxl',
    '.pbm', '.pgm', '.ppm', '.pnm',
    '.tga', '.dds', '.exr', '.hdr',
    '.jp2', '.j2k', '.jpf', '.jpx', '.jpm',
    '.fits', '.fit', '.fts',
    '.pcx', '.sgi', '.rgb', '.rgba', '.bw',
}

# Format quality ranking (higher = better quality potential)
# Lossless/RAW formats ranked higher
FORMAT_QUALITY_RANK = {
    # RAW - highest quality
    '.cr2': 100, '.cr3': 100, '.nef': 100, '.arw': 100, '.dng': 100,
    '.orf': 100, '.rw2': 100, '.pef': 100, '.srw': 100, '.raf': 100,
    '.3fr': 100, '.dcr': 100, '.kdc': 100, '.mrw': 100, '.nrw': 100,
    '.raw': 100,
    # Lossless
    '.tiff': 90, '.tif': 90,
    '.png': 85,
    '.bmp': 80,
    '.psd': 80, '.psb': 80,
    '.exr': 95, '.hdr': 95,
    # Modern efficient formats
    '.webp': 75,  # Can be lossy or lossless
    '.avif': 75,
    '.heic': 75, '.heif': 75,
    '.jxl': 80,
    # Lossy
    '.jpg': 60, '.jpeg': 60,
    '.gif': 50,
    # Other
    '.ico': 40, '.icns': 40,
}

# Default similarity threshold for perceptual hashing
# Lower = stricter matching (0-64 range)
# Recommended: 5-15
DEFAULT_THRESHOLD = 10

# Default number of parallel workers for image analysis
DEFAULT_WORKERS = 4

# LSH (Locality-Sensitive Hashing) configuration
# LSH provides O(n) performance vs O(n²) brute-force for perceptual matching
LSH_AUTO_THRESHOLD = 5000  # Auto-enable LSH when >= this many images
LSH_DEFAULT_TABLES = 20    # Number of hash tables (more = better recall)
LSH_DEFAULT_BITS = 16      # Bits per table (fewer = more candidates)

# Bit depth mapping for different image modes
MODE_BIT_DEPTHS = {
    '1': 1, 'L': 8, 'P': 8, 'RGB': 24, 'RGBA': 32,
    'CMYK': 32, 'YCbCr': 24, 'LAB': 24, 'HSV': 24,
    'I': 32, 'F': 32, 'I;16': 16, 'I;16L': 16,
    'I;16B': 16, 'I;16N': 16,
}

# State/history file locations
import os
STATE_FILE = os.path.join(os.path.expanduser('~'), '.duplicate_finder_state.json')
HISTORY_FILE = os.path.join(os.path.expanduser('~'), '.duplicate_finder_history.json')

# SQLite cache database location
# Stores analyzed image metadata for faster re-scans
CACHE_DB_FILE = os.path.join(os.path.expanduser('~'), '.duplicate_finder_cache.db')