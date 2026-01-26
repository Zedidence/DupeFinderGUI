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

from flask import Blueprint, jsonify, request, send_file, render_template

from .state import scan_state, HistoryManager
from .scanner import (
    find_image_files,
    analyze_image,
    analyze_images_parallel,
    find_exact_duplicates,
    find_perceptual_duplicates,
)
from .models import DuplicateGroup
from .database import get_cache
from .config import LSH_AUTO_THRESHOLD

# Create blueprint for routes
api = Blueprint('api', __name__)

# Module logger
_logger = logging.getLogger(__name__)

# Threshold for auto-disabling perceptual matching in GUI
# Perceptual matching is O(n²), so 50K images = 1.25 billion comparisons
PERCEPTUAL_AUTO_DISABLE_THRESHOLD = 50000

# Lock for thread-safe state persistence
_state_lock = threading.Lock()


def format_number(n: int) -> str:
    """Format large numbers with commas for readability."""
    return f"{n:,}"


def format_time_estimate(seconds: float) -> str:
    """Format seconds into human-readable time estimate."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def _safe_save_state():
    """Thread-safe state save to prevent JSON corruption."""
    with _state_lock:
        scan_state.save()


def _validate_path_in_directory(filepath: str, base_directory: str) -> bool:
    """
    Validate that a file path is within the expected base directory.
    
    Prevents path traversal attacks where user input could access files
    outside the scanned directory.
    """
    try:
        file_resolved = Path(filepath).resolve()
        base_resolved = Path(base_directory).resolve()
        return str(file_resolved).startswith(str(base_resolved) + os.sep) or \
               str(file_resolved) == str(base_resolved)
    except Exception:
        return False


def _validate_file_accessible(filepath: str) -> tuple[bool, str]:
    """Validate that a file exists and is accessible before operations."""
    if not os.path.exists(filepath):
        return False, "File does not exist"
    
    if not os.path.isfile(filepath):
        return False, "Path is not a file"
    
    if not os.access(filepath, os.R_OK):
        return False, "File is not readable (permission denied)"
    
    try:
        with open(filepath, 'rb') as f:
            pass
    except PermissionError:
        return False, "File is locked by another process"
    except IOError as e:
        return False, f"Cannot access file: {e}"
    
    return True, ""


def _apply_auto_selection(groups: list[DuplicateGroup], strategy: str) -> dict[str, str]:
    """
    Apply auto-selection strategy to determine which images to keep/delete.
    
    Args:
        groups: List of duplicate groups
        strategy: One of 'quality', 'largest', 'smallest', 'newest', 'oldest'
        
    Returns:
        Dict mapping image path to 'keep' or 'delete'
    """
    selections = {}
    
    for group in groups:
        if not group.images:
            continue
        
        # Sort images based on strategy
        if strategy == 'quality':
            # Default: highest quality score
            sorted_images = sorted(group.images, key=lambda x: -x.quality_score)
        elif strategy == 'largest':
            sorted_images = sorted(group.images, key=lambda x: -x.file_size)
        elif strategy == 'smallest':
            sorted_images = sorted(group.images, key=lambda x: x.file_size)
        elif strategy == 'newest':
            # Sort by mtime (newest first)
            def get_mtime(img):
                try:
                    return os.path.getmtime(img.path)
                except:
                    return 0
            sorted_images = sorted(group.images, key=lambda x: -get_mtime(x))
        elif strategy == 'oldest':
            # Sort by mtime (oldest first)
            def get_mtime(img):
                try:
                    return os.path.getmtime(img.path)
                except:
                    return float('inf')
            sorted_images = sorted(group.images, key=lambda x: get_mtime(x))
        else:
            # Fallback to quality
            sorted_images = sorted(group.images, key=lambda x: -x.quality_score)
        
        # First image is kept, rest are deleted
        for idx, img in enumerate(sorted_images):
            selections[img.path] = 'keep' if idx == 0 else 'delete'
    
    return selections


def run_scan(
    directory: str, 
    threshold: int, 
    exact_only: bool, 
    perceptual_only: bool,
    recursive: bool = True,
    use_cache: bool = True,
    use_lsh: bool | None = None,
    workers: int = 4,
    auto_select_strategy: str = 'quality',
):
    """
    Background scanning function with enhanced progress tracking and cancel support.
    
    This runs in a separate thread to avoid blocking the web server.
    """
    try:
        from collections import defaultdict
        import imagehash
        
        scan_state.reset()
        scan_state.status = 'scanning'
        scan_state.stage = 'scanning'
        scan_state.directory = directory
        scan_state.message = 'Scanning for image files...'
        scan_state.settings = {
            'threshold': threshold,
            'exact_only': exact_only,
            'perceptual_only': perceptual_only,
            'recursive': recursive,
            'use_cache': use_cache,
            'use_lsh': use_lsh,
            'workers': workers,
            'auto_select_strategy': auto_select_strategy,
        }
        scan_state.progress_details['start_time'] = time.time()
        
        # Track if we auto-disabled perceptual
        auto_disabled_perceptual = False
        
        # Save to history
        HistoryManager.save_directory(directory)
        
        # Check for cancel
        if scan_state.cancel_requested:
            scan_state.status = 'cancelled'
            scan_state.message = 'Scan cancelled by user'
            _safe_save_state()
            return
        
        # Find images
        image_files = find_image_files(directory, recursive=recursive)
        scan_state.total_files = len(image_files)
        scan_state.progress_details['elapsed_seconds'] = time.time() - scan_state.progress_details['start_time']
        
        if not image_files:
            scan_state.status = 'complete'
            scan_state.message = 'No images found in directory'
            _safe_save_state()
            return
        
        # Check if we should auto-disable perceptual matching
        if (not exact_only and not perceptual_only and 
            len(image_files) > PERCEPTUAL_AUTO_DISABLE_THRESHOLD and use_lsh is not True):
            auto_disabled_perceptual = True
            exact_only = True
            
            warning_msg = (
                f'⚠️ LARGE COLLECTION DETECTED ({format_number(len(image_files))} images). '
                f'Perceptual matching has been automatically disabled. '
                f'Enable LSH in Advanced Options to process large collections with perceptual matching.'
            )
            scan_state.message = warning_msg
            scan_state.settings['exact_only'] = True
            scan_state.settings['auto_disabled_perceptual'] = True
            _safe_save_state()
            time.sleep(3)
        
        # Check for cancel
        if scan_state.cancel_requested:
            scan_state.status = 'cancelled'
            scan_state.message = 'Scan cancelled by user'
            _safe_save_state()
            return
        
        # Analyze images
        scan_state.status = 'analyzing'
        scan_state.stage = 'analyzing'
        scan_state.message = f'Analyzing {format_number(len(image_files))} images...'
        _safe_save_state()
        
        analysis_start_time = time.time()
        last_save_time = time.time()
        last_progress_update = time.time()
        
        def analysis_progress_callback(current, total):
            nonlocal last_save_time, last_progress_update

            # Check for cancel
            if scan_state.cancel_requested:
                return

            # Handle pause
            while scan_state.paused and not scan_state.cancel_requested:
                time.sleep(0.5)

            current_time = time.time()

            # Optimized: Only update when 0.5 seconds have passed or final update
            should_update = (current_time - last_progress_update >= 0.5) or (current == total)

            if should_update:
                scan_state.analyzed = current
                scan_state.progress = int(current / total * 50)  # 0-50% for analysis
                scan_state.stage_progress = int(current / total * 100)

                elapsed = current_time - analysis_start_time

                # Update progress details
                scan_state.progress_details['elapsed_seconds'] = current_time - scan_state.progress_details['start_time']

                # Update message every 2 seconds
                if current_time - last_progress_update >= 2:
                    rate = current / elapsed if elapsed > 0 else 0
                    remaining = total - current

                    scan_state.progress_details['rate'] = round(rate, 1)

                    if rate > 0:
                        eta_seconds = remaining / rate
                        scan_state.progress_details['eta_seconds'] = int(eta_seconds)
                        eta_str = format_time_estimate(eta_seconds)
                        scan_state.message = (
                            f'Analyzing images: {format_number(current)}/{format_number(total)} '
                            f'({int(rate)}/sec, ~{eta_str} remaining)'
                        )
                    else:
                        scan_state.message = (
                            f'Analyzing images: {format_number(current)}/{format_number(total)}'
                        )
                    last_progress_update = current_time

                # Save state every 5 seconds
                if current_time - last_save_time > 5:
                    _safe_save_state()
                    last_save_time = current_time
        
        # Use the cached parallel analyzer
        images, cache_stats = analyze_images_parallel(
            filepaths=image_files,
            max_workers=workers,
            progress_callback=analysis_progress_callback,
            show_progress=False,
            use_cache=use_cache,
        )
        
        # Update cache stats in progress details
        scan_state.progress_details['cache_hits'] = cache_stats.cache_hits
        scan_state.progress_details['cache_misses'] = cache_stats.cache_misses
        
        # Check for cancel
        if scan_state.cancel_requested:
            scan_state.status = 'cancelled'
            scan_state.message = f'Scan cancelled (analyzed {format_number(len(images))} images)'
            _safe_save_state()
            return
        
        # Log cache stats
        if cache_stats.cache_hits > 0:
            _logger.info(f"Cache: {cache_stats.cache_hits:,} hits, {cache_stats.cache_misses:,} misses "
                  f"({cache_stats.hit_rate:.1f}% hit rate)")
        
        # Separate valid images from errors
        valid_images = [img for img in images if not img.error]
        error_images = [img for img in images if img.error]
        error_count = len(error_images)
        
        scan_state.error_images = error_images
        
        if not valid_images:
            scan_state.status = 'complete'
            scan_state.message = f'No valid images could be analyzed ({error_count} errors)'
            _safe_save_state()
            return
        
        if error_count > 0:
            _logger.warning(f"Warning: {error_count} images could not be analyzed")
        
        # Find exact duplicates
        exact_groups = []
        exact_hashes = set()
        
        if not perceptual_only:
            scan_state.status = 'comparing'
            scan_state.stage = 'exact_matching'
            scan_state.message = f'Finding exact duplicates among {format_number(len(valid_images))} images...'
            scan_state.stage_progress = 0
            
            # Check for cancel
            if scan_state.cancel_requested:
                scan_state.status = 'cancelled'
                scan_state.message = 'Scan cancelled by user'
                _safe_save_state()
                return
            
            exact_groups = find_exact_duplicates(valid_images)
            exact_hashes = {img.file_hash for g in exact_groups for img in g.images}
            
            scan_state.progress_details['exact_groups'] = len(exact_groups)
            exact_dupe_count = sum(len(g.images) - 1 for g in exact_groups)
            scan_state.message = (
                f'Found {format_number(exact_dupe_count)} exact duplicates '
                f'in {format_number(len(exact_groups))} groups'
            )
            scan_state.stage_progress = 100
        
        scan_state.progress = 60
        _safe_save_state()
        
        # Find perceptual duplicates
        perceptual_groups = []
        
        if not exact_only:
            # Calculate expected comparisons for progress
            candidates_count = len([img for img in valid_images 
                                   if img.perceptual_hash and img.file_hash not in exact_hashes])
            
            # Determine if we'll use LSH
            if use_lsh is None:
                # Auto-select based on collection size
                will_use_lsh = candidates_count >= LSH_AUTO_THRESHOLD
            else:
                will_use_lsh = use_lsh
            
            scan_state.progress_details['using_lsh'] = will_use_lsh
            
            if will_use_lsh:
                scan_state.message = (
                    f'Finding visually similar images using LSH ({format_number(candidates_count)} candidates)...'
                )
            else:
                total_comparisons = (candidates_count * (candidates_count - 1)) // 2
                scan_state.progress_details['total_comparisons'] = total_comparisons
                scan_state.message = (
                    f'Finding visually similar images ({format_number(candidates_count)} candidates, '
                    f'{format_number(total_comparisons)} comparisons)...'
                )
            
            scan_state.stage = 'perceptual_matching'
            scan_state.stage_progress = 0
            
            # Check for cancel
            if scan_state.cancel_requested:
                scan_state.status = 'cancelled'
                scan_state.message = 'Scan cancelled by user'
                _safe_save_state()
                return
            
            comparison_start_time = time.time()
            last_progress_update = time.time()
            
            def comparison_progress_callback(current, total):
                nonlocal last_progress_update

                # Check for cancel
                if scan_state.cancel_requested:
                    return

                # Handle pause
                while scan_state.paused and not scan_state.cancel_requested:
                    time.sleep(0.5)

                current_time = time.time()

                # Optimized: Only update when 0.5 seconds have passed or final update
                should_update = (current_time - last_progress_update >= 0.5) or (current == total)

                if should_update:
                    scan_state.progress = 60 + int(current / total * 35)
                    scan_state.stage_progress = int(current / total * 100)
                    scan_state.progress_details['comparisons_done'] = current
                    scan_state.progress_details['elapsed_seconds'] = time.time() - scan_state.progress_details['start_time']

                    # Update message every 2 seconds with progress
                    if current_time - last_progress_update >= 2:
                        elapsed = current_time - comparison_start_time
                        rate = current / elapsed if elapsed > 0 else 0
                        remaining = total - current

                        scan_state.progress_details['rate'] = round(rate, 1)

                        if rate > 0:
                            eta_seconds = remaining / rate
                            scan_state.progress_details['eta_seconds'] = int(eta_seconds)
                            eta_str = format_time_estimate(eta_seconds)
                            scan_state.message = (
                                f'Comparing images: {format_number(current)}/{format_number(total)} '
                                f'({format_number(int(rate))}/sec, ~{eta_str} remaining)'
                            )
                        last_progress_update = current_time
            
            perceptual_groups = find_perceptual_duplicates(
                valid_images,
                threshold=threshold,
                exclude_hashes=exact_hashes,
                start_id=len(exact_groups) + 1,
                progress_callback=comparison_progress_callback,
                show_progress=False,
                use_lsh=use_lsh,
            )
            
            scan_state.progress_details['perceptual_groups'] = len(perceptual_groups)
        
        # Check for cancel one last time
        if scan_state.cancel_requested:
            scan_state.status = 'cancelled'
            scan_state.message = 'Scan cancelled by user'
            _safe_save_state()
            return
        
        scan_state.groups = exact_groups + perceptual_groups
        scan_state.progress = 100
        scan_state.stage = 'complete'
        scan_state.stage_progress = 100
        scan_state.status = 'complete'
        
        # Apply auto-selection strategy
        scan_state.selections = _apply_auto_selection(scan_state.groups, auto_select_strategy)
        
        # Build final summary message
        total_dupes = sum(len(g.images) - 1 for g in scan_state.groups)
        exact_count = sum(len(g.images) - 1 for g in exact_groups)
        perceptual_count = sum(len(g.images) - 1 for g in perceptual_groups)
        
        elapsed_total = time.time() - scan_state.progress_details['start_time']
        scan_state.progress_details['elapsed_seconds'] = elapsed_total
        elapsed_str = format_time_estimate(elapsed_total)
        
        summary_parts = [f'Found {format_number(total_dupes)} duplicates in {format_number(len(scan_state.groups))} groups']
        
        if exact_count > 0 and perceptual_count > 0:
            summary_parts.append(f'({format_number(exact_count)} exact, {format_number(perceptual_count)} similar)')
        elif exact_count > 0:
            summary_parts.append('(exact matches)')
        elif perceptual_count > 0:
            summary_parts.append('(visually similar)')
        
        summary_parts.append(f'• Completed in {elapsed_str}')
        
        if error_count > 0:
            summary_parts.append(f'• {format_number(error_count)} files had errors')
        
        if auto_disabled_perceptual:
            summary_parts.append('• ⚠️ Perceptual matching was skipped for large collection')
        
        scan_state.message = ' '.join(summary_parts)
        scan_state.last_updated = datetime.now().isoformat()
        
        _safe_save_state()
        
    except Exception as e:
        scan_state.status = 'error'
        scan_state.message = f'Error: {str(e)}'
        _logger.exception(f"Scan error: {e}")
        _safe_save_state()


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

    # Validate directory
    if not directory:
        return jsonify({'error': 'Directory path is required'}), 400
    if not os.path.isabs(directory):
        return jsonify({'error': 'Directory must be an absolute path'}), 400
    if not os.path.exists(directory):
        return jsonify({'error': f'Directory not found: {directory}'}), 404
    if not os.path.isdir(directory):
        return jsonify({'error': f'Path is not a directory: {directory}'}), 400
    if not os.access(directory, os.R_OK):
        return jsonify({'error': f'Cannot read directory (permission denied): {directory}'}), 400

    # Validate threshold
    try:
        threshold = int(threshold)
        if not 0 <= threshold <= 64:
            return jsonify({'error': 'Threshold must be between 0 and 64'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Threshold must be an integer'}), 400

    # Validate mutual exclusivity
    if exact_only and perceptual_only:
        return jsonify({'error': 'Cannot use both exactOnly and perceptualOnly'}), 400

    # Validate workers
    workers = max(1, min(workers, 16))

    # Start scan in background thread
    thread = threading.Thread(
        target=run_scan,
        args=(directory, threshold, exact_only, perceptual_only),
        kwargs={
            'recursive': recursive,
            'use_cache': use_cache,
            'use_lsh': use_lsh,
            'workers': workers,
            'auto_select_strategy': auto_select_strategy,
        }
    )
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
    
    scan_state.selections = _apply_auto_selection(scan_state.groups, strategy)
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
        if not _validate_path_in_directory(path, scan_state.directory):
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
            if not _validate_path_in_directory(filepath, scan_state.directory):
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
            is_valid, error_msg = _validate_file_accessible(filepath)
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
    
    response = {'moved': moved, 'errors': errors}
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