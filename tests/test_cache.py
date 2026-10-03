"""Tests for the HTTP cache, with requests mocked out."""

import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

import requests

from spacex_graphs import cache
from spacex_graphs.config import HEADERS, REQUEST_TIMEOUT, STALE_CACHE_LIMIT

URL = "https://en.wikipedia.org/wiki/List_of_Starship_launches"


def _response(status, content=b"", headers=None):
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.content = content
    response.headers = headers or {}
    response.raise_for_status.side_effect = (
        requests.HTTPError(str(status)) if status >= 400 else None
    )
    return response


class TestFetchWithCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.get = self.enterContext(mock.patch("spacex_graphs.cache.requests.get"))

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
        with open(
            cache._cache_paths(URL, self._tmp.name)[0], "w", encoding="utf-8"
        ) as f:
            f.write("{not json")
        self.get.return_value = _response(200, b"fresh")
        self.assertEqual(self._fetch(), (b"fresh", False))

    def _set_verified_at(self, when):
        meta_path = cache._cache_paths(URL, self._tmp.name)[0]
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["verified_at"] = when.isoformat()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def test_fetches_record_when_the_copy_was_confirmed_current(self):
        self._prime()
        self.get.return_value = _response(304)
        self._fetch()
        with open(cache._cache_paths(URL, self._tmp.name)[0], encoding="utf-8") as f:
            verified_at = datetime.datetime.fromisoformat(json.load(f)["verified_at"])
        age = datetime.datetime.now(datetime.UTC) - verified_at
        self.assertLess(age, datetime.timedelta(minutes=1))

    def test_stale_cache_is_an_error_not_a_fallback(self):
        self._prime()
        too_old = datetime.datetime.now(datetime.UTC) - STALE_CACHE_LIMIT
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
        recent = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=30)
        self._set_verified_at(recent)
        self.get.side_effect = requests.Timeout()
        with self.assertLogs(cache.logger, "WARNING") as logs:
            self.assertEqual(self._fetch(), (b"<html>cached</html>", False))
        self.assertIn("1d 6h ago", logs.output[0])

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
        long_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)
        self._set_verified_at(long_ago)
        self.get.return_value = _response(304)
        self._fetch()
        with open(cache._cache_paths(URL, self._tmp.name)[0], encoding="utf-8") as f:
            verified_at = datetime.datetime.fromisoformat(json.load(f)["verified_at"])
        self.assertGreater(verified_at, long_ago + datetime.timedelta(days=1))

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

    def test_stale_limit_boundary(self):
        self._prime()
        now = datetime.datetime.now(datetime.UTC)
        self.get.side_effect = requests.ConnectionError()
        minute = datetime.timedelta(minutes=1)
        self._set_verified_at(now - STALE_CACHE_LIMIT + minute)
        with self.assertLogs(cache.logger, "WARNING"):
            self._fetch()
        self._set_verified_at(now - STALE_CACHE_LIMIT - minute)
        with self.assertRaises(cache.StaleCacheError):
            self._fetch()


if __name__ == "__main__":
    unittest.main()
