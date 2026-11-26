"""Tests for writing the SVG and CSV artifacts."""

import csv
import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from spacex_graphs import output
from spacex_graphs.errors import PublishedCsvError
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import build_dataframe
from spacex_graphs.validation import PublishedLaunch


def _figure():
    # Text, bars and a clipped line exercise every source of random SVG IDs
    fig, ax = plt.subplots()
    ax.bar(["2024", "2025"], [17000, 4000], label="mass")
    ax.plot([0, 1], [0, 20000])
    ax.set_title("Payload Mass")
    ax.legend()
    return fig


def _render_svgs(directory):
    figs = (_figure(), _figure())
    output.save_plots(
        {output.BY_YEAR_SVG: figs[0], output.CUMULATIVE_SVG: figs[1]},
        output_dir=directory,
    )
    contents = {}
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), "rb") as f:
            contents[name] = f.read()
    return contents


class TestSavePlots(unittest.TestCase):
    def setUp(self):
        self.addCleanup(plt.close, "all")

    def test_identical_data_produces_identical_svgs(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = _render_svgs(a), _render_svgs(b)
        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)

    def test_svgs_have_no_embedded_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in _render_svgs(directory).values():
                self.assertNotIn(b"<dc:date>", content)

    def test_failed_svg_render_keeps_the_original_and_leaves_no_tempfile(self):
        fig = _figure()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.BY_YEAR_SVG)
            path.write_bytes(b"original")

            def fail(f, **kwargs):
                f.write(b"partial SVG")
                self.assertEqual(path.read_bytes(), b"original")
                raise OSError("disk error")

            with (
                mock.patch.object(fig, "savefig", side_effect=fail),
                self.assertRaises(OSError),
            ):
                output.save_plots({path.name: fig}, output_dir=directory)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class TestSaveLaunchesCsv(unittest.TestCase):
    def test_rows_are_chronological_with_raw_and_categorized_orbits(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2026,
                    "LEO",
                    "Starlink 9",
                    17000,
                    datetime.datetime(2026, 2, 1, 5, 30),
                    "Falcon 9",
                ),
                LaunchRecord(
                    2025,
                    "GTO[12]",
                    "SES",
                    4000,
                    datetime.datetime(2025, 7, 4),
                    "Falcon Heavy",
                ),
                LaunchRecord(
                    2026,
                    "LEO",
                    "NROL-97",
                    None,
                    datetime.datetime(2026, 9, 1),
                    "Falcon 9",
                    "Failure",
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(df, output_dir=directory)
            with open(os.path.join(directory, "spacex_launches.csv"), newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(
            list(rows[0]),
            [
                "Date",
                "Time (UTC)",
                "Year",
                "Vehicle",
                "Payload",
                "Payload Mass (kg)",
                "Orbit",
                "Orbit Category",
                "Outcome",
                "Counted Mass (kg)",
            ],
        )
        self.assertEqual(
            [row["Date"] for row in rows], ["2025-07-04", "2026-02-01", "2026-09-01"]
        )
        self.assertEqual(rows[1]["Time (UTC)"], "05:30:00")
        self.assertEqual(rows[0]["Orbit"], "GTO[12]")
        self.assertEqual(rows[0]["Orbit Category"], "GTO/GEO")
        self.assertEqual(rows[1]["Orbit Category"], "LEO (Starlink)")
        self.assertEqual(rows[1]["Payload Mass (kg)"], "17000")
        self.assertEqual(rows[1]["Counted Mass (kg)"], "17000")
        # Unknown mass is blank rather than a misleading 0; failures count 0
        self.assertEqual(rows[2]["Payload Mass (kg)"], "")
        self.assertEqual(rows[2]["Outcome"], "Failure")
        self.assertEqual(rows[2]["Counted Mass (kg)"], "0")

    def test_same_time_rows_sort_by_vehicle_then_payload_with_utf8_lf(self):
        when = datetime.datetime(2026, 2, 1)
        records = [
            LaunchRecord(2026, "LEO", payload, 1, when, vehicle)
            for vehicle, payload in (("FH", "C"), ("F9", "Bé"), ("F9", "A"))
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.LAUNCHES_CSV)
            output.save_launches_csv(build_dataframe(records), output_dir=directory)
            baseline = path.read_bytes()
            output.save_launches_csv(
                build_dataframe(records[::-1]), output_dir=directory
            )
            self.assertEqual(path.read_bytes(), baseline)
            self.assertNotIn(b"\r", baseline)
            self.assertTrue(baseline.endswith(b"\n"))
            self.assertIn("Bé".encode(), baseline)
            self.assertEqual(
                [row.payload for row in output.published_launches(directory)],
                ["A", "Bé", "C"],
            )

    def test_failed_csv_write_keeps_the_original_and_leaves_no_tempfile(self):
        df = build_dataframe([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.LAUNCHES_CSV)
            path.write_bytes(b"original")

            def fail(f, **kwargs):
                f.write(b"partial CSV")
                self.assertEqual(path.read_bytes(), b"original")
                raise OSError("disk error")

            with (
                mock.patch.object(pd.DataFrame, "to_csv", side_effect=fail),
                self.assertRaises(OSError),
            ):
                output.save_launches_csv(df, output_dir=directory)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class TestFormulaEscaping(unittest.TestCase):
    def test_formula_like_text_is_escaped_in_the_csv(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2025,
                    "=1+1",
                    '=HYPERLINK("http://example.com","x")',
                    1,
                    datetime.datetime(2025, 1, 1),
                    "Falcon 9",
                    "@SUM(A1)",
                ),
                LaunchRecord(
                    2025, "LEO", "Starlink", 1, datetime.datetime(2025, 2, 1), "F9"
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(df, output_dir=directory)
            with open(os.path.join(directory, "spacex_launches.csv"), newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["Payload"], '\'=HYPERLINK("http://example.com","x")')
        self.assertEqual(rows[0]["Orbit"], "'=1+1")
        self.assertEqual(rows[0]["Outcome"], "'@SUM(A1)")
        self.assertEqual(rows[1]["Payload"], "Starlink")


class TestPublishedLaunches(unittest.TestCase):
    def test_reads_back_what_was_published(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2025, "LEO", "A", 900, datetime.datetime(2025, 1, 1), "F9"
                ),
                LaunchRecord(
                    2026, "LEO", "B", None, datetime.datetime(2026, 1, 1), "FH"
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(output.published_launches(directory), [])
            output.save_launches_csv(df, output_dir=directory)
            self.assertEqual(
                output.published_launches(directory),
                [
                    PublishedLaunch(datetime.date(2025, 1, 1), "F9", "A", 900),
                    PublishedLaunch(datetime.date(2026, 1, 1), "FH", "B", None),
                ],
            )

    def test_formula_escapes_round_trip_without_stripping_literal_apostrophes(self):
        payloads = ["=1+1", "'=1+1", "''=1+1", "'Voyager", "\rno", "\nno", "@SUM(A1)"]
        records = [
            LaunchRecord(
                2025, "LEO", payload, 1, datetime.datetime(2025, 1, day), "-vehicle"
            )
            for day, payload in enumerate(payloads, 1)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(build_dataframe(records), output_dir=directory)
            baseline = output.published_launches(directory)
        self.assertEqual([launch.payload for launch in baseline], payloads)
        self.assertEqual(
            [launch.vehicle for launch in baseline], ["-vehicle"] * len(payloads)
        )

    def test_malformed_baseline_raises_a_data_error(self):
        header = b"Date,Vehicle,Payload,Payload Mass (kg)\n"
        for contents in (
            b"",
            b"Date,Vehicle\n2025-01-01,F9\n",
            header + b"never,F9,Sat,100\n",
            header + b"2025-01-01,F9,Sat,not a mass\n",
            header + b"2025-01-01,F9,Sat\n",
            header + b'2025-01-01,F9,"Sat,100\n',
        ):
            with (
                self.subTest(contents=contents),
                tempfile.TemporaryDirectory() as directory,
            ):
                Path(directory, output.LAUNCHES_CSV).write_bytes(contents)
                with self.assertRaisesRegex(
                    PublishedCsvError, "malformed published CSV"
                ):
                    output.published_launches(directory)


class TestEscapeFormula(unittest.TestCase):
    def test_every_formula_prefix_is_escaped(self):
        for text in ("=1", "+1", "-1", "@A1", "\tx", "\rx"):
            with self.subTest(text=repr(text)):
                self.assertEqual(output._escape_formula(text), "'" + text)

    def test_ordinary_text_is_untouched(self):
        for text in ("Starlink", "SES-8", "1+1", "a=b"):
            with self.subTest(text=text):
                self.assertEqual(output._escape_formula(text), text)


class TestMissingOutputs(unittest.TestCase):
    def test_a_missing_csv_counts_as_a_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in output.OUTPUT_FILES:
                open(os.path.join(directory, name), "w").close()
            self.assertEqual(output.missing_outputs(directory), [])
            os.remove(os.path.join(directory, output.LAUNCHES_CSV))
            self.assertEqual(output.missing_outputs(directory), [output.LAUNCHES_CSV])


if __name__ == "__main__":
    unittest.main()
