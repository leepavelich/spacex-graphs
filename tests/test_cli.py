"""Tests for the CLI orchestration that don't touch the network."""

import datetime
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot

from spacex_graphs import cache, cli, output, plotting, validation
from spacex_graphs.config import WIKIPEDIA_PAGES
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.validation import PublishedLaunch

TODAY = datetime.date(2026, 10, 3)


def _launch(year, month=6, day=1, payload="Starlink", vehicle="Falcon 9"):
    when = datetime.datetime(year, month, day, 12, 0)
    return LaunchRecord(year, "LEO", payload, 1, when, vehicle)


# One launch in every year the missing-year check expects, plus a recent one
# this year, so the freshness check passes
EVERY_YEAR = [
    *[_launch(year) for year in range(2012, TODAY.year)],
    _launch(TODAY.year, 10, 1),
]


class TestCodeVersion(unittest.TestCase):
    def test_is_stable_and_tracks_the_source(self):
        baseline = cli.code_version()
        self.assertEqual(cli.code_version(), baseline)
        real_read = pathlib.Path.read_bytes
        with mock.patch(
            "pathlib.Path.read_bytes", lambda path: real_read(path) + b"# edited"
        ):
            self.assertNotEqual(cli.code_version(), baseline)

    def test_tracks_library_versions(self):
        baseline = cli.code_version()
        with mock.patch("spacex_graphs.cli.metadata.version", return_value="99.0"):
            self.assertNotEqual(cli.code_version(), baseline)


class TestFetchAndParse(unittest.TestCase):
    def test_fetches_the_page_url_and_parses_with_its_layout(self):
        page = WIKIPEDIA_PAGES[-1]
        with (
            mock.patch.object(cache, "fetch_with_cache") as fetch,
            mock.patch.object(
                cli, "parse_launch_page", return_value=["parsed"]
            ) as parse,
        ):
            fetch.side_effect = lambda url, parse_page, **kwargs: (
                parse_page(b"html"),
                False,
            )
            self.assertEqual(cli._fetch_and_parse(page, "cache-dir"), ["parsed"])
        self.assertEqual(fetch.call_args.args[0], page.url)
        self.assertEqual(
            fetch.call_args.kwargs, {"cache_dir": "cache-dir", "name": page.name}
        )
        parse.assert_called_once_with(page.layout, b"html")


class TestLoadLaunchRecords(unittest.TestCase):
    def _load(self, pages, published=None):
        """Loads with each page mapped to the records it should parse to,
        checked against the given published counts (none by default)."""
        with (
            mock.patch.object(
                cli, "_fetch_and_parse", lambda page, cache_dir: pages[page]
            ),
            mock.patch.object(
                output, "published_launches", return_value=published or []
            ),
        ):
            return cli.load_launch_records(
                TODAY, cache_dir="unused", output_dir="unused"
            )

    @staticmethod
    def _pages(first_page, filler_year=TODAY.year):
        """The first page parses to first_page; every other page parses to
        one distinct launch in filler_year."""
        pages = {
            page: [_launch(filler_year, 1, i + 1)]
            for i, page in enumerate(WIKIPEDIA_PAGES)
        }
        pages[WIKIPEDIA_PAGES[0]] = first_page
        return pages

    def test_page_with_no_records_is_fatal(self):
        pages = self._pages(EVERY_YEAR)
        empty_page = WIKIPEDIA_PAGES[-1]
        pages[empty_page] = []
        with self.assertRaises(validation.EmptyPageError) as ctx:
            self._load(pages)
        self.assertIn(empty_page.name, str(ctx.exception))

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
        today = datetime.date(2027, 1, 3)
        past = [*[r for r in EVERY_YEAR if r.year < TODAY.year], _launch(2026, 12, 20)]
        pages = self._pages(past, filler_year=2024)
        with (
            mock.patch.object(
                cli, "_fetch_and_parse", lambda page, cache_dir: pages[page]
            ),
            mock.patch.object(output, "published_launches", return_value=[]),
        ):
            records = cli.load_launch_records(
                today, cache_dir="unused", output_dir="unused"
            )
        self.assertNotIn(2027, {r.year for r in records})

    def test_launch_listed_on_two_pages_counts_once(self):
        with self.assertLogs(cli.logger, "WARNING") as logs:
            records = self._load({page: EVERY_YEAR for page in WIKIPEDIA_PAGES})
        self.assertEqual(len(records), len(EVERY_YEAR))
        self.assertIn("more than one page", logs.output[0])

    def test_published_launch_going_missing_is_fatal(self):
        gone = PublishedLaunch(datetime.date(2025, 3, 3), "Falcon 9", "Gone", 1)
        with self.assertRaises(validation.PublishedLaunchesLostError):
            self._load(self._pages(EVERY_YEAR), published=[gone])

    def test_no_recent_launch_is_fatal(self):
        stale = [r for r in EVERY_YEAR if r.year < TODAY.year]
        with self.assertRaises(validation.NoRecentLaunchesError):
            self._load(self._pages(stale, filler_year=2024))

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

    def test_file_system_errors_get_a_one_line_message(self):
        with (
            mock.patch.object(cli, "run", side_effect=PermissionError("denied")),
            mock.patch("sys.argv", ["graphs.py", "--output"]),
            mock.patch("spacex_graphs.cli.logging.basicConfig"),
            self.assertRaises(SystemExit) as ctx,
            self.assertLogs(cli.logger, "ERROR") as logs,
        ):
            cli.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("could not write the outputs or cache: denied", logs.output[0])

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
        self.records = list(RECORDS)
        self.enterContext(
            mock.patch.object(
                cli, "load_launch_records", lambda today, **dirs: self.records
            )
        )
        self.show = self.enterContext(mock.patch("spacex_graphs.cli.plt.show"))
        self.addCleanup(matplotlib.pyplot.close, "all")

    def _run(self, save_output=True):
        cli.run(
            save_output=save_output,
            today=TODAY,
            output_dir=self.output_dir,
            cache_dir=self.cache_dir,
        )

    def _changed(self):
        return cache.has_data_changed(
            self.records,
            TODAY,
            cache_dir=self.cache_dir,
            code_version=cli.code_version(),
        )

    def _outputs(self):
        if not os.path.isdir(self.output_dir):
            return []
        return sorted(os.listdir(self.output_dir))

    def test_first_save_writes_all_outputs(self):
        self._run()
        self.assertEqual(self._outputs(), OUTPUT_FILES)
        self.assertFalse(self._changed())
        self.show.assert_not_called()

    def test_unchanged_rerun_skips_regeneration(self):
        self._run()
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.utime(svg, (0, 0))
        self._run()
        self.assertEqual(os.path.getmtime(svg), 0)

    def test_missing_output_regenerates_even_when_unchanged(self):
        self._run()
        os.remove(os.path.join(self.output_dir, OUTPUT_FILES[0]))
        self._run()
        self.assertEqual(self._outputs(), OUTPUT_FILES)

    def test_new_launch_regenerates(self):
        self._run()
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.utime(svg, (0, 0))
        self.records.append(
            LaunchRecord(2026, "LEO", "New", 1, datetime.datetime(2026, 3, 1), "F9")
        )
        self._run()
        self.assertGreater(os.path.getmtime(svg), 0)

    def test_code_change_regenerates_on_the_same_day(self):
        self._run()
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.utime(svg, (0, 0))
        with mock.patch.object(cli, "code_version", return_value="changed"):
            self._run()
        self.assertGreater(os.path.getmtime(svg), 0)

    def test_display_mode_shows_and_writes_nothing(self):
        self._run(save_output=False)
        self.show.assert_called_once()
        self.assertEqual(self._outputs(), [])

    def test_failed_save_is_retried_rather_than_skipped(self):
        with (
            mock.patch.object(output, "save_launches_csv", side_effect=OSError),
            self.assertRaises(OSError),
        ):
            self._run()
        # The hash wasn't recorded, so the next run regenerates
        self.assertTrue(self._changed())


