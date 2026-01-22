"""
Allow running the package with: python -m dupefinder

By default, launches the GUI. Use 'cli' subcommand for command-line interface.

Examples:
    python -m dupefinder                     # Launch GUI
    python -m dupefinder gui                 # Launch GUI (explicit)
    python -m dupefinder cli                 # Launch CLI (interactive)
    python -m dupefinder cli /path/to/photos # CLI with path
    python -m dupefinder config --init       # Create example config file
"""

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'cli':
        # Remove 'cli' from argv so argparse in cli.py doesn't see it
        sys.argv.pop(1)
        from .cli import main as cli_main
        cli_main()
    elif len(sys.argv) > 1 and sys.argv[1] == 'gui':
        # Remove 'gui' from argv
        sys.argv.pop(1)
        from .app import main as gui_main
        gui_main()
    elif len(sys.argv) > 1 and sys.argv[1] == 'config':
        # Remove 'config' from argv
        sys.argv.pop(1)
        from .user_config import get_user_config

        config = get_user_config()

        if '--init' in sys.argv or '-i' in sys.argv:
            # Create example config file
            if config.create_example_config():
                print(f"✓ Created example configuration file at:")
                print(f"  {config.config_file_path}")
                print(f"\nEdit this file to customize DupeFinder settings.")
            else:
                print(f"✗ Failed to create configuration file.")
                sys.exit(1)
        else:
            # Show current config path and values
            print(f"Configuration file: {config.config_file_path}")
            if config.config_file_path.exists():
                print(f"Status: ✓ Found")
            else:
                print(f"Status: ✗ Not found (using defaults)")
                print(f"\nRun 'python -m dupefinder config --init' to create one.")

            print(f"\nCurrent settings:")
            print(f"  default_threshold: {config.default_threshold}")
            print(f"  default_workers: {config.default_workers}")
            print(f"  lsh_auto_threshold: {config.lsh_auto_threshold:,}")
            print(f"  max_image_pixels: {config.max_image_pixels:,}")
            print(f"  cache_max_age_days: {config.cache_max_age_days}")
            print(f"  perceptual_auto_disable_threshold: {config.perceptual_auto_disable_threshold:,}")
    else:
        # Default to GUI
        from .app import main as gui_main
        gui_main()


if __name__ == '__main__':
    main()
