"""Tests for writing the SVG and CSV artifacts."""

import csv
import datetime
import os
import tempfile
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from spacex_graphs import output
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import build_dataframe


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
    output.save_plots(*figs, output_dir=directory)
    plt.close("all")
    contents = {}
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), "rb") as f:
            contents[name] = f.read()
    return contents


class TestSavePlots(unittest.TestCase):
    def test_identical_data_produces_identical_svgs(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = _render_svgs(a), _render_svgs(b)
        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)

    def test_svgs_have_no_embedded_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in _render_svgs(directory).values():
                self.assertNotIn(b"<dc:date>", content)


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


class TestPublishedLaunchCounts(unittest.TestCase):
    def test_counts_rows_per_year_in_the_published_csv(self):
        df = build_dataframe(
            [
                LaunchRecord(2025, "LEO", "A", 1, datetime.datetime(2025, 1, 1), "F9"),
                LaunchRecord(2025, "LEO", "B", 1, datetime.datetime(2025, 2, 1), "F9"),
                LaunchRecord(2026, "LEO", "C", 1, datetime.datetime(2026, 1, 1), "F9"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(output.published_launch_counts(directory), {})
            output.save_launches_csv(df, output_dir=directory)
            self.assertEqual(
                output.published_launch_counts(directory), {2025: 2, 2026: 1}
            )


if __name__ == "__main__":
    unittest.main()
