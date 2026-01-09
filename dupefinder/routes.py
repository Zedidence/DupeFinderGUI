"""
Flask routes for Duplicate Image Finder GUI.

Contains all API endpoints for the web interface.
"""

import os
import shutil
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, render_template

from .state import scan_state, HistoryManager
from .scanner import (
    find_image_files,
    analyze_image,
    find_exact_duplicates,
    find_perceptual_duplicates,
)
from .models import DuplicateGroup

# Create blueprint for routes
api = Blueprint('api', __name__)

# Threshold for auto-disabling perceptual matching in GUI
# Perceptual matching is O(n²), so 50K images = 1.25 billion comparisons
PERCEPTUAL_AUTO_DISABLE_THRESHOLD = 50000


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


def run_scan(directory: str, threshold: int, exact_only: bool, perceptual_only: bool):
    """
    Background scanning function.
    
    This runs in a separate thread to avoid blocking the web server.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from collections import defaultdict
        import imagehash
        
        scan_state.reset()
        scan_state.status = 'scanning'
        scan_state.directory = directory
        scan_state.message = 'Scanning for image files...'
        scan_state.settings = {
            'threshold': threshold,
            'exact_only': exact_only,
            'perceptual_only': perceptual_only,
        }
        
        # Track if we auto-disabled perceptual
        auto_disabled_perceptual = False
        
        # Save to history
        HistoryManager.save_directory(directory)
        
        # Find images
        image_files = find_image_files(directory)
        scan_state.total_files = len(image_files)
        
        if not image_files:
            scan_state.status = 'complete'
            scan_state.message = 'No images found in directory'
            scan_state.save()
            return
        
        # Check if we should auto-disable perceptual matching for large collections
        if (not exact_only and not perceptual_only and 
            len(image_files) > PERCEPTUAL_AUTO_DISABLE_THRESHOLD):
            auto_disabled_perceptual = True
            exact_only = True
            scan_state.message = (
                f'Large collection ({format_number(len(image_files))} images). '
                f'Running exact match only for responsiveness. '
                f'Use CLI with --threshold {threshold} for perceptual matching.'
            )
            scan_state.settings['exact_only'] = True
            scan_state.settings['auto_disabled_perceptual'] = True
            time.sleep(2)  # Give user time to see the message
        
        # Analyze images
        scan_state.status = 'analyzing'
        scan_state.message = f'Analyzing {format_number(len(image_files))} images...'
        
        images = []
        last_save_time = time.time()
        last_rate_time = time.time()
        last_rate_count = 0
        images_per_second = 0
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(analyze_image, path): path for path in image_files}
            for i, future in enumerate(as_completed(futures)):
                try:
                    info = future.result()
                    images.append(info)
                except Exception as e:
                    print(f"Error analyzing image: {e}")
                
                scan_state.analyzed = i + 1
                scan_state.progress = int((i + 1) / len(image_files) * 50)
                
                # Calculate processing rate every 2 seconds
                current_time = time.time()
                if current_time - last_rate_time >= 2:
                    elapsed = current_time - last_rate_time
                    processed = (i + 1) - last_rate_count
                    images_per_second = processed / elapsed if elapsed > 0 else 0
                    last_rate_time = current_time
                    last_rate_count = i + 1
                
                # Update message with progress and ETA
                remaining = len(image_files) - (i + 1)
                if images_per_second > 0:
                    eta_seconds = remaining / images_per_second
                    eta_str = format_time_estimate(eta_seconds)
                    scan_state.message = (
                        f'Analyzing images: {format_number(i + 1)}/{format_number(len(image_files))} '
                        f'({int(images_per_second)}/sec, ~{eta_str} remaining)'
                    )
                else:
                    scan_state.message = (
                        f'Analyzing images: {format_number(i + 1)}/{format_number(len(image_files))}'
                    )
                
                # Save state every 5 seconds during scan
                if current_time - last_save_time > 5:
                    scan_state.save()
                    last_save_time = current_time
        
        valid_images = [img for img in images if not img.error]
        error_count = len(images) - len(valid_images)
        
        if not valid_images:
            scan_state.status = 'complete'
            scan_state.message = 'No valid images could be analyzed'
            scan_state.save()
            return
        
        # Log error count if significant
        if error_count > 0:
            print(f"Warning: {error_count} images could not be analyzed")
        
        # Find exact duplicates
        exact_groups = []
        exact_hashes = set()
        
        if not perceptual_only:
            scan_state.status = 'comparing'
            scan_state.message = f'Finding exact duplicates among {format_number(len(valid_images))} images...'
            
            exact_groups = find_exact_duplicates(valid_images)
            exact_hashes = {img.file_hash for g in exact_groups for img in g.images}
            
            exact_dupe_count = sum(len(g.images) - 1 for g in exact_groups)
            scan_state.message = (
                f'Found {format_number(exact_dupe_count)} exact duplicates '
                f'in {format_number(len(exact_groups))} groups'
            )
        
        scan_state.progress = 60
        scan_state.save()
        
        # Find perceptual duplicates
        perceptual_groups = []
        
        if not exact_only:
            # Calculate expected comparisons for progress message
            candidates_count = len([img for img in valid_images 
                                   if img.perceptual_hash and img.file_hash not in exact_hashes])
            total_comparisons = (candidates_count * (candidates_count - 1)) // 2
            
            scan_state.message = (
                f'Finding visually similar images ({format_number(candidates_count)} candidates, '
                f'{format_number(total_comparisons)} comparisons)...'
            )
            
            comparison_start_time = time.time()
            last_progress_update = time.time()
            
            def progress_callback(current, total):
                nonlocal last_progress_update
                scan_state.progress = 60 + int(current / total * 35)
                
                # Update message every 2 seconds with progress
                current_time = time.time()
                if current_time - last_progress_update >= 2:
                    elapsed = current_time - comparison_start_time
                    rate = current / elapsed if elapsed > 0 else 0
                    remaining = total - current
                    if rate > 0:
                        eta_seconds = remaining / rate
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
                progress_callback=progress_callback,
                show_progress=False,
            )
        
        scan_state.groups = exact_groups + perceptual_groups
        scan_state.progress = 100
        scan_state.status = 'complete'
        
        # Initialize selections (keep best, delete rest)
        for g in scan_state.groups:
            sorted_images = sorted(g.images, key=lambda x: -x.quality_score)
            for idx, img in enumerate(sorted_images):
                scan_state.selections[img.path] = 'keep' if idx == 0 else 'delete'
        
        # Build final summary message
        total_dupes = sum(len(g.images) - 1 for g in scan_state.groups)
        exact_count = sum(len(g.images) - 1 for g in exact_groups)
        perceptual_count = sum(len(g.images) - 1 for g in perceptual_groups)
        
        summary_parts = [f'Found {format_number(total_dupes)} duplicates in {format_number(len(scan_state.groups))} groups']
        
        if exact_count > 0 and perceptual_count > 0:
            summary_parts.append(f'({format_number(exact_count)} exact, {format_number(perceptual_count)} similar)')
        elif exact_count > 0:
            summary_parts.append('(exact matches)')
        elif perceptual_count > 0:
            summary_parts.append('(visually similar)')
        
        if auto_disabled_perceptual:
            summary_parts.append('• Perceptual matching skipped for large collection')
        
        scan_state.message = ' '.join(summary_parts)
        scan_state.last_updated = datetime.now().isoformat()
        
        scan_state.save()
        
    except Exception as e:
        scan_state.status = 'error'
        scan_state.message = f'Error: {str(e)}'
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
    directory = data.get('directory', '')
    threshold = data.get('threshold', 10)
    exact_only = data.get('exactOnly', False)
    perceptual_only = data.get('perceptualOnly', False)
    
    # Start scan in background thread
    thread = threading.Thread(
        target=run_scan,
        args=(directory, threshold, exact_only, perceptual_only)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'started'})


@api.route('/api/ping')
def api_ping():
    """Simple endpoint for connection monitoring."""
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})


@api.route('/api/status')
def api_status():
    """Return current scan status."""
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
    data = request.json
    scan_state.selections = data.get('selections', {})
    scan_state.save()
    return jsonify({'status': 'saved'})


@api.route('/api/clear', methods=['POST'])
def api_clear():
    """Clear current session state."""
    scan_state.reset()
    scan_state.clear_file()
    return jsonify({'status': 'cleared'})


@api.route('/api/image')
def api_image():
    """Serve an image file for preview."""
    path = request.args.get('path', '')
    if os.path.exists(path):
        return send_file(path)
    return '', 404


@api.route('/api/delete', methods=['POST'])
def api_delete():
    """Move selected files to trash directory."""
    data = request.json
    files = data.get('files', [])
    trash_dir = data.get('trashDir', '')
    
    if not trash_dir:
        return jsonify({'error': 'No trash directory specified'}), 400
    
    # Create trash dir
    os.makedirs(trash_dir, exist_ok=True)
    
    moved = 0
    errors = 0
    
    for filepath in files:
        try:
            if os.path.exists(filepath):
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
        except Exception as e:
            errors += 1
            print(f"Error moving {filepath}: {e}")
    
    return jsonify({'moved': moved, 'errors': errors})