"""HTTP caching (ETag/Last-Modified) and change detection for launch data."""

import datetime
import hashlib
import json
import logging
import os
from collections.abc import Iterable
from typing import Any

import requests

from spacex_graphs.config import CACHE_DIR, HEADERS, REQUEST_TIMEOUT, WIKIPEDIA_PAGES

logger = logging.getLogger(__name__)


def _cache_paths(url: str) -> tuple[str, str]:
    """Returns the (metadata, content) cache file paths for a URL."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    return (
        os.path.join(CACHE_DIR, f"{cache_key}.json"),
        os.path.join(CACHE_DIR, f"{cache_key}.html"),
    )


def fetch_with_cache(url: str) -> tuple[bytes, bool]:
    """Fetches a URL with ETag/Last-Modified caching support.

    Returns a tuple (content, not_modified) where not_modified is True when
    the server confirmed the cached copy is still current (HTTP 304).
    """
    cache_meta_path, cache_content_path = _cache_paths(url)
    page_name = WIKIPEDIA_PAGES.get(url, url)

    has_cached_content = os.path.exists(cache_content_path)

    cached_meta: dict[str, str] = {}
    # Only send validators when the body they describe is on disk; otherwise a
    # 304 would leave nothing to return
    if has_cached_content and os.path.exists(cache_meta_path):
        try:
            with open(cache_meta_path, encoding="utf-8") as f:
                cached_meta = json.load(f)
        except (OSError, ValueError):
            cached_meta = {}

    request_headers = HEADERS.copy()
    if "etag" in cached_meta:
        request_headers["If-None-Match"] = cached_meta["etag"]
    if "last-modified" in cached_meta:
        request_headers["If-Modified-Since"] = cached_meta["last-modified"]

    try:
        response = requests.get(url, headers=request_headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        if not has_cached_content:
            raise
        logger.warning("  ! %s (using cached - %s)", page_name, type(error).__name__)
        with open(cache_content_path, "rb") as f:
            return f.read(), False

    if response.status_code == 304 and has_cached_content:
        logger.info("  ✓ %s (cached)", page_name)
        with open(cache_content_path, "rb") as f:
            return f.read(), True

    if response.status_code == 200:
        logger.info("  ↓ %s (downloaded)", page_name)
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

    # Fallback to cached content if the server returned an error status
    if has_cached_content:
        logger.warning(
            "  ! %s (using cached - HTTP %s)", page_name, response.status_code
        )
        with open(cache_content_path, "rb") as f:
            return f.read(), False

    response.raise_for_status()
    # Not an error status, but not usable either (e.g. a 304 with no cached body)
    raise requests.HTTPError(
        f"Unexpected HTTP {response.status_code} for {url}", response=response
    )


def _hash_file_path() -> str:
    return os.path.join(CACHE_DIR, "data_hash.txt")


def compute_data_hash(records: Iterable[tuple[Any, ...]], today: datetime.date) -> str:
    """Hashes the launch records (any tuples) together with today's date.

    The date is included because the cumulative graph's current-year line
    extends to today, so the outputs legitimately change once per day even
    when no launch data does.
    """
    data_str = json.dumps(sorted(records), sort_keys=True, default=str)
    combined = f"{today.isoformat()}:{data_str}"
    return hashlib.sha256(combined.encode()).hexdigest()


def has_data_changed(records: Iterable[tuple[Any, ...]], today: datetime.date) -> bool:
    """Checks if the outputs would differ from the last successful run.

    Does not update the stored hash; call save_data_hash once the outputs
    have been written, so a failed run is retried instead of skipped.
    """
    hash_file = _hash_file_path()
    if not os.path.exists(hash_file):
        return True
    with open(hash_file, encoding="utf-8") as f:
        old_hash = f.read().strip()
    return old_hash != compute_data_hash(records, today)


def save_data_hash(records: Iterable[tuple[Any, ...]], today: datetime.date) -> None:
    """Records the data hash after outputs were generated successfully."""
    with open(_hash_file_path(), "w", encoding="utf-8") as f:
        f.write(compute_data_hash(records, today))


def write_last_run_date(today: datetime.date) -> None:
    """Records the date the graphs were last checked/generated."""
    date_file = os.path.join(CACHE_DIR, "last_run_date.txt")
    with open(date_file, "w", encoding="utf-8") as f:
        f.write(today.isoformat())
