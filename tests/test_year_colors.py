"""Tests for cumulative chart year colors (rendered with the Agg backend)."""

import datetime
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.plotting import (
    OLDER_YEARS_COLOR,
    YEAR_COLORS,
    plot_cumulative_payload_mass_to_orbit,
)
from spacex_graphs.transform import (
    build_cumulative_frame,
    build_dataframe,
)


def _cumulative_figure(years, today=None):
    records = [
        LaunchRecord(year, "LEO", "Starlink", 1000, datetime.datetime(year, 6, 1), "F9")
        for year in years
    ]
    df = build_dataframe(records)
    today = today or datetime.date(2026, 10, 3)
    return plot_cumulative_payload_mass_to_orbit(
        build_cumulative_frame(df, today), today
    )


class TestPlotCumulative(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_pre_highlight_years_are_grey(self):
        ax = _cumulative_figure(range(2017, 2027)).axes[0]
        colors = {line.get_label(): line.get_color() for line in ax.lines}

        recent = [str(year) for year in range(2026, 2019, -1)]
        self.assertEqual([colors[year] for year in recent], YEAR_COLORS[:7])
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        expected = ["2017–2019"] + [str(year) for year in range(2020, 2027)]
        self.assertEqual(legend, expected)
        older = [line for line in ax.lines if line.get_color() == OLDER_YEARS_COLOR]
        self.assertEqual(len(older), 3)

    def test_years_beyond_the_palette_also_fold(self):
        # Nine highlighted years, one more than YEAR_COLORS
        ax = _cumulative_figure(
            range(2020, 2029), today=datetime.date(2028, 10, 3)
        ).axes[0]
        colors = {line.get_label(): line.get_color() for line in ax.lines}
        recent = [str(year) for year in range(2028, 2020, -1)]
        self.assertEqual([colors[year] for year in recent], YEAR_COLORS)
        self.assertEqual(colors["2020"], OLDER_YEARS_COLOR)

    def test_no_folding_when_all_years_are_highlighted(self):
        ax = _cumulative_figure(range(2020, 2026)).axes[0]
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        self.assertEqual(legend, [str(year) for year in range(2020, 2026)])

    def test_current_year_keeps_red_before_its_first_launch(self):
        # Early January: no launches yet this year, so last year must not
        # turn red and every other year keeps its color
        ax = _cumulative_figure(
            range(2020, 2027), today=datetime.date(2027, 1, 3)
        ).axes[0]
        colors = {line.get_label(): line.get_color() for line in ax.lines}
        self.assertNotIn(YEAR_COLORS[0], colors.values())
        self.assertEqual(colors["2026"], YEAR_COLORS[1])
        self.assertEqual(colors["2020"], YEAR_COLORS[7])


class TestCumulativeGeometry(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_lines_step_and_the_axis_spans_the_current_year(self):
        ax = _cumulative_figure(range(2023, 2025)).axes[0]
        for line in ax.lines:
            self.assertEqual(line.get_drawstyle(), "steps-post")
        # TODAY is in 2026, a 365-day year, with a little padding either side
        self.assertEqual(ax.get_xlim(), (-14, 372))
        leap = _cumulative_figure([2024], today=datetime.date(2024, 5, 1)).axes[0]
        self.assertEqual(leap.get_xlim(), (-14, 373))
        self.assertEqual(
            [label.get_text() for label in ax.get_xticklabels()],
            ["Jan 1", "Mar 1", "May 1", "Jul 1", "Sep 1", "Nov 1"],
        )


if __name__ == "__main__":
    unittest.main()