class TestRunWiring(unittest.TestCase):
    def test_charts_get_the_current_year_and_caption(self):
        records = [
            LaunchRecord(2026, "LEO", "Sat", 5, datetime.datetime(2026, 9, 30), "F9")
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                cli, "load_launch_records", lambda today, **dirs: records
            ),
            mock.patch.object(
                plotting,
                "plot_payload_mass_to_orbit_by_year",
                wraps=plotting.plot_payload_mass_to_orbit_by_year,
            ) as by_year,
            mock.patch.object(
                plotting,
                "plot_cumulative_payload_mass_to_orbit",
                wraps=plotting.plot_cumulative_payload_mass_to_orbit,
            ) as cumulative,
        ):
            cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp)
        matplotlib.pyplot.close("all")
        self.assertEqual(by_year.call_args.kwargs["current_year"], 2026)
        caption = by_year.call_args.kwargs["caption"]
        self.assertIn("through 30 September 2026", caption)
        self.assertEqual(cumulative.call_args.kwargs["caption"], caption)


class TestJobSummary(unittest.TestCase):
    def test_run_summarizes_into_the_github_step_summary(self):
        records = [
            LaunchRecord(2026, "LEO", "Sat", 5, datetime.datetime(2026, 9, 30), "F9")
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                cli, "load_launch_records", lambda today, **dirs: records
            ),
        ):
            summary = os.path.join(tmp, "summary.md")
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": summary}):
                cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp)
                cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp)
            matplotlib.pyplot.close("all")
            with open(summary, encoding="utf-8") as f:
                text = f.read()
        self.assertIn("Parsed 1 launches; the latest is from 2026-09-30.", text)
        self.assertIn("Regenerated the graphs and CSV.", text)
        self.assertIn("Nothing changed since the last run", text)

    def test_no_summary_outside_github_actions(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cli._summarize("ignored")  # must not raise or write anywhere


class TestConfigureLogging(unittest.TestCase):
    def _handlers(self, quiet):
        with mock.patch("spacex_graphs.cli.logging.basicConfig") as basic:
            cli._configure_logging(quiet)
        return basic.call_args.kwargs

    def test_progress_goes_to_stdout_and_problems_to_stderr(self):
        import logging
        import sys

        kwargs = self._handlers(quiet=False)
        self.assertEqual(kwargs["level"], logging.INFO)
        progress, problems = kwargs["handlers"]
        self.assertIs(progress.stream, sys.stdout)
        self.assertIs(problems.stream, sys.stderr)
        info = logging.LogRecord("x", logging.INFO, "", 0, "m", None, None)
        warning = logging.LogRecord("x", logging.WARNING, "", 0, "m", None, None)
        self.assertTrue(progress.filter(info))
        self.assertFalse(progress.filter(warning))
        self.assertEqual(problems.level, logging.WARNING)

    def test_problems_become_annotations_in_github_actions(self):
        import logging

        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            _, problems = self._handlers(quiet=False)["handlers"]
        warning = logging.LogRecord(
            "x", logging.WARNING, "", 0, "  ! cached", None, None
        )
        error = logging.LogRecord("x", logging.ERROR, "", 0, "ERROR: bad", None, None)
        self.assertEqual(problems.format(warning), "::warning::! cached")
        self.assertEqual(problems.format(error), "::error::ERROR: bad")

    def test_quiet_shows_only_warnings_and_errors(self):
        import logging

        self.assertEqual(self._handlers(quiet=True)["level"], logging.WARNING)


if __name__ == "__main__":
    unittest.main()
