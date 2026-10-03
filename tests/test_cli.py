"""Tests for the CLI orchestration that don't touch the network."""

import datetime
import unittest
from unittest import mock

from spacex_graphs import cli
from spacex_graphs.config import WIKIPEDIA_PAGES
from spacex_graphs.parsing import LaunchRecord

RECORD = LaunchRecord(
    2025, "LEO", "Starlink", 1, datetime.datetime(2025, 1, 1), "Falcon 9"
)


class TestLoadLaunchRecords(unittest.TestCase):
    def test_page_with_no_records_is_fatal(self):
        empty_url = list(WIKIPEDIA_PAGES)[-1]

        def fake_fetch_and_parse(url):
            return ([] if url == empty_url else [RECORD]), False

        with mock.patch.object(cli, "_fetch_and_parse", fake_fetch_and_parse):
            with self.assertRaises(cli.EmptyPageError) as ctx:
                cli.load_launch_records()
        self.assertIn(WIKIPEDIA_PAGES[empty_url], str(ctx.exception))

    def test_all_pages_with_records_succeeds(self):
        with mock.patch.object(
            cli, "_fetch_and_parse", lambda url: ([RECORD], True)
        ):
            records, all_unchanged = cli.load_launch_records()
        self.assertEqual(len(records), len(WIKIPEDIA_PAGES))
        self.assertTrue(all_unchanged)

    def test_main_exits_nonzero_on_empty_page(self):
        with mock.patch.object(
            cli, "run", side_effect=cli.EmptyPageError("no launches parsed")
        ), mock.patch("sys.argv", ["graphs.py", "--output"]):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
