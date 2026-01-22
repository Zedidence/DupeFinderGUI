"""
User configuration management for Duplicate Image Finder.

Supports configuration from multiple sources (in order of priority):
1. Runtime parameters (highest priority)
2. Environment variables
3. User config file (~/.dupefinder/config.json)
4. Default values from config.py (lowest priority)

Configuration file location: ~/.dupefinder/config.json

Example config.json:
{
    "default_threshold": 10,
    "default_workers": 4,
    "lsh_auto_threshold": 5000,
    "max_image_pixels": 500000000,
    "cache_max_age_days": 30,
    "perceptual_auto_disable_threshold": 50000,
    "state_dir": null,
    "cache_dir": null
}
"""

import json
import os
from pathlib import Path
from typing import Any, Optional
import logging

from .config import (
    DEFAULT_THRESHOLD,
    DEFAULT_WORKERS,
    LSH_AUTO_THRESHOLD,
    STATE_FILE,
    HISTORY_FILE,
    CACHE_DB_FILE,
)

logger = logging.getLogger(__name__)


class UserConfig:
    """
    Manages user configuration from file and environment variables.

    Attributes are lazy-loaded and cached for performance.
    """

    _instance: Optional['UserConfig'] = None
    _config_data: Optional[dict] = None

    def __new__(cls):
        """Singleton pattern to ensure one config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def config_dir(self) -> Path:
        """Get the configuration directory path."""
        # Check environment variable first
        env_dir = os.getenv('DUPEFINDER_CONFIG_DIR')
        if env_dir:
            return Path(env_dir)

        # Default to ~/.dupefinder/
        return Path.home() / '.dupefinder'

    @property
    def config_file_path(self) -> Path:
        """Get the configuration file path."""
        return self.config_dir / 'config.json'

    def _load_config_file(self) -> dict:
        """Load configuration from JSON file."""
        if not self.config_file_path.exists():
            return {}

        try:
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.debug(f"Loaded configuration from {self.config_file_path}")
                return data
        except Exception as e:
            logger.warning(f"Failed to load config file {self.config_file_path}: {e}")
            return {}

    def _get_config_data(self) -> dict:
        """Get cached config data (lazy loading)."""
        if self._config_data is None:
            self._config_data = self._load_config_file()
        return self._config_data

    def reload(self):
        """Reload configuration from file."""
        self._config_data = None

    def get(self, key: str, default: Any = None, env_var: Optional[str] = None) -> Any:
        """
        Get a configuration value with priority:
        1. Environment variable (if env_var specified)
        2. Config file
        3. Default value

        Args:
            key: Configuration key
            default: Default value if not found
            env_var: Optional environment variable name to check

        Returns:
            Configuration value
        """
        # Check environment variable first
        if env_var:
            env_value = os.getenv(env_var)
            if env_value is not None:
                # Try to parse as JSON for complex types
                try:
                    return json.loads(env_value)
                except (json.JSONDecodeError, TypeError):
                    return env_value

        # Check config file
        config_data = self._get_config_data()
        if key in config_data:
            return config_data[key]

        # Return default
        return default

    @property
    def default_threshold(self) -> int:
        """Perceptual hash similarity threshold (0-64)."""
        return self.get(
            'default_threshold',
            default=DEFAULT_THRESHOLD,
            env_var='DUPEFINDER_THRESHOLD'
        )

    @property
    def default_workers(self) -> int:
        """Number of parallel workers for image analysis."""
        return self.get(
            'default_workers',
            default=DEFAULT_WORKERS,
            env_var='DUPEFINDER_WORKERS'
        )

    @property
    def lsh_auto_threshold(self) -> int:
        """Auto-enable LSH when collection size >= this value."""
        return self.get(
            'lsh_auto_threshold',
            default=LSH_AUTO_THRESHOLD,
            env_var='DUPEFINDER_LSH_THRESHOLD'
        )

    @property
    def max_image_pixels(self) -> int:
        """Maximum image size in pixels (decompression bomb limit)."""
        return self.get(
            'max_image_pixels',
            default=500_000_000,
            env_var='DUPEFINDER_MAX_PIXELS'
        )

    @property
    def cache_max_age_days(self) -> int:
        """Maximum age for cache entries before cleanup (days)."""
        return self.get(
            'cache_max_age_days',
            default=30,
            env_var='DUPEFINDER_CACHE_MAX_AGE'
        )

    @property
    def perceptual_auto_disable_threshold(self) -> int:
        """Auto-disable perceptual matching in GUI when collection size >= this."""
        return self.get(
            'perceptual_auto_disable_threshold',
            default=50000,
            env_var='DUPEFINDER_PERCEPTUAL_DISABLE_THRESHOLD'
        )

    @property
    def state_file(self) -> str:
        """Path to state file."""
        custom = self.get('state_file', env_var='DUPEFINDER_STATE_FILE')
        if custom:
            return custom
        return STATE_FILE

    @property
    def history_file(self) -> str:
        """Path to history file."""
        custom = self.get('history_file', env_var='DUPEFINDER_HISTORY_FILE')
        if custom:
            return custom
        return HISTORY_FILE

    @property
    def cache_db_file(self) -> str:
        """Path to cache database file."""
        custom = self.get('cache_db_file', env_var='DUPEFINDER_CACHE_DB')
        if custom:
            return custom
        return CACHE_DB_FILE

    def create_example_config(self):
        """Create an example configuration file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        example_config = {
            "_comment": "DupeFinder User Configuration",
            "default_threshold": DEFAULT_THRESHOLD,
            "default_workers": DEFAULT_WORKERS,
            "lsh_auto_threshold": LSH_AUTO_THRESHOLD,
            "max_image_pixels": 500000000,
            "cache_max_age_days": 30,
            "perceptual_auto_disable_threshold": 50000,
            "state_file": None,
            "history_file": None,
            "cache_db_file": None,
        }

        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(example_config, f, indent=2)
            logger.info(f"Created example config file at {self.config_file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create example config: {e}")
            return False


# Global instance
_user_config = UserConfig()


def get_user_config() -> UserConfig:
    """Get the global UserConfig instance."""
    return _user_config
