"""
Interactive prompts for the CLI interface.

Provides functions for user interaction including directory selection
and action confirmation.
"""

from __future__ import annotations

from pathlib import Path


def prompt_for_directory() -> Path:
    """
    Interactively prompt user for a directory to scan.

    Returns:
        Path object for the validated directory

    Notes:
        - Displays banner with application name
        - Loops until a valid directory is provided
        - Handles quoted paths (strips quotes)
        - Validates directory exists and is a directory
    """
    print("\n" + "=" * 50)
    print("  DUPLICATE IMAGE FINDER")
    print("=" * 50)

    while True:
        dir_input = input("\nEnter the directory path to scan: ").strip()
        if not dir_input:
            print("Please enter a valid path.")
            continue

        # Handle quotes around path (common when copy-pasting)
        dir_input = dir_input.strip('"\'')
        directory = Path(dir_input)

        if directory.exists() and directory.is_dir():
            return directory
        else:
            print(f"Directory not found: {directory}")
            print("Please try again.")


def confirm_action(action: str, count: int) -> bool:
    """
    Prompt user to confirm a file action.

    Args:
        action: The action to be performed (e.g., 'delete', 'move')
        count: Number of files that will be affected

    Returns:
        True if user confirms (types 'y'), False otherwise

    Examples:
        >>> confirm_action('delete', 42)
        This will delete 42 files. Continue? [y/N]: y
        True
        >>> confirm_action('move', 10)
        This will move 10 files. Continue? [y/N]: n
        False
    """
    confirm = input(f"\nThis will {action} {count:,} files. Continue? [y/N]: ")
    return confirm.lower() == 'y'


__all__ = [
    'prompt_for_directory',
    'confirm_action',
]
