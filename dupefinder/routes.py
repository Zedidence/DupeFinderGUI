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
        
        # Analyze images
        scan_state.status = 'analyzing'
        scan_state.message = f'Analyzing {len(image_files)} images...'
        
        images = []
        last_save_time = time.time()
        
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
                
                # Save state every 5 seconds during scan
                if time.time() - last_save_time > 5:
                    scan_state.save()
                    last_save_time = time.time()
        
        valid_images = [img for img in images if not img.error]
        
        if not valid_images:
            scan_state.status = 'complete'
            scan_state.message = 'No valid images could be analyzed'
            scan_state.save()
            return
        
        # Find exact duplicates
        exact_groups = []
        exact_hashes = set()
        
        if not perceptual_only:
            scan_state.status = 'comparing'
            scan_state.message = 'Finding exact duplicates...'
            
            exact_groups = find_exact_duplicates(valid_images)
            exact_hashes = {img.file_hash for g in exact_groups for img in g.images}
        
        scan_state.progress = 60
        scan_state.save()
        
        # Find perceptual duplicates
        perceptual_groups = []
        
        if not exact_only:
            scan_state.message = 'Finding visually similar images...'
            
            def progress_callback(current, total):
                scan_state.progress = 60 + int(current / total * 35)
            
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
        
        total_dupes = sum(len(g.images) - 1 for g in scan_state.groups)
        scan_state.message = f'Found {total_dupes} duplicates in {len(scan_state.groups)} groups'
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
    return jsonify(scan_state.to_status_dict())


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
