"""Tests for the HTTP cache, with requests mocked out."""

import os
import tempfile
import unittest
from unittest import mock

import requests

from spacex_graphs import cache

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
        patcher = mock.patch.object(cache, "CACHE_DIR", self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.get = self.enterContext(mock.patch.object(cache.requests, "get"))

    def _prime(self, content=b"<html>cached</html>"):
        self.get.return_value = _response(200, content, {"ETag": '"v1"'})
        cache.fetch_with_cache(URL)

    def test_200_writes_cache_and_returns_content(self):
        self.get.return_value = _response(200, b"fresh", {"ETag": '"v1"'})
        self.assertEqual(cache.fetch_with_cache(URL), (b"fresh", False))
        meta_path, content_path = cache._cache_paths(URL)
        self.assertTrue(os.path.exists(meta_path))
        with open(content_path, "rb") as f:
            self.assertEqual(f.read(), b"fresh")

    def test_304_returns_cached_and_sends_etag(self):
        self._prime()
        self.get.return_value = _response(304)
        self.assertEqual(cache.fetch_with_cache(URL), (b"<html>cached</html>", True))
        sent_headers = self.get.call_args.kwargs["headers"]
        self.assertEqual(sent_headers["If-None-Match"], '"v1"')

    def test_network_error_falls_back_to_cache(self):
        self._prime()
        for error in (requests.ConnectionError(), requests.Timeout()):
            with self.subTest(error=type(error).__name__):
                self.get.side_effect = error
                self.assertEqual(
                    cache.fetch_with_cache(URL), (b"<html>cached</html>", False)
                )

    def test_network_error_without_cache_raises(self):
        self.get.side_effect = requests.ConnectionError()
        with self.assertRaises(requests.ConnectionError):
            cache.fetch_with_cache(URL)

    def test_server_error_falls_back_to_cache(self):
        self._prime()
        self.get.return_value = _response(503)
        self.assertEqual(cache.fetch_with_cache(URL), (b"<html>cached</html>", False))

    def test_missing_body_sends_no_validators(self):
        self._prime()
        os.remove(cache._cache_paths(URL)[1])
        self.get.return_value = _response(200, b"refetched")
        self.assertEqual(cache.fetch_with_cache(URL), (b"refetched", False))
        self.assertNotIn("If-None-Match", self.get.call_args.kwargs["headers"])

    def test_unexpected_304_without_cache_raises(self):
        self.get.return_value = _response(304)
        with self.assertRaises(requests.HTTPError):
            cache.fetch_with_cache(URL)

    def test_corrupt_metadata_is_ignored(self):
        self._prime()
        with open(cache._cache_paths(URL)[0], "w", encoding="utf-8") as f:
            f.write("{not json")
        self.get.return_value = _response(200, b"fresh")
        self.assertEqual(cache.fetch_with_cache(URL), (b"fresh", False))


if __name__ == "__main__":
    unittest.main()
