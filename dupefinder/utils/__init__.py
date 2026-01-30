"""
Utilities package for the Duplicate Image Finder.

Provides:
- formatters: Human-readable formatting for numbers, time, and file sizes
- validators: Input validation and security checks
- selection: Selection strategies for duplicate handling
- platform: Platform-specific capability checks
- exporters: Export duplicate results to files
"""

from __future__ import annotations

# Import submodules for convenient access
from . import formatters
from . import validators
from . import selection
from . import platform
from . import exporters

# Export commonly used functions and classes
from .formatters import format_number, format_time_estimate, format_size
from .validators import (
    validate_path_in_directory,
    validate_file_accessible,
    validate_directory,
    validate_threshold,
    validate_scan_params,
)
from .selection import SelectionStrategy, apply_selection_strategy
from .platform import is_windows_admin, check_hardlink_support, check_symlink_support
from .exporters import export_results

__all__ = [
    # Submodules
    'formatters',
    'validators',
    'selection',
    'platform',
    'exporters',
    # Formatters
    'format_number',
    'format_time_estimate',
    'format_size',
    # Validators
    'validate_path_in_directory',
    'validate_file_accessible',
    'validate_directory',
    'validate_threshold',
    'validate_scan_params',
    # Selection
    'SelectionStrategy',
    'apply_selection_strategy',
    # Platform
    'is_windows_admin',
    'check_hardlink_support',
    'check_symlink_support',
    # Exporters
    'export_results',
]
