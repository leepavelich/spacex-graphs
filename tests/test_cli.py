"""Tests for the CLI orchestration that don't touch the network."""

import datetime
import os
import tempfile
import unittest
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot

from spacex_graphs import cache, cli, output, validation
from spacex_graphs.config import WIKIPEDIA_PAGES
from spacex_graphs.parsing import LaunchRecord

TODAY = datetime.date(2026, 10, 3)


def _launch(year, month=6, day=1, payload="Starlink", vehicle="Falcon 9"):
    when = datetime.datetime(year, month, day, 12, 0)
    return LaunchRecord(year, "LEO", payload, 1, when, vehicle)


# One launch in every year the missing-year check expects, plus this year
EVERY_YEAR = [_launch(year) for year in range(2012, TODAY.year + 1)]


class TestLoadLaunchRecords(unittest.TestCase):
    def _load(self, pages, published=None):
        """Loads with each page URL mapped to the records it should parse to,
        checked against the given published counts (none by default)."""
        with (
            mock.patch.object(cli, "_fetch_and_parse", lambda url: pages[url]),
            mock.patch.object(
                output, "published_launch_counts", return_value=published or {}
            ),
        ):
            return cli.load_launch_records(TODAY)

    @staticmethod
    def _pages(first_page, filler_year=TODAY.year):
        """The first page parses to first_page; every other page parses to
        one distinct launch in filler_year."""
        urls = list(WIKIPEDIA_PAGES)
        pages = {url: [_launch(filler_year, 1, i + 1)] for i, url in enumerate(urls)}
        pages[urls[0]] = first_page
        return pages

    def test_page_with_no_records_is_fatal(self):
        pages = self._pages(EVERY_YEAR)
        empty_url = list(WIKIPEDIA_PAGES)[-1]
        pages[empty_url] = []
        with self.assertRaises(validation.EmptyPageError) as ctx:
            self._load(pages)
        self.assertIn(WIKIPEDIA_PAGES[empty_url], str(ctx.exception))

    def test_complete_pages_load(self):
        records = self._load(self._pages(EVERY_YEAR))
        self.assertEqual(len(records), len(EVERY_YEAR) + len(WIKIPEDIA_PAGES) - 1)

    def test_missing_past_year_is_fatal(self):
        # As if Wikipedia split 2025 out into a page this project doesn't fetch
        without_2025 = [r for r in EVERY_YEAR if r.year != 2025]
        with self.assertRaises(validation.MissingYearsError) as ctx:
            self._load(self._pages(without_2025))
        self.assertIn("2025", str(ctx.exception))

    def test_current_year_may_be_empty(self):
        # Early January can legitimately have no launches yet
        past_only = [r for r in EVERY_YEAR if r.year < TODAY.year]
        records = self._load(self._pages(past_only, filler_year=2024))
        self.assertNotIn(TODAY.year, {r.year for r in records})

    def test_launch_listed_on_two_pages_counts_once(self):
        with self.assertLogs(cli.logger, "WARNING") as logs:
            records = self._load({url: EVERY_YEAR for url in WIKIPEDIA_PAGES})
        self.assertEqual(len(records), len(EVERY_YEAR))
        self.assertIn("more than one page", logs.output[0])

    def test_year_losing_launches_since_last_publish_is_fatal(self):
        with self.assertRaises(validation.LaunchCountDropError):
            self._load(self._pages(EVERY_YEAR), published={2025: 50})

    def test_launches_after_today_are_dropped(self):
        planned = _launch(TODAY.year, 12, 24, payload="Planned")
        with self.assertLogs(cli.logger, "WARNING") as logs:
            records = self._load(self._pages([*EVERY_YEAR, planned]))
        self.assertNotIn(planned, records)
        self.assertIn("after today", logs.output[0])

    def test_main_exits_nonzero_on_empty_page(self):
        with (
            mock.patch.object(
                cli, "run", side_effect=validation.EmptyPageError("no launches parsed")
            ),
            mock.patch("sys.argv", ["graphs.py", "--output"]),
            # main() configures the root logger; keep that out of other tests
            mock.patch("spacex_graphs.cli.logging.basicConfig"),
            self.assertRaises(SystemExit) as ctx,
            self.assertLogs(cli.logger, "ERROR") as logs,
        ):
            cli.main()
        self.assertIn("no launches parsed", logs.output[0])
        self.assertEqual(ctx.exception.code, 1)

    def test_main_exits_nonzero_on_every_data_error(self):
        for error in (
            validation.MissingYearsError("no launches found for 2025"),
            cache.FetchError("Falcon current could not be fetched"),
            cache.StaleCacheError("Falcon current could not be fetched"),
        ):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(cli, "run", side_effect=error),
                mock.patch("sys.argv", ["graphs.py", "--output"]),
                mock.patch("spacex_graphs.cli.logging.basicConfig"),
                self.assertRaises(SystemExit) as ctx,
                self.assertLogs(cli.logger, "ERROR"),
            ):
                cli.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_display_without_a_display_is_a_usage_error(self):
        # Tests run with the file-only Agg backend, like a container or CI
        with (
            mock.patch.object(cli, "run") as run,
            mock.patch("sys.argv", ["graphs.py", "-q"]),
            mock.patch("sys.stderr"),
            self.assertRaises(SystemExit) as ctx,
        ):
            cli.main()
        self.assertEqual(ctx.exception.code, 2)
        run.assert_not_called()


