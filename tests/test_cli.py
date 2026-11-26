"""Tests for the CLI orchestration that don't touch the network."""

import datetime
import os
import pathlib
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import requests

from spacex_graphs import cache, cli, output, parsing, plotting, validation
from spacex_graphs.config import WIKIPEDIA_PAGES
from spacex_graphs.errors import ImplausibleMassError, OutcomeIntegrityError
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.validation import PublishedLaunch

TODAY = datetime.date(2026, 10, 3)
SVG = "http://www.w3.org/2000/svg"


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

    def test_fingerprints_nested_package_sources_and_transitive_rendering_libraries(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cli_file = root / "cli.py"
            cli_file.touch()
            with (
                mock.patch.object(cli, "__file__", str(cli_file)),
                mock.patch(
                    "spacex_graphs.cli.metadata.version", return_value="1"
                ) as version,
            ):
                before = cli.code_version()
                for library in ("fonttools", "kiwisolver", "pillow", "soupsieve"):
                    version.assert_any_call(library)
                nested = root / "nested"
                nested.mkdir()
                (nested / "example.py").write_text(
                    "# new rendering code", encoding="utf-8"
                )
                self.assertNotEqual(cli.code_version(), before)

    def test_tracks_the_python_version(self):
        baseline = cli.code_version()
        with mock.patch("sys.version_info", (3, 99, 0, "final", 0)):
            self.assertNotEqual(cli.code_version(), baseline)

    def test_fields_are_delimited_so_moved_bytes_change_the_fingerprint(self):
        # Without delimiters, "ab" + "c" and "a" + "bc" would hash the same
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "cli.py").write_bytes(b"")
            fingerprints = set()
            for name, content in (("a.py", b"x.py"), ("a.pyx.py", b"")):
                for stale in root.glob("a*"):
                    stale.unlink()
                (root / name).write_bytes(content)
                with (
                    mock.patch.object(cli, "__file__", str(root / "cli.py")),
                    mock.patch("spacex_graphs.cli.metadata.version", return_value="1"),
                ):
                    fingerprints.add(cli.code_version())
            self.assertEqual(len(fingerprints), 2)

    def test_help_explains_when_regeneration_is_skipped(self):
        with (
            mock.patch("sys.argv", ["graphs.py", "--help"]),
            mock.patch("sys.stdout") as stdout,
            self.assertRaises(SystemExit),
        ):
            cli.main()
        text = " ".join(
            "".join(call.args[0] for call in stdout.write.call_args_list).split()
        )
        self.assertIn("code fingerprint", text)
        self.assertIn("every output file still exists", text)


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

    def test_scrubbed_same_day_duplicate_cannot_displace_actual_launch(self):
        launched = _launch(2026, 10, 3, payload="Actual")
        scrubbed = launched._replace(outcome="Scrubbed", payload="Cancelled")
        with self.assertLogs(cli.logger, "WARNING") as logs:
            records = self._load(self._pages([*EVERY_YEAR, scrubbed, launched]))
        self.assertIn(launched, records)
        self.assertNotIn(scrubbed, records)
        self.assertIn("have not taken place", logs.output[0])

    def test_integrity_checks_run_before_publishing(self):
        huge = EVERY_YEAR[-1]._replace(payload_mass=100_000)
        with self.assertRaises(ImplausibleMassError):
            self._load(self._pages([*EVERY_YEAR[:-1], huge]))
        with self.assertRaises(OutcomeIntegrityError):
            self._load(
                self._pages([r._replace(outcome="Cape Canaveral") for r in EVERY_YEAR])
            )


