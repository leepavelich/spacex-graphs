"""Tests for the HTTP cache, with requests mocked out."""

import datetime
import hashlib
import http.server
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import requests

from spacex_graphs import cache
from spacex_graphs.config import HEADERS, REQUEST_TIMEOUT, STALE_CACHE_LIMIT

URL = "https://en.wikipedia.org/wiki/List_of_Starship_launches"
NOW = datetime.datetime(2026, 10, 3, 12, tzinfo=datetime.UTC)


def _response(status, content=b"", headers=None):
    response = mock.MagicMock(spec=requests.Response)
    response.__enter__.return_value = response
    response.status_code = status
    response.iter_content.return_value = [content]
    response.headers = headers or {}
    response.raise_for_status.side_effect = (
        requests.HTTPError(str(status)) if status >= 400 else None
    )
    return response


class TestFetchWithCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.get = self.enterContext(mock.patch.object(requests.Session, "get"))
        self.clock = self.enterContext(
            mock.patch.object(cache, "_now", return_value=NOW)
        )

    def _fetch(self, *parse):
        return cache.fetch_with_cache(
            URL, *parse, cache_dir=self._tmp.name, name="Starship launches"
        )

    def _prime(self, content=b"<html>cached</html>"):
        self.get.return_value = _response(200, content, {"ETag": '"v1"'})
        self._fetch()

    def test_200_writes_cache_and_returns_content(self):
        self.get.return_value = _response(200, b"fresh", {"ETag": '"v1"'})
        self.assertEqual(self._fetch(), (b"fresh", False))
        meta_path, content_path = cache._cache_paths(URL, self._tmp.name)
        self.assertTrue(os.path.exists(meta_path))
        with open(content_path, "rb") as f:
            self.assertEqual(f.read(), b"fresh")

    def test_304_returns_cached_and_sends_etag(self):
        self._prime()
        self.get.return_value = _response(304)
        self.assertEqual(self._fetch(), (b"<html>cached</html>", True))
        sent_headers = self.get.call_args.kwargs["headers"]
        self.assertEqual(sent_headers["If-None-Match"], '"v1"')

    def test_network_error_falls_back_to_cache(self):
        self._prime()
        for error in (requests.ConnectionError(), requests.Timeout()):
            with (
                self.subTest(error=type(error).__name__),
                self.assertLogs(cache.logger, "WARNING") as logs,
            ):
                self.get.side_effect = error
                self.assertEqual(self._fetch(), (b"<html>cached</html>", False))
            self.assertIn(type(error).__name__, logs.output[0])

    def test_network_error_without_cache_is_a_clear_error(self):
        self.get.side_effect = requests.ConnectionError()
        with self.assertRaises(cache.FetchError) as ctx:
            self._fetch()
        self.assertIn("no cached copy", str(ctx.exception))
        self.assertIn("check the network connection", str(ctx.exception))

    def test_server_error_falls_back_to_cache(self):
        self._prime()
        self.get.return_value = _response(503)
        with self.assertLogs(cache.logger, "WARNING") as logs:
            self.assertEqual(self._fetch(), (b"<html>cached</html>", False))
        self.assertIn("HTTP 503", logs.output[0])

    def test_missing_body_sends_no_validators(self):
        self._prime()
        os.remove(cache._cache_paths(URL, self._tmp.name)[1])
        self.get.return_value = _response(200, b"refetched")
        self.assertEqual(self._fetch(), (b"refetched", False))
        self.assertNotIn("If-None-Match", self.get.call_args.kwargs["headers"])

    def test_unusable_response_without_cache_is_a_clear_error(self):
        for status in (304, 403, 404, 503):
            with self.subTest(status=status):
                self.get.return_value = _response(status)
                with self.assertRaises(cache.FetchError) as ctx:
                    self._fetch()
                self.assertIn(f"HTTP {status}", str(ctx.exception))

    def test_corrupt_metadata_is_ignored(self):
        self._prime()
        meta_path, _ = cache._cache_paths(URL, self._tmp.name)
        for bad in ("{not json", "null", '["etag"]', '{"etag": 200}'):
            with self.subTest(bad=bad):
                with open(meta_path, "w", encoding="utf-8") as f:
                    f.write(bad)
                self.get.return_value = _response(200, b"fresh")
                self.assertEqual(self._fetch(), (b"fresh", False))
                self.assertNotIn("If-None-Match", self.get.call_args.kwargs["headers"])

    def _set_verified_at(self, when):
        meta_path = cache._cache_paths(URL, self._tmp.name)[0]
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["verified_at"] = when.isoformat()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def test_stale_cache_is_an_error_not_a_fallback(self):
        self._prime()
        too_old = NOW - STALE_CACHE_LIMIT
        self._set_verified_at(too_old - datetime.timedelta(hours=1))
        for failure in (requests.ConnectionError(), _response(403)):
            with self.subTest(failure=failure):
                if isinstance(failure, Exception):
                    self.get.side_effect = failure
                else:
                    self.get.side_effect = None
                    self.get.return_value = failure
                with self.assertRaises(cache.StaleCacheError) as ctx:
                    self._fetch()
                self.assertIn("Starship launches", str(ctx.exception))

    def test_recent_cache_still_falls_back(self):
        self._prime()
        recent = NOW - datetime.timedelta(hours=30)
        self._set_verified_at(recent)
        self.get.side_effect = requests.Timeout()
        with self.assertLogs(cache.logger, "WARNING") as logs:
            self.assertEqual(self._fetch(), (b"<html>cached</html>", False))
        self.assertIn("1d 6h ago", logs.output[0])

    def test_invalid_or_naive_timestamps_fall_back_to_file_age(self):
        self._prime()
        meta_path, content_path = cache._cache_paths(URL, self._tmp.name)
        os.utime(content_path, (0, 0))
        self.get.side_effect = requests.ConnectionError()
        for stamp in ("not a date", NOW.replace(tzinfo=None).isoformat(), None):
            with self.subTest(stamp=stamp):
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump({"verified_at": stamp}, f)
                with self.assertRaises(cache.StaleCacheError):
                    self._fetch()

    def test_cache_without_timestamp_uses_file_age(self):
        self._prime()
        meta_path, content_path = cache._cache_paths(URL, self._tmp.name)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"etag": '"v1"'}, f)
        os.utime(content_path, (0, 0))
        self.get.side_effect = requests.ConnectionError()
        with self.assertRaises(cache.StaleCacheError):
            self._fetch()

    def test_requests_identify_the_client_and_time_out(self):
        self.get.return_value = _response(200, b"fresh")
        self._fetch()
        kwargs = self.get.call_args.kwargs
        self.assertEqual(kwargs["timeout"], REQUEST_TIMEOUT)
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["headers"]["User-Agent"], HEADERS["User-Agent"])
        self.assertIn("github.com", kwargs["headers"]["User-Agent"])

    def test_last_modified_is_stored_and_sent_back(self):
        modified = "Wed, 01 Oct 2026 10:00:00 GMT"
        self.get.return_value = _response(200, b"fresh", {"Last-Modified": modified})
        self._fetch()
        self.get.return_value = _response(304)
        self._fetch()
        self.assertEqual(
            self.get.call_args.kwargs["headers"]["If-Modified-Since"], modified
        )

    def test_304_refreshes_the_confirmation_time(self):
        self._prime()
        long_ago = NOW - datetime.timedelta(days=2)
        self._set_verified_at(long_ago)
        self.get.return_value = _response(304)
        self._fetch()
        with open(cache._cache_paths(URL, self._tmp.name)[0], encoding="utf-8") as f:
            verified_at = datetime.datetime.fromisoformat(json.load(f)["verified_at"])
        self.assertEqual(verified_at, NOW)

    def test_304_with_missing_or_corrupt_body_refetches_without_validators(self):
        for problem in ("missing", "empty result", "parser error"):
            with self.subTest(problem=problem):
                self.get.side_effect = None
                self._prime(b"not usable")
                _, path = cache._cache_paths(URL, self._tmp.name)

                def get(*args, problem=problem, path=path, **kwargs):
                    if "If-None-Match" in kwargs["headers"]:
                        if problem == "missing":
                            os.unlink(path)
                        return _response(304)
                    return _response(200, b"usable", {"ETag": '"v2"'})

                def parse(content, problem=problem):
                    if content == b"usable":
                        return [content]
                    if problem == "parser error":
                        raise ValueError("bad HTML")
                    return []

                self.get.side_effect = get
                self.assertEqual(self._fetch(parse), ([b"usable"], False))
                self.assertNotIn("If-None-Match", self.get.call_args.kwargs["headers"])

    def test_304_with_unusable_body_does_not_refresh_meta_when_refetch_fails(self):
        self._prime()
        self.clock.return_value = NOW + datetime.timedelta(hours=1)
        self.get.side_effect = [_response(304), _response(503)]
        with self.assertRaisesRegex(
            cache.FetchError, r"HTTP 503.*cached copy is unusable"
        ):
            self._fetch(lambda _: [])
        meta, _ = cache._cache_paths(URL, self._tmp.name)
        self.assertEqual(cache._read_meta(meta)["verified_at"], NOW.isoformat())

    def test_response_size_cap_stops_reading_before_parsing_or_caching(self):
        response = _response(200)

        def chunks():
            yield b"ab"
            yield b"cd"
            raise AssertionError("read more bytes after reaching the size cap")

        response.iter_content.return_value = chunks()
        self.get.return_value = response
        parser = mock.Mock()
        with (
            mock.patch.object(cache, "MAX_RESPONSE_BYTES", 3),
            self.assertRaisesRegex(cache.FetchError, "body exceeds 3 bytes"),
        ):
            self._fetch(parser)
        response.iter_content.assert_called_once_with(chunk_size=65536)
        response.__exit__.assert_called_once()
        parser.assert_not_called()
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_response_size_cap_allows_exact_limit(self):
        self.get.return_value = _response(200, b"abc")
        with mock.patch.object(cache, "MAX_RESPONSE_BYTES", 3):
            self.assertEqual(self._fetch(), (b"abc", False))

    def test_interrupted_stream_falls_back_to_cache(self):
        self._prime()
        response = _response(200)
        response.iter_content.side_effect = requests.exceptions.ChunkedEncodingError
        self.get.return_value = response
        with self.assertLogs(cache.logger, "WARNING"):
            self.assertEqual(self._fetch(), (b"<html>cached</html>", False))

    def test_parse_result_is_returned(self):
        self.get.return_value = _response(200, b"a,b,c")
        result, _ = self._fetch(lambda c: c.decode().split(","))
        self.assertEqual(result, ["a", "b", "c"])

    def test_unusable_download_keeps_the_good_cached_copy(self):
        self._prime(b"good")
        self.get.return_value = _response(200, b"maintenance page")

        def parse(content):
            return [] if content == b"maintenance page" else [content]

        with self.assertLogs(cache.logger, "WARNING") as logs:
            result, _ = self._fetch(parse)
        self.assertEqual(result, [b"good"])
        self.assertIn("nothing usable", logs.output[0])
        with open(cache._cache_paths(URL, self._tmp.name)[1], "rb") as f:
            self.assertEqual(f.read(), b"good")

    def test_unusable_download_without_cache_is_an_error(self):
        self.get.return_value = _response(200, b"maintenance page")
        with self.assertRaises(cache.FetchError):
            self._fetch(lambda content: [])

    def test_cache_writes_leave_no_temporary_files(self):
        self._prime()
        self.assertFalse(
            [name for name in os.listdir(self._tmp.name) if name.endswith(".tmp")]
        )

    def test_failed_atomic_replace_preserves_cache_and_removes_tempfile(self):
        self._prime(b"original")
        _, path = cache._cache_paths(URL, self._tmp.name)
        before = sorted(os.listdir(self._tmp.name))
        with (
            mock.patch.object(os, "replace", side_effect=OSError("disk error")),
            self.assertRaises(OSError),
        ):
            cache._write_atomically(path, b"replacement")
        self.assertEqual(sorted(os.listdir(self._tmp.name)), before)
        self.assertEqual(cache._read_content(path), b"original")

    def test_stale_limit_boundary(self):
        self._prime()
        now = NOW
        self.get.side_effect = requests.ConnectionError()
        minute = datetime.timedelta(minutes=1)
        self._set_verified_at(now - STALE_CACHE_LIMIT)
        with self.assertLogs(cache.logger, "WARNING"):
            self._fetch()
        self._set_verified_at(now - STALE_CACHE_LIMIT - minute)
        with self.assertRaises(cache.StaleCacheError):
            self._fetch()


