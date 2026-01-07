"""
State management for Duplicate Image Finder GUI.

Handles persistence of scan state, user selections, and directory history
to allow recovery after browser refresh or application restart.
"""

import json
import os
from datetime import datetime
from typing import Optional

from .config import STATE_FILE, HISTORY_FILE
from .models import DuplicateGroup, ImageInfo


class ScanState:
    """
    Manages the current state of a duplicate scan.
    
    This class handles both the in-memory state during scanning
    and persistence to disk for session recovery.
    """
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset state to initial values."""
        self.status = 'idle'  # idle, scanning, analyzing, comparing, complete, error
        self.progress = 0
        self.message = ''
        self.directory = ''
        self.total_files = 0
        self.analyzed = 0
        self.groups: list[DuplicateGroup] = []
        self.selections: dict[str, str] = {}  # path -> 'keep' | 'delete'
        self.last_updated: Optional[str] = None
        self.settings = {
            'threshold': 10,
            'exact_only': False,
            'perceptual_only': False,
        }
    
    def save(self):
        """Persist state to disk for recovery after refresh/restart."""
        try:
            state_to_save = {
                'status': self.status,
                'progress': self.progress,
                'message': self.message,
                'directory': self.directory,
                'total_files': self.total_files,
                'selections': self.selections,
                'last_updated': datetime.now().isoformat(),
                'settings': self.settings,
                'groups': [g.to_dict() for g in self.groups] if self.status == 'complete' else [],
            }
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_to_save, f)
        except Exception as e:
            print(f"Warning: Could not save state: {e}")
    
    def load(self) -> bool:
        """
        Load persisted state from disk.
        
        Returns:
            True if state was loaded successfully, False otherwise
        """
        try:
            if not os.path.exists(STATE_FILE):
                return False
            
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            
            # Check if state is recent (within 24 hours)
            if saved.get('last_updated'):
                last_updated = datetime.fromisoformat(saved['last_updated'])
                age_hours = (datetime.now() - last_updated).total_seconds() / 3600
                if age_hours > 24:
                    return False
            
            # Restore state
            self.status = saved.get('status', 'idle')
            self.progress = saved.get('progress', 0)
            self.message = saved.get('message', '')
            self.directory = saved.get('directory', '')
            self.total_files = saved.get('total_files', 0)
            self.selections = saved.get('selections', {})
            self.last_updated = saved.get('last_updated')
            self.settings = saved.get('settings', self.settings)
            
            # Rebuild group objects from saved data
            self.groups = []
            for g_data in saved.get('groups', []):
                group = DuplicateGroup.from_dict(g_data)
                self.groups.append(group)
            
            return True
            
        except Exception as e:
            print(f"Warning: Could not load state: {e}")
            return False
    
    def clear_file(self):
        """Remove the state file from disk."""
        try:
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
        except Exception:
            pass
    
    def to_status_dict(self) -> dict:
        """Return current status for API response."""
        return {
            'status': self.status,
            'progress': self.progress,
            'message': self.message,
            'total_files': self.total_files,
            'analyzed': self.analyzed,
            'directory': self.directory,
            'has_results': len(self.groups) > 0,
            'group_count': len(self.groups),
        }
    
    def to_groups_dict(self) -> dict:
        """Return groups data for API response."""
        return {
            'groups': [g.to_dict() for g in self.groups],
            'selections': self.selections,
            'directory': self.directory,
        }


class HistoryManager:
    """Manages directory scan history for autocomplete."""
    
    @staticmethod
    def load() -> dict:
        """Load directory history from disk."""
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {'directories': []}
    
    @staticmethod
    def save_directory(directory: str):
        """Add a directory to history."""
        try:
            history = HistoryManager.load()
            
            # Remove if already exists (to move to front)
            if directory in history['directories']:
                history['directories'].remove(directory)
            
            # Add to front
            history['directories'].insert(0, directory)
            
            # Keep only last 10
            history['directories'] = history['directories'][:10]
            
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f)
        except Exception:
            pass


# Global state instance for the application
scan_state = ScanState()
