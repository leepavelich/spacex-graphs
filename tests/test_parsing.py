"""Tests for the pure parsing helpers."""

import datetime
import unittest

from spacex_graphs.parsing import parse_launch_datetime, parse_payload_mass_text


class TestParseLaunchDatetime(unittest.TestCase):
    def test_day_first_format(self):
        self.assertEqual(
            parse_launch_datetime("4 June 2010 18:45"),
            datetime.datetime(2010, 6, 4, 18, 45),
        )

    def test_month_first_format(self):
        self.assertEqual(
            parse_launch_datetime("August 26, 2025"),
            datetime.datetime(2025, 8, 26, 0, 0),
        )

    def test_missing_time_defaults_to_midnight(self):
        self.assertEqual(
            parse_launch_datetime("15 January 2023"),
            datetime.datetime(2023, 1, 15, 0, 0),
        )

    def test_footnotes_and_extra_text_ignored(self):
        self.assertEqual(
            parse_launch_datetime("1 May 2024 03:30 [12] (planned)"),
            datetime.datetime(2024, 5, 1, 3, 30),
        )

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_launch_datetime("TBD"))


class TestParsePayloadMassText(unittest.TestCase):
    def test_simple_mass(self):
        self.assertEqual(parse_payload_mass_text("5,000 kg"), 5000)

    def test_range_returns_average(self):
        self.assertEqual(parse_payload_mass_text("5,000–6,000 kg"), 5500)
        self.assertEqual(parse_payload_mass_text("5000-6000 kg"), 5500)

    def test_approximate_mass(self):
        self.assertEqual(parse_payload_mass_text("~16,000 kg (35,000 lb)[54]"), 16000)

    def test_unparseable_returns_zero(self):
        self.assertEqual(parse_payload_mass_text("—"), 0)
        self.assertEqual(parse_payload_mass_text(""), 0)
        self.assertEqual(parse_payload_mass_text(None), 0)


if __name__ == "__main__":
    unittest.main()
