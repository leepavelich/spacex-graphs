"""Tests for the completeness checks; all pure, so no mocks."""

import datetime
import unittest

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.validation import (
    EmptyPageError,
    MissingYearsError,
    NoRecentLaunchesError,
    PublishedLaunch,
    PublishedLaunchesLostError,
    check_pages_not_empty,
    check_published_launches,
    check_recent_launch,
    check_year_coverage,
    drop_duplicate_launches,
    drop_future_launches,
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


def _published(launch, mass=1):
    return PublishedLaunch(
        launch.launch_datetime.date(), launch.vehicle, launch.payload, mass
    )


class TestCheckPublishedLaunches(unittest.TestCase):
    def setUp(self):
        self.records = _launches({2025: 20, 2026: 10})
        self.published = [_published(r) for r in self.records]

    def test_unchanged_and_new_launches_pass(self):
        check_published_launches([*self.records, _launch(2026, 9, 30)], self.published)

    def test_first_run_has_no_baseline(self):
        check_published_launches(self.records, [])

    def test_a_single_missing_launch_fails_and_is_named(self):
        # As if one heavy Starship row's layout changed; no tolerance applies
        with self.assertRaises(PublishedLaunchesLostError) as ctx:
            check_published_launches(self.records[1:], self.published)
        first = self.records[0]
        self.assertIn("1 published launches are missing", str(ctx.exception))
        self.assertIn(first.launch_datetime.date().isoformat(), str(ctx.exception))

    def test_a_new_launch_next_to_a_lost_one_does_not_hide_it(self):
        lost = self.records[-1]
        new_next_day = lost._replace(
            launch_datetime=lost.launch_datetime + datetime.timedelta(days=1),
            payload="New",
        )
        with self.assertRaises(PublishedLaunchesLostError) as ctx:
            check_published_launches([*self.records[:-1], new_next_day], self.published)
        self.assertIn(lost.launch_datetime.date().isoformat(), str(ctx.exception))

    def test_a_changed_launch_time_still_matches(self):
        retimed = self.records[0]._replace(
            launch_datetime=self.records[0].launch_datetime.replace(hour=3, minute=7)
        )
        check_published_launches([retimed, *self.records[1:]], self.published)

    def test_two_launches_on_one_day_need_two_matches(self):
        day = _launch(2026, 5, 5)
        published = [_published(day), _published(day._replace(payload="Second"))]
        with self.assertRaises(PublishedLaunchesLostError):
            check_published_launches([day], published)

    def test_a_known_mass_becoming_unknown_fails(self):
        # As if a column reorder left the mass column unreadable
        unknown = [r._replace(payload_mass=None) for r in self.records[:3]]
        with self.assertRaises(PublishedLaunchesLostError) as ctx:
            check_published_launches([*unknown, *self.records[3:]], self.published)
        self.assertIn("3 published launches lost their mass", str(ctx.exception))

    def test_a_mass_that_was_already_unknown_may_stay_unknown(self):
        published = [_published(self.records[0], mass=None), *self.published[1:]]
        unknown = self.records[0]._replace(payload_mass=None)
        check_published_launches([unknown, *self.records[1:]], published)

    def test_long_lists_are_truncated(self):
        with self.assertRaises(PublishedLaunchesLostError) as ctx:
            check_published_launches([], self.published)
        self.assertIn("30 published launches are missing", str(ctx.exception))
        self.assertIn("; ...", str(ctx.exception))


class TestCheckRecentLaunch(unittest.TestCase):
    def test_launch_within_the_limit_passes(self):
        check_recent_launch([_launch(2026, 9, 3)], TODAY)  # 30 days before TODAY

    def test_launch_older_than_the_limit_fails(self):
        with self.assertRaises(NoRecentLaunchesError) as ctx:
            check_recent_launch([_launch(2026, 9, 2)], TODAY)  # 31 days
        self.assertIn("2026-09-02", str(ctx.exception))


class TestPolicyValues(unittest.TestCase):
    def test_thresholds_are_pinned(self):
        # Changing these changes what the daily job will publish; make it a
        # deliberate, reviewed change
        from spacex_graphs import config

        self.assertEqual(config.FIRST_CONTINUOUS_YEAR, 2012)
        self.assertEqual(config.MAX_DAYS_SINCE_LAUNCH, 30)
        self.assertEqual(config.STALE_CACHE_LIMIT, datetime.timedelta(days=3))
        self.assertEqual(config.REQUEST_TIMEOUT, 10)
        self.assertEqual(config.MIN_CUMULATIVE_YEAR, 2017)
        self.assertEqual(config.HIGHLIGHT_FROM_YEAR, 2020)


if __name__ == "__main__":
    unittest.main()
