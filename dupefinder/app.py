#!/usr/bin/env python3
"""
Duplicate Image Finder - GUI Application
========================================
A web-based interface for reviewing and managing duplicate images.

Run with: python -m dupefinder.app
Or: python dupefinder/app.py

Options:
    -q, --quiet     Quiet mode - suppress all output except errors
    -v, --verbose   Verbose mode - show all Flask request logs
    -p, --port      Port to run on (default: 5000)
    --no-browser    Don't auto-open browser

Author: Zach
"""

import argparse
import os
import sys
import atexit
import webbrowser
import threading
import logging

from flask import Flask

from .api import api
from .state import scan_state


# Logging levels
LOG_QUIET = 0    # No output except errors
LOG_MINIMAL = 1  # Startup info only (default)
LOG_VERBOSE = 2  # All Flask request logs


def create_app(log_level: int = LOG_MINIMAL) -> Flask:
    """
    Create and configure the Flask application.
    
    Args:
        log_level: Logging verbosity level
        
    Returns:
        Configured Flask app instance
    """
    # Get the package directory for templates
    package_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(package_dir, 'templates')
    
    app = Flask(__name__, template_folder=template_dir)
    app.secret_key = 'duplicate-finder-secret-key'
    
    # Configure logging based on level
    if log_level < LOG_VERBOSE:
        # Suppress Flask's default request logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR if log_level == LOG_QUIET else logging.WARNING)
    
    # Register routes
    app.register_blueprint(api)
    
    return app


def cleanup_on_exit():
    """Clean up state file on exit if scan wasn't complete."""
    if scan_state.status not in ('complete', 'idle'):
        scan_state.clear_file()


def suppress_flask_banner():
    """Suppress Flask's development server banner and startup messages."""
    try:
        import flask.cli
        flask.cli.show_server_banner = lambda *args, **kwargs: None
    except (ImportError, AttributeError):
        pass
    
    # Suppress werkzeug's startup log messages
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)


def main():
    """Main entry point for the GUI application."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Duplicate Image Finder - GUI',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Quiet mode - suppress all output except errors'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose mode - show all Flask request logs'
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=5000,
        help='Port to run the server on (default: 5000)'
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not automatically open browser'
    )
    
    args = parser.parse_args()
    
    # Determine log level
    if args.quiet:
        log_level = LOG_QUIET
    elif args.verbose:
        log_level = LOG_VERBOSE
    else:
        log_level = LOG_MINIMAL
    
    port = args.port
    url = f'http://localhost:{port}'
    
    # Print startup message (unless quiet)
    if log_level >= LOG_MINIMAL:
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║     DUPLICATE IMAGE FINDER - GUI     ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        
        # Try to restore previous state
        if scan_state.load() and scan_state.status == 'complete' and scan_state.groups:
            print(f"  📂 Previous session: {scan_state.directory}")
            print(f"     └─ {len(scan_state.groups)} duplicate groups found")
            print()
        
        print(f"  🌐 Server running at: {url}")
        if not args.no_browser:
            print("     └─ Opening in browser...")
        print()
        print("  💡 Press Ctrl+C to stop")
        print()
    
    # Register cleanup handler
    atexit.register(cleanup_on_exit)
    
    # Suppress Flask banner for non-verbose modes
    if log_level < LOG_VERBOSE:
        suppress_flask_banner()
    
    # Create the app
    app = create_app(log_level)
    
    # Open browser after short delay (unless disabled)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    
    # Configure werkzeug logging
    if log_level < LOG_VERBOSE:
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
    
    # Run Flask
    try:
        app.run(
            host='127.0.0.1',
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        if log_level >= LOG_MINIMAL:
            print("\n  👋 Server stopped\n")


if __name__ == '__main__':
    main()