class TestCachePaths(unittest.TestCase):
    def test_each_page_gets_its_own_cache_files(self):
        first = cache._cache_paths(URL, "dir")
        second = cache._cache_paths(URL + "_(2024)", "dir")
        self.assertEqual(len({*first, *second}), 4)

    def test_cache_keys_are_compatible_and_not_used_for_security(self):
        with mock.patch.object(hashlib, "md5", wraps=hashlib.md5) as md5:
            cache._cache_paths(URL, "dir")
        md5.assert_called_once_with(URL.encode(), usedforsecurity=False)


def _retry_handler(queue, statuses):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status, retry_after = next(queue, (500, None))
            statuses.append(status)
            self.send_response(status)
            if retry_after is not None:
                self.send_header("Retry-After", retry_after)
            self.end_headers()
            if status == 200:
                self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    return Handler


class TestHttpRetries(unittest.TestCase):
    def test_requests_retry_after_and_back_off_with_a_bounded_budget(self):
        for responses, expected_sleeps in (
            ([(429, "2"), (503, None), (200, None)], [2, 1.0]),
            ([(502, None), (504, "3600"), (503, None)], [30]),
        ):
            with (
                self.subTest(responses=responses),
                tempfile.TemporaryDirectory() as tmp,
            ):
                queue = iter(responses)
                statuses: list[int] = []

                with http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), _retry_handler(queue, statuses)
                ) as server:
                    thread = threading.Thread(target=server.serve_forever, args=(0.01,))
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}/"
                        with mock.patch("urllib3.util.retry.time.sleep") as sleep:
                            if responses[-1][0] == 200:
                                self.assertEqual(
                                    cache.fetch_with_cache(url, cache_dir=tmp),
                                    (b"ok", False),
                                )
                            else:
                                with self.assertRaisesRegex(
                                    cache.FetchError, "HTTP 503"
                                ):
                                    cache.fetch_with_cache(url, cache_dir=tmp)
                        self.assertEqual(
                            sleep.call_args_list,
                            [mock.call(s) for s in expected_sleeps],
                        )
                        self.assertEqual(statuses, [status for status, _ in responses])
                    finally:
                        server.shutdown()
                        thread.join()


if __name__ == "__main__":
    unittest.main()
