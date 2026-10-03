"""Tests for the skip-when-unchanged data hash."""

import datetime
import tempfile
import unittest
from unittest import mock

from spacex_graphs import cache
from spacex_graphs.parsing import LaunchRecord

RECORDS = [
    LaunchRecord(2025, "LEO", "Starlink", 1, datetime.datetime(2025, 1, 1), "F9")
]


class TestDataHash(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.enterContext(mock.patch.object(cache, "CACHE_DIR", tmp.name))

    def test_first_run_is_changed(self):
        self.assertTrue(cache.has_data_changed(RECORDS))

    def test_checking_does_not_record_the_hash(self):
        # A run that fails after the check must not be skipped on retry
        cache.has_data_changed(RECORDS)
        self.assertTrue(cache.has_data_changed(RECORDS))

    def test_unchanged_after_saving(self):
        cache.save_data_hash(RECORDS)
        self.assertFalse(cache.has_data_changed(RECORDS))

    def test_changed_records_are_detected(self):
        cache.save_data_hash(RECORDS)
        self.assertTrue(cache.has_data_changed(RECORDS + RECORDS))


if __name__ == "__main__":
    unittest.main()
