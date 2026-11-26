"""Fetches and caches HTTP pages with conditional requests and bounded staleness."""

import datetime
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import IO, Final, overload

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


# Outputs are published and cached pages are public, so both are readable by
# everyone, like a file written with open() under the usual 022 umask, rather
# than owner-only like NamedTemporaryFile's default. That keeps them readable
# from a bind mount or by another user, such as a CI step after the container.
DEFAULT_FILE_MODE: Final = 0o644


@contextmanager
def atomic_writer(path: str, mode: int = DEFAULT_FILE_MODE) -> Iterator[IO[bytes]]:
    """Writes beside the destination, replacing it only after a successful write.

    The file gets the permission bits in mode, whatever the process umask.
    """
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=os.path.dirname(path) or ".", suffix=".tmp", delete=False
        ) as f:
            temporary = f.name
            os.chmod(temporary, mode)
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


@dataclass
class _CacheEntry:
    """A page's cache files and what is known about them during one fetch."""

    url: str
    name: str
    meta_path: str
    content_path: str
    has_content: bool
    meta: dict[str, str]
    # Set once a 304 confirmed the cached body but it couldn't be used
    unusable: bool = False

    def validators(self) -> dict[str, str]:
        """Conditional request headers, sent only when the cached body exists."""
        return {
            header: self.meta[key]
            for key, header in (
                ("etag", "If-None-Match"),
                ("last-modified", "If-Modified-Since"),
            )
            if key in self.meta
        }


def _open_entry(url: str, cache_dir: str, name: str | None) -> _CacheEntry:
    meta_path, content_path = _cache_paths(url, cache_dir)
    has_content = os.path.exists(content_path)
    return _CacheEntry(
        url=url,
        name=name or url,
        meta_path=meta_path,
        content_path=content_path,
        has_content=has_content,
        meta=_read_meta(meta_path) if has_content else {},
    )


def _cache_age(entry: _CacheEntry) -> datetime.timedelta:
    """How long ago the cached copy was last confirmed current.

    A confirmation time in the future, from a clock that was ahead, counts as
    just now rather than as a negative age.
    """
    age = _now() - _verified_at(entry.meta, entry.content_path)
    return max(age, datetime.timedelta(0))


def _fall_back[T](
    entry: _CacheEntry, parse: Callable[[bytes], T], reason: str
) -> tuple[T, bool]:
    """Returns the cached copy after a failed fetch, if it is usable and recent."""
    if not entry.has_content:
        raise FetchError(
            f"{entry.name} could not be fetched ({reason}) and there is no "
            "cached copy to fall back to"
        )
    result = None if entry.unusable else _cached_result(entry.content_path, parse)
    if result is None:
        raise FetchError(
            f"{entry.name} could not be fetched ({reason}) and the cached copy "
            "is unusable"
        )
    age = _cache_age(entry)
    if age > STALE_CACHE_LIMIT:
        raise StaleCacheError(
            f"{entry.name} could not be fetched ({reason}) and the cached copy "
            f"was last confirmed current {_format_age(age)} ago"
        )
    logger.warning(
        "  ! %s (using cached - %s; last confirmed %s ago)",
        entry.name,
        reason,
        _format_age(age),
    )
    return result, False


def _confirm_cached[T](entry: _CacheEntry, parse: Callable[[bytes], T]) -> T | None:
    """After a 304, returns the cached copy and records that it is current.

    Returns None, and marks the entry unusable, if the cached body can't be
    used after all.
    """
    result = _cached_result(entry.content_path, parse)
    if result is None:
        entry.unusable = True
        return None
    _write_meta(entry.meta_path, {**entry.meta, "verified_at": _now().isoformat()})
    logger.info("  ✓ %s (cached)", entry.name)
    return result


def _store(entry: _CacheEntry, response: requests.Response, content: bytes) -> None:
    """Caches a usable download with its validators."""
    meta = {"url": entry.url, "verified_at": _now().isoformat()}
    if "ETag" in response.headers:
        meta["etag"] = response.headers["ETag"]
    if "Last-Modified" in response.headers:
        meta["last-modified"] = response.headers["Last-Modified"]
    _write_atomically(entry.content_path, content)
    _write_meta(entry.meta_path, meta)
    logger.info("  ↓ %s (downloaded)", entry.name)


def _use_response[T](
    entry: _CacheEntry, parse: Callable[[bytes], T], response: requests.Response
) -> tuple[T, bool]:
    """Parses and caches a usable 200 response, or falls back to the cache."""
    if response.status_code != 200:
        return _fall_back(entry, parse, f"HTTP {response.status_code}")
    content = _response_content(response)
    if content is None:
        return _fall_back(
            entry, parse, f"HTTP 200 body exceeds {MAX_RESPONSE_BYTES} bytes"
        )
    result = parse(content)
    if not result:
        return _fall_back(entry, parse, "HTTP 200, but nothing usable in the page")
    _store(entry, response, content)
    return result, False


def _get(
    session: requests.Session, url: str, headers: Mapping[str, str]
) -> requests.Response:
    return session.get(url, headers=dict(headers), timeout=REQUEST_TIMEOUT, stream=True)


def _request[T](
    session: requests.Session, entry: _CacheEntry, parse: Callable[[bytes], T]
) -> tuple[T, bool]:
    """Fetches the page, conditionally when there is a cached copy.

    If a 304 confirms a cached body that can't be used, asks once more
    without validators.
    """
    validators = entry.validators()
    if validators:
        with _get(session, entry.url, {**HEADERS, **validators}) as response:
            if response.status_code != 304:
                return _use_response(entry, parse, response)
            result = _confirm_cached(entry, parse)
            if result is not None:
                return result, True
    with _get(session, entry.url, HEADERS) as response:
        return _use_response(entry, parse, response)


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
    entry = _open_entry(url, cache_dir, name)
    try:
        with _session() as session:
            return _request(session, entry, parse_content)
    except requests.RequestException as error:
        return _fall_back(
            entry,
            parse_content,
            f"{type(error).__name__}; check the network connection",
        )
