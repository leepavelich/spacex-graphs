"""Tests for the completeness checks; all pure, so no mocks."""

import datetime
import unittest

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.validation import (
    EmptyPageError,
    LaunchCountDropError,
    MissingYearsError,
    check_launch_counts,
    check_pages_not_empty,
    check_year_coverage,
    drop_duplicate_launches,
    drop_future_launches,
    launch_counts_by_year,
)

TODAY = datetime.date(2026, 10, 3)


def _launch(year, month=6, day=1, payload="Sat", vehicle="Falcon 9"):
    when = datetime.datetime(year, month, day, 12, 0)
    return LaunchRecord(year, "LEO", payload, 1, when, vehicle)


def _launches(counts):
    """Records with the given number of launches per year."""
    return [
        _launch(year, 1 + i // 28, 1 + i % 28)
        for year, count in counts.items()
        for i in range(count)
    ]


class TestCheckPagesNotEmpty(unittest.TestCase):
    def test_names_every_empty_page(self):
        with self.assertRaises(EmptyPageError) as ctx:
            check_pages_not_empty({"A": [_launch(2025)], "B": [], "C": []})
        self.assertIn("B, C", str(ctx.exception))

    def test_pages_with_launches_pass(self):
        check_pages_not_empty({"A": [_launch(2025)]})


class TestDropDuplicateLaunches(unittest.TestCase):
    def test_same_time_and_vehicle_is_one_launch(self):
        when = datetime.datetime(2025, 1, 6, 20, 43)
        first = LaunchRecord(2025, "LEO", "Starlink 6-71[12]", 1, when, "Falcon 9")
        relisted = LaunchRecord(2025, "LEO", "Starlink 6-71[48]", 1, when, "Falcon 9")
        unique, dropped = drop_duplicate_launches([first, relisted])
        self.assertEqual((unique, dropped), ([first], 1))

    def test_different_vehicles_at_the_same_time_are_kept(self):
        when = datetime.datetime(2025, 1, 6, 20, 43)
        falcon = LaunchRecord(2025, "LEO", "A", 1, when, "Falcon 9")
        starship = LaunchRecord(2025, "LEO", "B", 1, when, "Block 2 Starship")
        self.assertEqual(drop_duplicate_launches([falcon, starship])[1], 0)


class TestDropFutureLaunches(unittest.TestCase):
    def test_today_is_kept_and_tomorrow_dropped(self):
        today = _launch(2026, 10, 3)
        tomorrow = _launch(2026, 10, 4)
        self.assertEqual(drop_future_launches([today, tomorrow], TODAY), ([today], 1))


class TestCheckYearCoverage(unittest.TestCase):
    def test_every_past_year_since_2012_must_have_launches(self):
        for missing in (2012, 2019, 2025):
            with self.subTest(missing=missing):
                years = [y for y in range(2012, 2027) if y != missing]
                with self.assertRaises(MissingYearsError) as ctx:
                    check_year_coverage([_launch(y) for y in years], TODAY)
                self.assertIn(str(missing), str(ctx.exception))

    def test_years_before_2012_and_the_current_year_may_be_empty(self):
        check_year_coverage([_launch(y) for y in range(2012, 2026)], TODAY)


class TestCheckLaunchCounts(unittest.TestCase):
    def test_counts_by_year(self):
        self.assertEqual(
            launch_counts_by_year(_launches({2024: 3, 2025: 1})), {2024: 3, 2025: 1}
        )

    def test_small_corrections_and_growth_pass(self):
        records = _launches({2024: 132, 2025: 170})
        check_launch_counts(records, {2024: 134, 2025: 165})

    def test_losing_most_of_a_year_fails(self):
        # As if a column change made the 2026 table stop parsing
        records = _launches({2025: 165, 2026: 3})
        with self.assertRaises(LaunchCountDropError) as ctx:
            check_launch_counts(records, {2025: 165, 2026: 117})
        self.assertIn("2026 has 3 (was 117)", str(ctx.exception))

    def test_drop_of_three_is_one_too_many(self):
        with self.assertRaises(LaunchCountDropError):
            check_launch_counts(_launches({2024: 131}), {2024: 134})

    def test_a_year_disappearing_entirely_fails(self):
        with self.assertRaises(LaunchCountDropError):
            check_launch_counts(_launches({2025: 165}), {2024: 134, 2025: 165})

    def test_first_run_has_no_baseline(self):
        check_launch_counts(_launches({2025: 1}), {})


if __name__ == "__main__":
    unittest.main()
