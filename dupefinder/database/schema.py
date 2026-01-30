"""
Database schema initialization and migrations.

Provides schema versioning and table creation for the cache database.
"""

from __future__ import annotations

import sqlite3


# Schema version - increment when changing table structure
SCHEMA_VERSION = 1


def initialize_schema(conn: sqlite3.Connection) -> None:
    """
    Initialize database schema with versioning support.

    Creates tables and indexes if they don't exist. Drops and recreates
    tables if schema version has changed.

    Args:
        conn: Active database connection

    Tables created:
        - meta: Schema version tracking
        - images: Cached image analysis results
        - scan_history: Directory scan tracking
    """
    # Create meta table for schema versioning
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Check current schema version
    result = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()

    current_version = int(result['value']) if result else 0

    # Drop and recreate tables if schema changed
    if current_version < SCHEMA_VERSION:
        conn.execute("DROP TABLE IF EXISTS images")
        conn.execute("DROP TABLE IF EXISTS scan_history")

    # Main images table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            cache_key TEXT UNIQUE NOT NULL,

            -- Image metadata
            width INTEGER,
            height INTEGER,
            pixel_count INTEGER,
            bit_depth INTEGER,
            format TEXT,

            -- Hashes
            file_hash TEXT,
            perceptual_hash TEXT,

            -- Computed
            quality_score REAL,
            error TEXT,

            -- Timestamps
            created_at REAL DEFAULT (strftime('%s', 'now')),
            last_accessed REAL DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Indexes for common queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_images_cache_key
        ON images(cache_key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_images_path
        ON images(path)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_images_file_hash
        ON images(file_hash)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_images_phash_prefix
        ON images(substr(perceptual_hash, 1, 8))
    """)

    # Scan history for tracking directories
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            directory TEXT NOT NULL,
            file_count INTEGER,
            scan_time REAL,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Update schema version
    conn.execute("""
        INSERT OR REPLACE INTO meta (key, value)
        VALUES ('schema_version', ?)
    """, (str(SCHEMA_VERSION),))


__all__ = ['SCHEMA_VERSION', 'initialize_schema']
