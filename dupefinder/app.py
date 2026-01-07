#!/usr/bin/env python3
"""
Duplicate Image Finder - GUI Application
========================================
A web-based interface for reviewing and managing duplicate images.

Run with: python -m dupefinder.app
Or: python dupefinder/app.py

Then open http://localhost:5000 in your browser

Author: Zach
"""

import os
import sys
import atexit
import webbrowser
import threading

from flask import Flask

from .routes import api
from .state import scan_state


def create_app() -> Flask:
    """
    Create and configure the Flask application.
    
    Returns:
        Configured Flask app instance
    """
    # Get the package directory for templates
    package_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(package_dir, 'templates')
    
    app = Flask(__name__, template_folder=template_dir)
    app.secret_key = 'duplicate-finder-secret-key'
    
    # Register routes
    app.register_blueprint(api)
    
    return app


def cleanup_on_exit():
    """Clean up state file on exit if scan wasn't complete."""
    if scan_state.status not in ('complete', 'idle'):
        scan_state.clear_file()


def main():
    """Main entry point for the GUI application."""
    port = 5000
    url = f'http://localhost:{port}'
    
    print("=" * 50)
    print("  DUPLICATE IMAGE FINDER - GUI")
    print("=" * 50)
    
    # Try to restore previous state
    if scan_state.load() and scan_state.status == 'complete' and scan_state.groups:
        print(f"\n📂 Found previous session: {scan_state.directory}")
        print(f"   {len(scan_state.groups)} duplicate groups")
    
    print(f"\n🌐 Opening browser at {url}")
    print("   (If browser doesn't open, navigate there manually)")
    print("\n💡 Press Ctrl+C to stop the server\n")
    
    # Register cleanup handler
    atexit.register(cleanup_on_exit)
    
    # Create the app
    app = create_app()
    
    # Open browser after short delay
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    
    # Run Flask
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
