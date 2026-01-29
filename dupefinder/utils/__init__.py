"""
Utilities package for the Duplicate Image Finder.

Provides:
- formatters: Human-readable formatting for numbers, time, and file sizes
- validators: Input validation and security checks
- selection: Selection strategies for duplicate handling
"""

from __future__ import annotations

# Import submodules for convenient access
from . import formatters
from . import validators
from . import selection

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

__all__ = [
    # Submodules
    'formatters',
    'validators',
    'selection',
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
]
