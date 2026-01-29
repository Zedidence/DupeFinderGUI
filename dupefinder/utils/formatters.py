"""
Formatting utilities for the Duplicate Image Finder.

Provides human-readable formatting for numbers, time estimates, and file sizes.
"""

from __future__ import annotations

# Re-export format_size from models for convenience
from ..models import format_size


def format_number(n: int) -> str:
    """
    Format large numbers with commas for readability.

    Args:
        n: Number to format

    Returns:
        Formatted string with comma separators

    Examples:
        >>> format_number(1000)
        '1,000'
        >>> format_number(1234567)
        '1,234,567'
    """
    return f"{n:,}"


def format_time_estimate(seconds: float) -> str:
    """
    Format seconds into human-readable time estimate.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted time string (e.g., "5s", "2m 30s", "1h 15m")

    Examples:
        >>> format_time_estimate(45)
        '45s'
        >>> format_time_estimate(150)
        '2m 30s'
        >>> format_time_estimate(3665)
        '1h 1m'
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


__all__ = ['format_number', 'format_time_estimate', 'format_size']
