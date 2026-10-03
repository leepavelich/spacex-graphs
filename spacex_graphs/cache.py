"""HTTP caching (ETag/Last-Modified) and change detection for launch data."""

import datetime
import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterable
from typing import Any, TypeVar, overload

import requests

from spacex_graphs.config import (
    CACHE_DIR,
    HEADERS,
    REQUEST_TIMEOUT,
    STALE_CACHE_LIMIT,
    WIKIPEDIA_PAGES,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _cache_paths(url: str) -> tuple[str, str]:
    """Returns the (metadata, content) cache file paths for a URL."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    return (
        os.path.join(CACHE_DIR, f"{cache_key}.json"),
        os.path.join(CACHE_DIR, f"{cache_key}.html"),
    )


class StaleCacheError(RuntimeError):
    """Raised when a page can't be fetched and its cached copy is too old."""


class FetchError(RuntimeError):
    """Raised when a page can't be fetched and there is no cached copy."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _read_meta(cache_meta_path: str) -> dict[str, str]:
    try:
        with open(cache_meta_path, encoding="utf-8") as f:
            meta: dict[str, str] = json.load(f)
            return meta
    except (OSError, ValueError):
        return {}


def _write_atomically(path: str, data: bytes) -> None:
    """Writes via a temporary file, so an interrupted run can't leave a
    truncated file behind."""
    temporary = f"{path}.tmp"
    with open(temporary, "wb") as f:
        f.write(data)
    os.replace(temporary, path)


def _write_meta(cache_meta_path: str, meta: dict[str, str]) -> None:
    _write_atomically(cache_meta_path, json.dumps(meta).encode())


def _read_content(cache_content_path: str) -> bytes:
    with open(cache_content_path, "rb") as f:
        return f.read()


def _verified_at(meta: dict[str, str], cache_content_path: str) -> datetime.datetime:
    """When the cached copy was last confirmed current by the server.

    Caches written before this was recorded fall back to the file's mtime.
    """
    try:
        return datetime.datetime.fromisoformat(meta["verified_at"])
    except (KeyError, ValueError):
        mtime = os.path.getmtime(cache_content_path)
        return datetime.datetime.fromtimestamp(mtime, datetime.UTC)


def _fall_back_to_cache(
    page_name: str, reason: str, meta: dict[str, str], cache_content_path: str
) -> bytes:
    """Serves the cached copy after a failed fetch, unless it is too old."""
    age = _now() - _verified_at(meta, cache_content_path)
    if age > STALE_CACHE_LIMIT:
        raise StaleCacheError(
            f"{page_name} could not be fetched ({reason}) and the cached copy was "
            f"last confirmed current {age.days} days ago"
        )
    logger.warning(
        "  ! %s (using cached - %s; last confirmed %s ago)",
        page_name,
        reason,
        _format_age(age),
    )
    return _read_content(cache_content_path)


def _format_age(age: datetime.timedelta) -> str:
    hours = int(age.total_seconds() // 3600)
    return f"{hours // 24}d {hours % 24}h" if hours >= 24 else f"{hours}h"


def _unparsed(content: bytes) -> bytes:
    return content


@overload
def fetch_with_cache(url: str) -> tuple[bytes, bool]: ...


@overload
def fetch_with_cache(url: str, parse: Callable[[bytes], T]) -> tuple[T, bool]: ...


def fetch_with_cache(
    url: str, parse: Callable[[bytes], Any] = _unparsed
) -> tuple[Any, bool]:
    """Fetches a URL with ETag/Last-Modified caching and parses it.

    Returns (parse(content), not_modified), where not_modified is True when
    the server confirmed the cached copy is still current (HTTP 304). A new
    download replaces the cached copy only if parse finds something in it
    (a non-empty result), so an error or maintenance page served with HTTP
    200 can't overwrite a good copy; it counts as a failed fetch instead.

    When the fetch fails, returns the parsed cached copy if it was confirmed
    current within STALE_CACHE_LIMIT and raises StaleCacheError otherwise;
    with no cached copy at all, it raises FetchError.
    """
    cache_meta_path, cache_content_path = _cache_paths(url)
    page_name = WIKIPEDIA_PAGES.get(url, url)

    has_cached_content = os.path.exists(cache_content_path)
    # Only send validators when the body they describe is on disk; otherwise a
    # 304 would leave nothing to return
    cached_meta = _read_meta(cache_meta_path) if has_cached_content else {}

    def fall_back(reason: str) -> tuple[Any, bool]:
        if not has_cached_content:
            raise FetchError(
                f"{page_name} could not be fetched ({reason}) and there is no "
                "cached copy to fall back to"
            )
        content = _fall_back_to_cache(
            page_name, reason, cached_meta, cache_content_path
        )
        return parse(content), False

    request_headers = HEADERS.copy()
    if "etag" in cached_meta:
        request_headers["If-None-Match"] = cached_meta["etag"]
    if "last-modified" in cached_meta:
        request_headers["If-Modified-Since"] = cached_meta["last-modified"]

    try:
        response = requests.get(url, headers=request_headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        return fall_back(f"{type(error).__name__}; check the network connection")

    if response.status_code == 304 and has_cached_content:
        logger.info("  ✓ %s (cached)", page_name)
        _write_meta(cache_meta_path, {**cached_meta, "verified_at": _now().isoformat()})
        return parse(_read_content(cache_content_path)), True

    if response.status_code != 200:
        return fall_back(f"HTTP {response.status_code}")

    result = parse(response.content)
    if not result:
        return fall_back("HTTP 200, but nothing usable in the page")

    logger.info("  ↓ %s (downloaded)", page_name)
    _write_atomically(cache_content_path, response.content)
    meta = {"url": url, "verified_at": _now().isoformat()}
    if "ETag" in response.headers:
        meta["etag"] = response.headers["ETag"]
    if "Last-Modified" in response.headers:
        meta["last-modified"] = response.headers["Last-Modified"]
    _write_meta(cache_meta_path, meta)
    return result, False


def _hash_file_path() -> str:
    return os.path.join(CACHE_DIR, "data_hash.txt")


def compute_data_hash(records: Iterable[tuple[Any, ...]], today: datetime.date) -> str:
    """Hashes the launch records (any tuples) together with today's date.

    The date is included because the cumulative graph's current-year line
    extends to today, so the outputs legitimately change once per day even
    when no launch data does.
    """
    # Sort the serialized records: records themselves can't be ordered once a
    # field may be None
    data_str = json.dumps(sorted(json.dumps(r, default=str) for r in records))
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
