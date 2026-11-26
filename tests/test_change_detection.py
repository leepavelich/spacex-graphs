"""Tests for the skip-when-unchanged data hash."""

import datetime
import tempfile
import unittest

from spacex_graphs import output
from spacex_graphs.parsing import LaunchRecord

TODAY = datetime.date(2026, 10, 3)
RECORDS = [
    LaunchRecord(2025, "LEO", "Starlink", 1, datetime.datetime(2025, 1, 1), "F9")
]


class TestDataHash(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_first_run_is_changed(self):
        self.assertTrue(output.has_data_changed(RECORDS, TODAY, cache_dir=self.dir))

    def test_checking_does_not_record_the_hash(self):
        # A run that fails after the check must not be skipped on retry
        output.has_data_changed(RECORDS, TODAY, cache_dir=self.dir)
        self.assertTrue(output.has_data_changed(RECORDS, TODAY, cache_dir=self.dir))

    def test_unchanged_after_saving(self):
        output.save_data_hash(RECORDS, TODAY, cache_dir=self.dir)
        self.assertFalse(output.has_data_changed(RECORDS, TODAY, cache_dir=self.dir))

    def test_changed_records_are_detected(self):
        output.save_data_hash(RECORDS, TODAY, cache_dir=self.dir)
        self.assertTrue(
            output.has_data_changed(RECORDS + RECORDS, TODAY, cache_dir=self.dir)
        )

    def test_hash_is_order_independent_for_records_with_unknown_mass(self):
        known = RECORDS[0]
        records = [known, known._replace(payload_mass=None)]
        self.assertEqual(
            output.compute_data_hash(records, TODAY),
            output.compute_data_hash(reversed(records), TODAY),
        )
        self.assertNotEqual(
            output.compute_data_hash(records, TODAY),
            output.compute_data_hash([known], TODAY),
        )

    def test_new_day_is_changed_even_with_identical_data(self):
        # The cumulative graph's current-year line extends to today
        output.save_data_hash(RECORDS, TODAY, cache_dir=self.dir)
        tomorrow = TODAY + datetime.timedelta(days=1)
        self.assertTrue(output.has_data_changed(RECORDS, tomorrow, cache_dir=self.dir))

    def test_code_change_is_changed_even_with_identical_data(self):
        output.save_data_hash(RECORDS, TODAY, code_version="v1", cache_dir=self.dir)
        self.assertFalse(
            output.has_data_changed(
                RECORDS, TODAY, code_version="v1", cache_dir=self.dir
            )
        )
        self.assertTrue(
            output.has_data_changed(
                RECORDS, TODAY, code_version="v2", cache_dir=self.dir
            )
        )


if __name__ == "__main__":
    unittest.main()
