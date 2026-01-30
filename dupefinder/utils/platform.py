"""
Platform-specific capability checks for the Duplicate Image Finder.

Provides functions to check support for filesystem operations that vary by
platform and configuration, such as hardlinks and symlinks.
"""

from __future__ import annotations

import os
import platform as platform_module
from pathlib import Path


def is_windows_admin() -> bool:
    """
    Check if the current process has administrator privileges on Windows.

    Returns:
        True if running with admin privileges, False otherwise or if not on Windows

    Notes:
        - On non-Windows platforms, returns False
        - Uses ctypes to check Windows admin status
        - Returns False if check fails (safer default)
    """
    if platform_module.system() != 'Windows':
        return False

    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_hardlink_support(source: Path, dest_dir: Path) -> tuple[bool, str]:
    """
    Check if hardlinks are supported between source and destination.

    Hardlinks require:
    - Same filesystem (same st_dev value)
    - Administrator privileges on Windows
    - Source and destination on same mount point

    Args:
        source: Source file path
        dest_dir: Destination directory

    Returns:
        Tuple of (is_supported, reason_if_not)
        - (True, "") if hardlinks are supported
        - (False, reason) if hardlinks are not supported

    Examples:
        >>> check_hardlink_support(Path('/data/file.jpg'), Path('/data/backup/'))
        (True, '')
        >>> check_hardlink_support(Path('/data/file.jpg'), Path('/mnt/external/'))
        (False, 'Source and destination are on different filesystems')
    """
    # Check if both paths are on the same filesystem
    try:
        source_dev = os.stat(source).st_dev
        dest_dev = os.stat(dest_dir).st_dev

        if source_dev != dest_dev:
            return False, "Source and destination are on different filesystems"
    except OSError as e:
        return False, f"Cannot check filesystem: {e}"

    # Windows-specific checks
    if platform_module.system() == 'Windows':
        # On Windows, hardlinks typically require admin privileges
        # or Developer Mode enabled in Windows 10+
        if not is_windows_admin():
            return False, "Hardlinks on Windows require administrator privileges"

    return True, ""


def check_symlink_support(dest_dir: Path) -> tuple[bool, str]:
    """
    Check if symlinks are supported in the destination directory.

    Symlinks require:
    - Administrator privileges on Windows
    - Developer Mode enabled on Windows 10+ (for unprivileged symlinks)

    Args:
        dest_dir: Destination directory

    Returns:
        Tuple of (is_supported, reason_if_not)
        - (True, "") if symlinks are supported
        - (False, reason) if symlinks are not supported

    Examples:
        >>> check_symlink_support(Path('/data/backup/'))
        (True, '')

    Notes:
        - On non-Windows platforms, symlinks are generally always supported
        - Windows requires admin privileges or Developer Mode
        - Developer Mode check is simplified (actual implementation would query registry)
    """
    if platform_module.system() == 'Windows':
        # Check for admin privileges
        if not is_windows_admin():
            # Check for Developer Mode (Windows 10+)
            # This is a simplified check - the actual implementation
            # would need to query the registry key:
            # HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock\AllowDevelopmentWithoutDevLicense
            return False, (
                "Symlinks on Windows require administrator privileges "
                "or Developer Mode enabled"
            )

    return True, ""


__all__ = [
    'is_windows_admin',
    'check_hardlink_support',
    'check_symlink_support',
]