class TestMain(unittest.TestCase):
    def test_output_quiet_and_step_summary_are_forwarded(self):
        with (
            mock.patch.object(cli, "run") as run,
            mock.patch.object(cli, "_configure_logging") as configure,
            mock.patch("sys.argv", ["graphs.py", "--output", "-q"]),
            mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": "step-summary.md"}),
        ):
            cli.main()
        run.assert_called_once_with(True, summary_path="step-summary.md")
        configure.assert_called_once_with(True)

    def test_display_is_allowed_with_an_interactive_backend(self):
        with (
            mock.patch.object(cli, "run") as run,
            mock.patch.object(cli, "_configure_logging") as configure,
            mock.patch.object(matplotlib, "get_backend", return_value="TkAgg"),
            mock.patch("sys.argv", ["graphs.py"]),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            cli.main()
        run.assert_called_once_with(False, summary_path=None)
        configure.assert_called_once_with(False)

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
        self.assertIn("file system error: denied", logs.output[0])

    def test_failures_are_fenced_in_the_step_summary(self):
        message = "invalid value\n~~~\n# not a heading <img>"
        for error in (validation.EmptyPageError(message), OSError(message)):
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                summary = pathlib.Path(tmp) / "summary.md"
                with (
                    mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}),
                    mock.patch.object(cli, "run", side_effect=error),
                    mock.patch.object(cli, "_configure_logging"),
                    mock.patch("sys.argv", ["graphs.py", "--output"]),
                    self.assertLogs(cli.logger, "ERROR"),
                    self.assertRaises(SystemExit),
                ):
                    cli.main()
                contents = summary.read_text(encoding="utf-8")
                self.assertIn(f"{message}\n~~~~\n", contents)
                self.assertTrue(contents.startswith("**Failed**\n\n~~~~\n"))

    def test_an_unwritable_step_summary_still_exits_with_the_error(self):
        # A directory can't be opened for appending
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": tmp}),
            mock.patch.object(
                cli, "run", side_effect=validation.EmptyPageError("no rows")
            ),
            mock.patch.object(cli, "_configure_logging"),
            mock.patch("sys.argv", ["graphs.py", "--output"]),
            self.assertLogs(cli.logger, "WARNING") as logs,
            self.assertRaises(SystemExit) as ctx,
        ):
            cli.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("ERROR: no rows", logs.output[0])
        self.assertIn("Could not write job summary", logs.output[1])

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
    """Exercises graph and CSV generation from known launch records."""

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
        # Display mode imports pyplot when it runs, so patch it at the source
        self.show = self.enterContext(mock.patch("matplotlib.pyplot.show"))
        self.addCleanup(plt.close, "all")

    def _run(self, save_output=True):
        cli.run(
            save_output=save_output,
            today=TODAY,
            output_dir=self.output_dir,
            cache_dir=self.cache_dir,
        )

    def _changed(self):
        return output.has_data_changed(
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
        existing_figures = plt.get_fignums()
        self._run()
        self.assertEqual(self._outputs(), OUTPUT_FILES)
        self.assertFalse(self._changed())
        self.show.assert_not_called()
        self.assertEqual(plt.get_fignums(), existing_figures)

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
        existing_figures = plt.get_fignums()
        self._run(save_output=False)
        self.show.assert_called_once()
        # Both charts were handed to pyplot to get windows
        self.assertEqual(len(plt.get_fignums()), len(existing_figures) + 2)
        titles = {
            plt.figure(num).axes[0].get_title()
            for num in plt.get_fignums()
            if num not in existing_figures
        }
        self.assertEqual(
            titles,
            {
                "SpaceX Payload Mass Launched by Year and Destination",
                "SpaceX Cumulative Payload Mass Launched by Year",
            },
        )
        self.assertEqual(self._outputs(), [])
        self.assertFalse(os.path.exists(self.output_dir))

    def test_failed_save_is_retried_rather_than_skipped(self):
        existing_figures = plt.get_fignums()
        with (
            mock.patch.object(output, "save_launches_csv", side_effect=OSError),
            self.assertRaises(OSError),
        ):
            self._run()
        # The hash wasn't recorded, so the next run regenerates
        self.assertTrue(self._changed())
        self.assertEqual(plt.get_fignums(), existing_figures)

    def test_utc_now_is_computed_once_when_today_is_omitted(self):
        utc_noon = datetime.datetime.combine(TODAY, datetime.time(12), datetime.UTC)
        with (
            mock.patch.object(cli, "datetime", wraps=datetime) as clock,
            mock.patch.object(
                cli, "load_launch_records", return_value=self.records
            ) as load,
        ):
            clock.datetime.now.return_value = utc_noon
            clock.UTC = datetime.UTC
            cli.run(False, output_dir=self.output_dir, cache_dir=self.cache_dir)
        clock.datetime.now.assert_called_once_with(datetime.UTC)
        load.assert_called_once_with(
            TODAY, output_dir=self.output_dir, cache_dir=self.cache_dir
        )


class TestFixtureRoundTrip(unittest.TestCase):
    def test_real_html_fixtures_run_through_cache_to_published_baseline(self):
        falcon, starship = WIKIPEDIA_PAGES[-2:]
        fixtures = pathlib.Path(__file__).parent / "fixtures"
        html = {
            falcon.url: (fixtures / "falcon_launches.html").read_bytes(),
            starship.url: (fixtures / "starship_launches.html").read_bytes(),
        }

        def get(url, *, headers, **kwargs):
            response = mock.MagicMock(spec=requests.Response)
            response.__enter__.return_value = response
            response.status_code = 304 if "If-None-Match" in headers else 200
            response.headers = {"ETag": '"fixture"'}
            response.iter_content.return_value = [html[url]]
            return response

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(cli, "WIKIPEDIA_PAGES", (falcon, starship)),
            mock.patch.object(validation, "FIRST_CONTINUOUS_YEAR", 2024),
            mock.patch.object(requests.Session, "get", side_effect=get),
        ):
            cache_dir, output_dir = (
                os.path.join(tmp, name) for name in ("cache", "out")
            )
            today = datetime.date(2025, 1, 13)
            expected_count = sum(
                1
                for page in (falcon, starship)
                for record in parsing.parse_launch_page(page.layout, html[page.url])
                if record.launch_datetime.date() <= today
            )
            cli.run(True, today, cache_dir=cache_dir, output_dir=output_dir)
            baseline = output.published_launches(output_dir)
            self.assertEqual(len(baseline), expected_count)
            self.assertIn(
                PublishedLaunch(
                    datetime.date(2024, 11, 19),
                    "Block 1 Starship",
                    "Plush banana",
                    None,
                ),
                baseline,
            )
            self.assertIn(
                PublishedLaunch(
                    datetime.date(2025, 1, 4), "Falcon 9", "Thuraya 4-NGS", 5000
                ),
                baseline,
            )
            self.assertEqual(output.missing_outputs(output_dir), [])
            with mock.patch.object(output, "save_plots") as save:
                cli.run(True, today, cache_dir=cache_dir, output_dir=output_dir)
            save.assert_not_called()
            self.assertEqual(output.published_launches(output_dir), baseline)


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
        self.assertEqual(by_year.call_args.kwargs["current_year"], 2026)
        caption = by_year.call_args.kwargs["caption"]
        self.assertIn("through 30 September 2026", caption)
        self.assertEqual(cumulative.call_args.kwargs["caption"], caption)

    def test_svgs_are_titled_and_described_for_screen_readers(self):
        records = [
            LaunchRecord(2026, "LEO", "Sat", 5, datetime.datetime(2026, 9, 30), "F9")
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                cli, "load_launch_records", lambda today, **dirs: records
            ),
        ):
            cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp)
            descriptions = {}
            for name in (output.BY_YEAR_SVG, output.CUMULATIVE_SVG):
                # The SVG was just written by this test, not untrusted input
                root = ElementTree.parse(os.path.join(tmp, name)).getroot()  # noqa: S314
                desc = root.find(f"{{{SVG}}}desc")
                assert desc is not None and desc.text is not None
                descriptions[name] = desc.text
        self.assertTrue(
            descriptions[output.BY_YEAR_SVG].startswith("Stacked bar chart")
        )
        self.assertTrue(descriptions[output.CUMULATIVE_SVG].startswith("Line chart"))
        for description in descriptions.values():
            # The summary comes first, then the caption
            self.assertIn("2026", description)
            self.assertTrue(description.endswith("count as 0 kg."))


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
            cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp, summary_path=summary)
            cli.run(True, TODAY, output_dir=tmp, cache_dir=tmp, summary_path=summary)
            with open(summary, encoding="utf-8") as f:
                text = f.read()
        self.assertIn("Parsed 1 launches; the latest is from 2026-09-30.", text)
        self.assertIn("Regenerated the graphs and CSV.", text)
        self.assertIn("Nothing changed since the last run", text)

    def test_no_summary_outside_github_actions(self):
        with mock.patch("builtins.open") as open_file:
            cli._summarize(None, "ignored")
        open_file.assert_not_called()


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
        injected = logging.LogRecord(
            "x", logging.ERROR, "", 0, "50%\r\n::notice::sneaky\n", None, None
        )
        self.assertEqual(
            problems.format(injected), "::error::50%25%0D%0A::notice::sneaky%0A"
        )

    def test_quiet_shows_only_warnings_and_errors(self):
        import logging

        self.assertEqual(self._handlers(quiet=True)["level"], logging.WARNING)


if __name__ == "__main__":
    unittest.main()
