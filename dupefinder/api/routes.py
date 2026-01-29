"""
Flask routes for Duplicate Image Finder GUI.

Contains all API endpoints for the web interface.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, send_file, render_template

from ..state import scan_state, HistoryManager
from ..models import DuplicateGroup
from ..database import get_cache
from ..utils import formatters, validators, selection
from .orchestrator import ScanOrchestrator

# Create blueprint for routes
api = Blueprint('api', __name__)

# Module logger
_logger = logging.getLogger(__name__)

# Lock for thread-safe state persistence
_state_lock = threading.Lock()


def _safe_save_state():
    """Thread-safe state save to prevent JSON corruption."""
    with _state_lock:
        scan_state.save()


# =============================================================================
# Route Handlers
# =============================================================================

@api.route('/')
def index():
    """Serve the main HTML page."""
    return render_template('index.html')


@api.route('/api/scan', methods=['POST'])
def api_scan():
    """Start a new scan in the background."""
    data = request.json
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    directory = data.get('directory', '').strip()
    threshold = data.get('threshold', 10)
    exact_only = data.get('exactOnly', False)
    perceptual_only = data.get('perceptualOnly', False)

    # New options
    recursive = data.get('recursive', True)
    use_cache = data.get('useCache', True)
    use_lsh = data.get('useLsh')  # None, True, or False
    workers = data.get('workers', 4)
    auto_select_strategy = data.get('autoSelectStrategy', 'quality')

    # Validate parameters
    is_valid, error = validators.validate_scan_params(
        directory=directory,
        threshold=threshold,
        exact_only=exact_only,
        perceptual_only=perceptual_only,
        workers=workers,
    )
    if not is_valid:
        return jsonify({'error': error}), 400

    # Validate workers (clamp to safe range)
    workers = max(1, min(workers, 16))

    # Create scan orchestrator
    orchestrator = ScanOrchestrator(
        scan_state=scan_state,
        directory=directory,
        threshold=threshold,
        exact_only=exact_only,
        perceptual_only=perceptual_only,
        recursive=recursive,
        use_cache=use_cache,
        use_lsh=use_lsh,
        workers=workers,
        auto_select_strategy=auto_select_strategy,
        save_callback=_safe_save_state,
    )

    # Start scan in background thread
    thread = threading.Thread(target=orchestrator.run)
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'started'})


@api.route('/api/cancel', methods=['POST'])
def api_cancel():
    """Cancel the current scan."""
    if scan_state.status in ('scanning', 'analyzing', 'comparing'):
        scan_state.request_cancel()
        return jsonify({'status': 'cancel_requested'})
    return jsonify({'status': 'no_scan_running'})


@api.route('/api/pause', methods=['POST'])
def api_pause():
    """Pause the current scan."""
    if scan_state.status in ('scanning', 'analyzing', 'comparing'):
        scan_state.pause()
        return jsonify({'status': 'paused'})
    return jsonify({'status': 'no_scan_running'})


@api.route('/api/resume', methods=['POST'])
def api_resume():
    """Resume a paused scan."""
    if scan_state.paused:
        scan_state.resume()
        return jsonify({'status': 'resumed'})
    return jsonify({'status': 'not_paused'})


@api.route('/api/ping')
def api_ping():
    """Simple endpoint for connection monitoring."""
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})


@api.route('/api/status')
def api_status():
    """Return current scan status with detailed progress info."""
    status_dict = scan_state.to_status_dict()
    # Add auto-disabled flag if relevant
    if scan_state.settings.get('auto_disabled_perceptual'):
        status_dict['auto_disabled_perceptual'] = True
    return jsonify(status_dict)


@api.route('/api/history')
def api_history():
    """Return directory scan history."""
    history = HistoryManager.load()
    return jsonify(history)


@api.route('/api/groups')
def api_groups():
    """Return all duplicate groups."""
    return jsonify(scan_state.to_groups_dict())


@api.route('/api/selections', methods=['POST'])
def api_selections():
    """Save user selections."""
    data = request.json or {}
    scan_state.selections = data.get('selections', {})
    _safe_save_state()
    return jsonify({'status': 'saved'})


@api.route('/api/apply_strategy', methods=['POST'])
def api_apply_strategy():
    """Apply an auto-selection strategy to current results."""
    data = request.json or {}
    strategy = data.get('strategy', 'quality')
    
    if not scan_state.groups:
        return jsonify({'error': 'No groups to apply strategy to'}), 400

    scan_state.selections = selection.apply_selection_strategy(scan_state.groups, strategy)
    scan_state.settings['auto_select_strategy'] = strategy
    _safe_save_state()
    
    return jsonify({
        'status': 'applied',
        'selections': scan_state.selections,
    })


@api.route('/api/clear', methods=['POST'])
def api_clear():
    """Clear current session state."""
    scan_state.reset()
    scan_state.clear_file()
    return jsonify({'status': 'cleared'})


@api.route('/api/image')
def api_image():
    """Serve an image file for preview.

    Security: Only serves images within the scanned directory
    to prevent path traversal attacks.
    """
    path = request.args.get('path', '').strip()

    if not path:
        return jsonify({'error': 'No path specified'}), 400

    # Security check: Validate path is within scanned directory
    if scan_state.directory:
        if not validators.validate_path_in_directory(path, scan_state.directory):
            _logger.warning(f"Blocked access to file outside scan directory: {path}")
            return jsonify({'error': 'Access denied: file outside scan directory'}), 403
    else:
        # No scan results available - don't serve any files
        return jsonify({'error': 'No active scan results'}), 403

    # Verify file exists
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404

    if not os.path.isfile(path):
        return jsonify({'error': 'Path is not a file'}), 400

    # Serve the file
    try:
        return send_file(path)
    except Exception as e:
        _logger.error(f"Error serving file {path}: {e}")
        return jsonify({'error': f'Error serving file: {str(e)}'}), 500


@api.route('/api/delete', methods=['POST'])
def api_delete():
    """Move selected files to trash directory."""
    data = request.json
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    files = data.get('files', [])
    trash_dir = data.get('trashDir', '').strip()

    # Validate inputs
    if not trash_dir:
        return jsonify({'error': 'No trash directory specified'}), 400
    if not os.path.isabs(trash_dir):
        return jsonify({'error': 'Trash directory must be an absolute path'}), 400
    if not isinstance(files, list):
        return jsonify({'error': 'Files must be a list'}), 400
    if len(files) == 0:
        return jsonify({'error': 'No files specified'}), 400

    # Validate all file paths are within the scanned directory
    if scan_state.directory:
        invalid_paths = []
        for filepath in files:
            if not validators.validate_path_in_directory(filepath, scan_state.directory):
                invalid_paths.append(filepath)

        if invalid_paths:
            _logger.warning(f"Blocked deletion of files outside scan directory: {invalid_paths}")
            return jsonify({
                'error': 'Security error: some files are outside the scanned directory',
                'invalid_paths': invalid_paths
            }), 403

    # Create trash directory
    try:
        os.makedirs(trash_dir, exist_ok=True)
    except PermissionError:
        return jsonify({'error': f'Cannot create trash directory (permission denied): {trash_dir}'}), 400
    except OSError as e:
        return jsonify({'error': f'Cannot create trash directory: {e}'}), 400
    
    moved = 0
    errors = 0
    error_details = []
    
    for filepath in files:
        try:
            is_valid, error_msg = validators.validate_file_accessible(filepath)
            if not is_valid:
                errors += 1
                error_details.append({'path': filepath, 'error': error_msg})
                _logger.warning(f"Cannot move {filepath}: {error_msg}")
                continue
            
            filename = os.path.basename(filepath)
            dest = os.path.join(trash_dir, filename)
            
            # Handle name conflicts
            counter = 1
            base, ext = os.path.splitext(filename)
            while os.path.exists(dest):
                dest = os.path.join(trash_dir, f"{base}_{counter}{ext}")
                counter += 1
            
            shutil.move(filepath, dest)
            moved += 1
            
        except PermissionError as e:
            errors += 1
            error_details.append({'path': filepath, 'error': 'Permission denied'})
            _logger.warning(f"Permission denied moving {filepath}: {e}")
        except FileNotFoundError:
            errors += 1
            error_details.append({'path': filepath, 'error': 'File not found (may have been deleted)'})
        except OSError as e:
            errors += 1
            error_details.append({'path': filepath, 'error': str(e)})
            _logger.warning(f"OS error moving {filepath}: {e}")
        except Exception as e:
            errors += 1
            error_details.append({'path': filepath, 'error': str(e)})
            _logger.exception(f"Unexpected error moving {filepath}: {e}")
    
    response: dict[str, Any] = {'moved': moved, 'errors': errors}
    if error_details:
        response['error_details'] = error_details
    
    return jsonify(response)


@api.route('/api/cache/stats')
def api_cache_stats():
    """Return cache statistics."""
    cache = get_cache()
    stats = cache.get_stats()
    return jsonify(stats)


@api.route('/api/cache/clear', methods=['POST'])
def api_cache_clear():
    """Clear the image analysis cache."""
    cache = get_cache()
    cache.clear()
    return jsonify({'status': 'cleared'})


@api.route('/api/cache/cleanup', methods=['POST'])
def api_cache_cleanup():
    """Clean up stale and missing entries from cache."""
    cache = get_cache()
    
    missing_removed = cache.cleanup_missing()
    
    data = request.json or {}
    max_age_days = data.get('max_age_days', 30)
    stale_removed = cache.cleanup_stale(max_age_days=max_age_days)
    
    cache.vacuum()
    
    return jsonify({
        'missing_removed': missing_removed,
        'stale_removed': stale_removed,
    })