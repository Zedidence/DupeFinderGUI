"""
API package for the Duplicate Image Finder.

Provides Flask routes and scan orchestration for the web interface.
"""

from __future__ import annotations

from .routes import api

__all__ = ['api']
