"""Fetches and caches HTTP pages with conditional requests and bounded staleness."""

import datetime
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from typing import IO, overload

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from spacex_graphs.config import (
    HEADERS,
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT,
    STALE_CACHE_LIMIT,
)
from spacex_graphs.errors import DataError

logger = logging.getLogger(__name__)


def _cache_paths(url: str, cache_dir: str) -> tuple[str, str]:
    """Returns the (metadata, content) cache file paths for a URL."""
    cache_key = hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()
    return (
        os.path.join(cache_dir, f"{cache_key}.json"),
        os.path.join(cache_dir, f"{cache_key}.html"),
    )


class StaleCacheError(DataError):
    """Raised when a page can't be fetched and its cached copy is too old."""


class FetchError(DataError):
    """Raised when a page can neither be fetched nor recovered from cache."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _read_meta(cache_meta_path: str) -> dict[str, str]:
    try:
        with open(cache_meta_path, encoding="utf-8") as f:
            raw: object = json.load(f)
    except OSError, ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    entries: Mapping[object, object] = raw
    meta: dict[str, str] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return {}
        meta[key] = value
    return meta


@contextmanager
def atomic_writer(path: str) -> Iterator[IO[bytes]]:
    """Writes beside the destination, replacing it only after a successful write."""
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=os.path.dirname(path) or ".", suffix=".tmp", delete=False
        ) as f:
            temporary = f.name
            yield f
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary)


def _write_atomically(path: str, data: bytes) -> None:
    with atomic_writer(path) as f:
        f.write(data)


def _write_meta(cache_meta_path: str, meta: dict[str, str]) -> None:
    _write_atomically(cache_meta_path, json.dumps(meta).encode())


def _read_content(cache_content_path: str) -> bytes:
    with open(cache_content_path, "rb") as f:
        return f.read()


def _verified_at(meta: dict[str, str], cache_content_path: str) -> datetime.datetime:
    """When the cached copy was last confirmed current, or its mtime for old caches."""
    try:
        verified_at = datetime.datetime.fromisoformat(meta["verified_at"])
        if verified_at.tzinfo is not None:
            return verified_at
    except KeyError, TypeError, ValueError:
        pass
    mtime = os.path.getmtime(cache_content_path)
    return datetime.datetime.fromtimestamp(mtime, datetime.UTC)


def _format_age(age: datetime.timedelta) -> str:
    hours = int(age.total_seconds() // 3600)
    return f"{hours // 24}d {hours % 24}h" if hours >= 24 else f"{hours}h"


def _session() -> requests.Session:
    """A session per fetch, avoiding shared mutable state across workers."""
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        backoff_max=2,
        retry_after_max=30,
        allowed_methods=frozenset({"GET"}),
        status_forcelist=(429, 502, 503, 504),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    for scheme in ("https://", "http://"):
        session.mount(scheme, HTTPAdapter(max_retries=retry))
    return session


def _response_content(response: requests.Response) -> bytes | None:
    """Reads at most the configured number of decoded bytes, or rejects the body."""
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
            return None
        body.extend(chunk)
    return bytes(body)


def _cached_result[T](path: str, parse: Callable[[bytes], T]) -> T | None:
    """Reads a usable cached copy without letting corruption mask a fetch failure."""
    try:
        result = parse(_read_content(path))
    except OSError, ValueError, DataError:
        return None
    return result if result else None


@overload
def fetch_with_cache(
    url: str, *, cache_dir: str, name: str | None = None
) -> tuple[bytes, bool]: ...


@overload
def fetch_with_cache[T](
    url: str, parse: Callable[[bytes], T], *, cache_dir: str, name: str | None = None
) -> tuple[T, bool]: ...


def fetch_with_cache[T](
    url: str,
    parse: Callable[[bytes], T] | None = None,
    *,
    cache_dir: str,
    name: str | None = None,
) -> tuple[T | bytes, bool]:
    """Returns the parsed body (or raw bytes) and whether HTTP 304 confirmed it.

    Only usable responses replace the cache. If a cached body can't be used
    after a 304, try an unconditional request. Other fetch failures can use a
    usable copy confirmed within STALE_CACHE_LIMIT.
    """
    parse_content: Callable[[bytes], T | bytes] = (
        parse if parse is not None else lambda content: content
    )
    cache_meta_path, cache_content_path = _cache_paths(url, cache_dir)
    page_name = name or url

    # Only send validators if their body exists.
    has_cached_content = os.path.exists(cache_content_path)
    cached_meta = _read_meta(cache_meta_path) if has_cached_content else {}
    cache_unusable = False

    def fall_back(reason: str) -> tuple[T | bytes, bool]:
        if not has_cached_content:
            raise FetchError(
                f"{page_name} could not be fetched ({reason}) and there is no "
                "cached copy to fall back to"
            )
        if not cache_unusable:
            result = _cached_result(cache_content_path, parse_content)
            if result is not None:
                age = _now() - _verified_at(cached_meta, cache_content_path)
                if age > STALE_CACHE_LIMIT:
                    raise StaleCacheError(
                        f"{page_name} could not be fetched ({reason}) and the cached "
                        f"copy was last confirmed current {age.days} days ago"
                    )
                logger.warning(
                    "  ! %s (using cached - %s; last confirmed %s ago)",
                    page_name,
                    reason,
                    _format_age(age),
                )
                return result, False
        raise FetchError(
            f"{page_name} could not be fetched ({reason}) and the cached copy is unusable"
        )

    headers = HEADERS.copy()
    for key, header in (
        ("etag", "If-None-Match"),
        ("last-modified", "If-Modified-Since"),
    ):
        if key in cached_meta:
            headers[header] = cached_meta[key]

    try:
        with _session() as session:
            while True:
                with session.get(
                    url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True
                ) as response:
                    if response.status_code == 304 and headers != HEADERS:
                        result = _cached_result(cache_content_path, parse_content)
                        if result is not None:
                            _write_meta(
                                cache_meta_path,
                                {**cached_meta, "verified_at": _now().isoformat()},
                            )
                            logger.info("  ✓ %s (cached)", page_name)
                            return result, True
                        cache_unusable = True
                        headers = HEADERS.copy()
                        continue

                    if response.status_code != 200:
                        return fall_back(f"HTTP {response.status_code}")

                    content = _response_content(response)
                    if content is None:
                        return fall_back(
                            f"HTTP 200 body exceeds {MAX_RESPONSE_BYTES} bytes"
                        )
                    result = parse_content(content)
                    if not result:
                        return fall_back("HTTP 200, but nothing usable in the page")

                    meta = {"url": url, "verified_at": _now().isoformat()}
                    if "ETag" in response.headers:
                        meta["etag"] = response.headers["ETag"]
                    if "Last-Modified" in response.headers:
                        meta["last-modified"] = response.headers["Last-Modified"]
                    _write_atomically(cache_content_path, content)
                    _write_meta(cache_meta_path, meta)
                    logger.info("  ↓ %s (downloaded)", page_name)
                    return result, False
    except requests.RequestException as error:
        return fall_back(f"{type(error).__name__}; check the network connection")
