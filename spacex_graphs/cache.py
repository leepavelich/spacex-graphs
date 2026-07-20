"""HTTP caching (ETag/Last-Modified) and change detection for launch data."""

import datetime
import hashlib
import json
import os

import requests

from spacex_graphs.config import CACHE_DIR, HEADERS, REQUEST_TIMEOUT, WIKIPEDIA_PAGES


def _cache_paths(url):
    """Returns the (metadata, content) cache file paths for a URL."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    return (
        os.path.join(CACHE_DIR, f"{cache_key}.json"),
        os.path.join(CACHE_DIR, f"{cache_key}.html"),
    )


def fetch_with_cache(url):
    """Fetches a URL with ETag/Last-Modified caching support.

    Returns a tuple (content, not_modified) where not_modified is True when
    the server confirmed the cached copy is still current (HTTP 304).
    """
    cache_meta_path, cache_content_path = _cache_paths(url)
    page_name = WIKIPEDIA_PAGES.get(url, url)

    cached_meta = {}
    if os.path.exists(cache_meta_path):
        with open(cache_meta_path, "r", encoding="utf-8") as f:
            cached_meta = json.load(f)

    request_headers = HEADERS.copy()
    if "etag" in cached_meta:
        request_headers["If-None-Match"] = cached_meta["etag"]
    if "last-modified" in cached_meta:
        request_headers["If-Modified-Since"] = cached_meta["last-modified"]

    response = requests.get(url, headers=request_headers, timeout=REQUEST_TIMEOUT)

    if response.status_code == 304 and os.path.exists(cache_content_path):
        print(f"  ✓ {page_name} (cached)")
        with open(cache_content_path, "rb") as f:
            return f.read(), True

    if response.status_code == 200:
        print(f"  ↓ {page_name} (downloaded)")
        with open(cache_content_path, "wb") as f:
            f.write(response.content)

        meta = {"url": url}
        if "ETag" in response.headers:
            meta["etag"] = response.headers["ETag"]
        if "Last-Modified" in response.headers:
            meta["last-modified"] = response.headers["Last-Modified"]
        with open(cache_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        return response.content, False

    # Fallback to cached content if the request failed but a cache exists
    if os.path.exists(cache_content_path):
        print(f"  ! {page_name} (using cached - request failed)")
        with open(cache_content_path, "rb") as f:
            return f.read(), False

    response.raise_for_status()
    return response.content, False


def _hash_file_path():
    return os.path.join(CACHE_DIR, "data_hash.txt")


def has_previous_run():
    """Returns True if a data hash from a previous run exists."""
    return os.path.exists(_hash_file_path())


def compute_data_hash(records):
    """Computes a hash of the launch data and current date for change detection."""
    # Include current date since graphs extend to today
    current_date = datetime.date.today().isoformat()
    data_str = json.dumps(sorted(records), sort_keys=True, default=str)
    combined = f"{current_date}:{data_str}"
    return hashlib.sha256(combined.encode()).hexdigest()


def has_data_changed(records):
    """Checks if data has changed since the last run, updating the stored hash."""
    hash_file = _hash_file_path()
    new_hash = compute_data_hash(records)

    if os.path.exists(hash_file):
        with open(hash_file, "r", encoding="utf-8") as f:
            old_hash = f.read().strip()
        if old_hash == new_hash:
            return False

    with open(hash_file, "w", encoding="utf-8") as f:
        f.write(new_hash)
    return True


def write_last_run_date():
    """Records the date the graphs were last checked/generated."""
    date_file = os.path.join(CACHE_DIR, "last_run_date.txt")
    with open(date_file, "w", encoding="utf-8") as f:
        f.write(datetime.date.today().isoformat())