RECORDS = [
    LaunchRecord(2025, "LEO", "Starlink 1", 17000, datetime.datetime(2025, 3, 1), "F9"),
    LaunchRecord(2026, "GTO", "SES", 4000, datetime.datetime(2026, 2, 1), "F9"),
]
OUTPUT_FILES = [
    "cumulative_payload_mass_to_orbit.svg",
    "payload_mass_to_orbit_by_year.svg",
    "spacex_launches.csv",
]


class TestRun(unittest.TestCase):
    """Runs the whole pipeline with only the network fetch mocked out."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output_dir = os.path.join(tmp.name, "outputs")
        self.cache_dir = os.path.join(tmp.name, ".cache")
        for module, name, value in (
            (cli, "OUTPUT_DIR", self.output_dir),
            (cli, "CACHE_DIR", self.cache_dir),
            (cache, "CACHE_DIR", self.cache_dir),
            (output, "OUTPUT_DIR", self.output_dir),
        ):
            self.enterContext(mock.patch.object(module, name, value))
        self.records = list(RECORDS)
        self.enterContext(
            mock.patch.object(cli, "load_launch_records", lambda today: self.records)
        )
        self.show = self.enterContext(mock.patch("spacex_graphs.cli.plt.show"))
        self.addCleanup(matplotlib.pyplot.close, "all")

    def _outputs(self):
        if not os.path.isdir(self.output_dir):
            return []
        return sorted(os.listdir(self.output_dir))

    def test_first_save_writes_all_outputs(self):
        cli.run(save_output=True, today=TODAY)
        self.assertEqual(self._outputs(), OUTPUT_FILES)
        self.assertFalse(cache.has_data_changed(self.records, TODAY))
        self.show.assert_not_called()

    def test_unchanged_rerun_skips_regeneration(self):
        cli.run(save_output=True, today=TODAY)
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.utime(svg, (0, 0))
        cli.run(save_output=True, today=TODAY)
        self.assertEqual(os.path.getmtime(svg), 0)
        with open(os.path.join(self.cache_dir, "last_run_date.txt")) as f:
            self.assertEqual(f.read(), TODAY.isoformat())

    def test_missing_output_regenerates_even_when_unchanged(self):
        cli.run(save_output=True, today=TODAY)
        os.remove(os.path.join(self.output_dir, OUTPUT_FILES[0]))
        cli.run(save_output=True, today=TODAY)
        self.assertEqual(self._outputs(), OUTPUT_FILES)

    def test_new_launch_regenerates(self):
        cli.run(save_output=True, today=TODAY)
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.utime(svg, (0, 0))
        self.records.append(
            LaunchRecord(2026, "LEO", "New", 1, datetime.datetime(2026, 3, 1), "F9")
        )
        cli.run(save_output=True, today=TODAY)
        self.assertGreater(os.path.getmtime(svg), 0)

    def test_display_mode_shows_and_writes_nothing(self):
        cli.run(save_output=False, today=TODAY)
        self.show.assert_called_once()
        self.assertEqual(self._outputs(), [])

    def test_failed_save_is_retried_rather_than_skipped(self):
        with (
            mock.patch.object(output, "save_launches_csv", side_effect=OSError),
            self.assertRaises(OSError),
        ):
            cli.run(save_output=True, today=TODAY)
        # The hash wasn't recorded, so the next run regenerates
        self.assertTrue(cache.has_data_changed(self.records, TODAY))


if __name__ == "__main__":
    unittest.main()
