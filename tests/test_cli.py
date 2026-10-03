"""Tests for the CLI orchestration that don't touch the network."""

import datetime
import os
import tempfile
import unittest
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot

from spacex_graphs import cache, cli, output
from spacex_graphs.config import WIKIPEDIA_PAGES
from spacex_graphs.parsing import LaunchRecord

RECORD = LaunchRecord(
    2025, "LEO", "Starlink", 1, datetime.datetime(2025, 1, 1), "Falcon 9"
)


class TestLoadLaunchRecords(unittest.TestCase):
    def test_page_with_no_records_is_fatal(self):
        empty_url = list(WIKIPEDIA_PAGES)[-1]

        def fake_fetch_and_parse(url):
            return [] if url == empty_url else [RECORD]

        with (
            mock.patch.object(cli, "_fetch_and_parse", fake_fetch_and_parse),
            self.assertRaises(cli.EmptyPageError) as ctx,
        ):
            cli.load_launch_records()
        self.assertIn(WIKIPEDIA_PAGES[empty_url], str(ctx.exception))

    def test_all_pages_with_records_succeeds(self):
        with mock.patch.object(cli, "_fetch_and_parse", lambda url: [RECORD]):
            records = cli.load_launch_records()
        self.assertEqual(len(records), len(WIKIPEDIA_PAGES))

    def test_main_exits_nonzero_on_empty_page(self):
        with (
            mock.patch.object(
                cli, "run", side_effect=cli.EmptyPageError("no launches parsed")
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
            mock.patch.object(cli, "load_launch_records", lambda: self.records)
        )
        self.show = self.enterContext(mock.patch("spacex_graphs.cli.plt.show"))
        self.addCleanup(matplotlib.pyplot.close, "all")

    def _outputs(self):
        if not os.path.isdir(self.output_dir):
            return []
        return sorted(os.listdir(self.output_dir))

    def test_first_save_writes_all_outputs(self):
        cli.run(save_output=True)
        self.assertEqual(self._outputs(), OUTPUT_FILES)
        self.assertFalse(cache.has_data_changed(self.records, self._today()))
        self.show.assert_not_called()

    def test_unchanged_rerun_skips_regeneration(self):
        cli.run(save_output=True)
        svg = os.path.join(self.output_dir, OUTPUT_FILES[0])
        os.remove(svg)
        cli.run(save_output=True)
        self.assertFalse(os.path.exists(svg))
        with open(os.path.join(self.cache_dir, "last_run_date.txt")) as f:
            self.assertEqual(f.read(), self._today().isoformat())

    def test_new_launch_regenerates(self):
        cli.run(save_output=True)
        os.remove(os.path.join(self.output_dir, OUTPUT_FILES[0]))
        self.records.append(
            LaunchRecord(2026, "LEO", "New", 1, datetime.datetime(2026, 3, 1), "F9")
        )
        cli.run(save_output=True)
        self.assertEqual(self._outputs(), OUTPUT_FILES)

    def test_display_mode_shows_and_writes_nothing(self):
        cli.run(save_output=False)
        self.show.assert_called_once()
        self.assertEqual(self._outputs(), [])

    @staticmethod
    def _today():
        return datetime.datetime.now(datetime.UTC).date()


if __name__ == "__main__":
    unittest.main()
