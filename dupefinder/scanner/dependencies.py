"""
Dependency initialization for the scanner package.

Handles PIL, imagehash, HEIC/HEIF support, and tqdm imports with proper
error handling and configuration.
"""

from __future__ import annotations

import warnings
import logging
from typing import Optional, Any

# Module-level logger
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


__all__ = [
    'Image',
    'imagehash',
    'HAS_HEIF_SUPPORT',
    'HAS_TQDM',
    '_tqdm_class',
    '_logger',
]
