"""
CLI package for the Duplicate Image Finder.

Provides the command-line interface for scanning and managing duplicate images,
with support for various actions (delete, move, hardlink, symlink) and export
formats.

Public API:
- main: Entry point for CLI execution
- CLIOrchestrator: CLI workflow orchestration class
- handle_duplicates: Function to execute actions on duplicates
- print_duplicate_report: Function to display results report
"""

from __future__ import annotations

from .orchestrator import CLIOrchestrator, setup_logging
from .arg_parser import create_parser, parse_arguments
from .actions import handle_duplicates
from .reporting import print_duplicate_report
from .interactive import prompt_for_directory, confirm_action


def main() -> int:
    """
    Main entry point for the CLI.

    Delegates to CLIOrchestrator to execute the complete workflow.

    Returns:
        Exit code (0 for success, 1 for error)

    Examples:
        >>> # Called from __main__.py
        >>> exit_code = main()
        >>> sys.exit(exit_code)
    """
    orchestrator = CLIOrchestrator()
    return orchestrator.run()


__all__ = [
    # Main entry point
    'main',
    # Core classes
    'CLIOrchestrator',
    # Utilities
    'setup_logging',
    'create_parser',
    'parse_arguments',
    'handle_duplicates',
    'print_duplicate_report',
    'prompt_for_directory',
    'confirm_action',
]
