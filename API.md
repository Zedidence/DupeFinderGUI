# DupeFinder REST API Documentation

The DupeFinder web GUI exposes a REST API for programmatic access to duplicate detection functionality.

**Base URL**: `http://localhost:5000` (default)

---

## Table of Contents

1. [Scan Operations](#scan-operations)
2. [Status and Progress](#status-and-progress)
3. [Results Management](#results-management)
4. [Cache Management](#cache-management)
5. [Utility Endpoints](#utility-endpoints)

---

## Scan Operations

### Start a New Scan

```http
POST /api/scan
Content-Type: application/json

{
  "directory": "/path/to/images",
  "threshold": 10,
  "exactOnly": false,
  "perceptualOnly": false
}
```

**Request Body**:
- `directory` (string, required): Absolute path to directory to scan
- `threshold` (integer, optional): Perceptual hash threshold (0-64), default: 10
- `exactOnly` (boolean, optional): Only find exact duplicates, default: false
- `perceptualOnly` (boolean, optional): Only find perceptual duplicates, default: false

**Response** (200 OK):
```json
{
  "status": "started"
}
```

**Error Responses**:
- `400 Bad Request`: Invalid parameters
  ```json
  {
    "error": "Directory must be an absolute path"
  }
  ```
- `404 Not Found`: Directory does not exist
  ```json
  {
    "error": "Directory not found: /path/to/images"
  }
  ```

**Notes**:
- Scan runs in background thread
- Poll `/api/status` for progress updates
- Only one scan can run at a time

---

## Status and Progress

### Get Current Scan Status

```http
GET /api/status
```

**Response** (200 OK):
```json
{
  "status": "analyzing",
  "progress": 45,
  "message": "Analyzing images: 4,500/10,000 (125/sec, ~44s remaining)",
  "total_files": 10000,
  "analyzed": 4500,
  "directory": "/path/to/images",
  "has_results": false,
  "group_count": 0,
  "error_count": 0
}
```

**Status Values**:
- `idle`: No scan in progress
- `scanning`: Finding image files
- `analyzing`: Analyzing image metadata
- `comparing`: Comparing for duplicates
- `complete`: Scan finished
- `error`: Scan failed

**Fields**:
- `status` (string): Current scan status
- `progress` (integer): Progress percentage (0-100)
- `message` (string): Human-readable status message
- `total_files` (integer): Total number of image files found
- `analyzed` (integer): Number of images analyzed so far
- `directory` (string): Directory being scanned
- `has_results` (boolean): Whether duplicate groups are available
- `group_count` (integer): Number of duplicate groups found
- `error_count` (integer): Number of images that could not be analyzed

---

### Get Scan History

```http
GET /api/history
```

**Response** (200 OK):
```json
{
  "directories": [
    "/path/to/images",
    "/another/path",
    "/third/path"
  ]
}
```

**Notes**:
- Returns last 10 scanned directories
- Most recent first
- Used for autocomplete in UI

---

## Results Management

### Get Duplicate Groups

```http
GET /api/groups
```

**Response** (200 OK):
```json
{
  "groups": [
    {
      "id": 1,
      "match_type": "exact",
      "image_count": 3,
      "images": [
        {
          "path": "/path/to/img1.jpg",
          "filename": "img1.jpg",
          "directory": "/path/to",
          "file_size": 2048576,
          "file_size_formatted": "2.0 MB",
          "width": 1920,
          "height": 1080,
          "resolution": "1920x1080",
          "pixel_count": 2073600,
          "megapixels": 2.07,
          "format": "JPEG",
          "quality_score": 75.5,
          "error": null
        },
        {
          "path": "/path/to/img2.jpg",
          ...
        }
      ],
      "best_path": "/path/to/img1.jpg",
      "selected_keep": "/path/to/img1.jpg",
      "potential_savings": 4096000,
      "potential_savings_formatted": "3.9 MB"
    }
  ],
  "selections": {
    "/path/to/img1.jpg": "keep",
    "/path/to/img2.jpg": "delete",
    "/path/to/img3.jpg": "delete"
  },
  "directory": "/path/to/images",
  "error_images": []
}
```

**Fields**:
- `groups` (array): Array of duplicate groups
  - `id` (integer): Unique group identifier
  - `match_type` (string): "exact" or "perceptual"
  - `image_count` (integer): Number of images in group
  - `images` (array): Array of ImageInfo objects (sorted by quality, best first)
  - `best_path` (string): Path to highest quality image (recommended to keep)
  - `selected_keep` (string): Currently selected image to keep
  - `potential_savings` (integer): Bytes saved if duplicates removed
  - `potential_savings_formatted` (string): Human-readable size
- `selections` (object): User's keep/delete selections
- `directory` (string): Scanned directory path
- `error_images` (array): Images that could not be analyzed

---

### Save User Selections

```http
POST /api/selections
Content-Type: application/json

{
  "selections": {
    "/path/to/img1.jpg": "keep",
    "/path/to/img2.jpg": "delete",
    "/path/to/img3.jpg": "delete"
  }
}
```

**Request Body**:
- `selections` (object): Map of file path to "keep" or "delete"

**Response** (200 OK):
```json
{
  "status": "saved"
}
```

---

### Delete Selected Files

```http
POST /api/delete
Content-Type: application/json

{
  "files": [
    "/path/to/img2.jpg",
    "/path/to/img3.jpg"
  ],
  "trashDir": "/path/to/trash"
}
```

**Request Body**:
- `files` (array): Paths to files to delete
- `trashDir` (string): Absolute path to trash directory (files will be moved here)

**Response** (200 OK):
```json
{
  "moved": 2,
  "errors": 0
}
```

**Fields**:
- `moved` (integer): Number of files successfully moved
- `errors` (integer): Number of files that failed to move

**Error Responses**:
- `400 Bad Request`: Invalid parameters
- `500 Internal Server Error`: Failed to create trash directory

**Notes**:
- Files are moved, not permanently deleted
- Handles filename conflicts automatically
- Creates trash directory if it doesn't exist

---

### Clear Session State

```http
POST /api/clear
```

**Response** (200 OK):
```json
{
  "status": "cleared"
}
```

**Notes**:
- Clears current scan results
- Resets scan state to idle
- Deletes state file from disk

---

## Cache Management

### Get Cache Statistics

```http
GET /api/cache/stats
```

**Response** (200 OK):
```json
{
  "total_entries": 15234,
  "db_size_bytes": 3145728,
  "db_size_mb": 3.0,
  "db_path": "/home/user/.duplicate_finder_cache.db"
}
```

**Fields**:
- `total_entries` (integer): Number of cached images
- `db_size_bytes` (integer): Database size in bytes
- `db_size_mb` (float): Database size in MB
- `db_path` (string): Path to cache database file

---

### Clear All Cache

```http
POST /api/cache/clear
```

**Response** (200 OK):
```json
{
  "status": "cleared"
}
```

**Notes**:
- Removes all cached image analysis data
- Next scan will be slower (full analysis)
- Frees disk space

---

### Cleanup Cache

```http
POST /api/cache/cleanup
Content-Type: application/json

{
  "max_age_days": 30
}
```

**Request Body**:
- `max_age_days` (integer, optional): Remove entries older than this many days, default: 30

**Response** (200 OK):
```json
{
  "missing_removed": 45,
  "stale_removed": 128
}
```

**Fields**:
- `missing_removed` (integer): Entries for deleted files removed
- `stale_removed` (integer): Entries older than max_age_days removed

**Notes**:
- Automatically compacts database after cleanup
- Safe to run periodically

---

## Utility Endpoints

### Get Image File

```http
GET /api/image?path=/path/to/image.jpg
```

**Query Parameters**:
- `path` (string, required): Absolute path to image file

**Response** (200 OK):
- Binary image data
- Content-Type header set appropriately (image/jpeg, image/png, etc.)

**Error Responses**:
- `400 Bad Request`: No path specified
- `403 Forbidden`: Path not in scan results (security check)
- `404 Not Found`: File not found
- `500 Internal Server Error`: Failed to serve file

**Security**:
- Only serves images from the most recent scan results
- Prevents path traversal attacks
- Normalized paths before checking

---

### Health Check

```http
GET /api/ping
```

**Response** (200 OK):
```json
{
  "status": "ok",
  "time": "2026-01-22T15:30:45.123456"
}
```

**Notes**:
- Simple endpoint to check if server is running
- Returns current server time in ISO format

---

## Error Handling

All endpoints may return these standard errors:

**400 Bad Request**:
```json
{
  "error": "Descriptive error message"
}
```

**403 Forbidden**:
```json
{
  "error": "Access denied: reason"
}
```

**404 Not Found**:
```json
{
  "error": "Resource not found"
}
```

**500 Internal Server Error**:
```json
{
  "error": "Internal error: details"
}
```

---

## Example Usage

### Python

```python
import requests
import json

base_url = "http://localhost:5000"

# Start scan
response = requests.post(
    f"{base_url}/api/scan",
    json={
        "directory": "/path/to/photos",
        "threshold": 10,
        "exactOnly": False
    }
)
print(response.json())  # {"status": "started"}

# Poll status
import time
while True:
    status = requests.get(f"{base_url}/api/status").json()
    print(f"Progress: {status['progress']}% - {status['message']}")

    if status['status'] == 'complete':
        break
    elif status['status'] == 'error':
        print(f"Error: {status['message']}")
        break

    time.sleep(2)

# Get results
groups = requests.get(f"{base_url}/api/groups").json()
print(f"Found {len(groups['groups'])} duplicate groups")

# Delete duplicates
files_to_delete = []
for group in groups['groups']:
    # Keep best, delete rest
    for img in group['images'][1:]:
        files_to_delete.append(img['path'])

result = requests.post(
    f"{base_url}/api/delete",
    json={
        "files": files_to_delete,
        "trashDir": "/path/to/trash"
    }
)
print(f"Moved {result.json()['moved']} files")
```

### cURL

```bash
# Start scan
curl -X POST http://localhost:5000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"directory":"/path/to/photos","threshold":10}'

# Get status
curl http://localhost:5000/api/status

# Get results
curl http://localhost:5000/api/groups

# Clear cache
curl -X POST http://localhost:5000/api/cache/clear
```

---

## Rate Limiting

Currently, there is no rate limiting implemented. The API is designed for local use only.

## Authentication

No authentication is required. The API is intended for local use only on localhost.

**Security Warning**: Do not expose the API to the internet without adding authentication and HTTPS.

---

## Versioning

The API follows semantic versioning. Current version: **2.0.0**

Breaking changes will increment the major version number.
