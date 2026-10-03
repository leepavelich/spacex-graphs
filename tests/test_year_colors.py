"""Tests for cumulative chart year colors (rendered with the Agg backend)."""

import datetime
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from spacex_graphs.parsing import LaunchRecord  # noqa: E402
from spacex_graphs.plotting import (  # noqa: E402
    OLDER_YEARS_COLOR,
    YEAR_COLORS,
    plot_cumulative_payload_mass_to_orbit,
)
from spacex_graphs.transform import (  # noqa: E402
    build_cumulative_frame,
    build_dataframe,
)


def _cumulative_figure(years):
    records = [
        LaunchRecord(year, "LEO", "Starlink", 1000, datetime.datetime(year, 6, 1), "F9")
        for year in years
    ]
    df = build_dataframe(records)
    today = datetime.date(2026, 10, 3)
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
        ax = _cumulative_figure(range(2020, 2029)).axes[0]
        colors = {line.get_label(): line.get_color() for line in ax.lines}
        recent = [str(year) for year in range(2028, 2020, -1)]
        self.assertEqual([colors[year] for year in recent], YEAR_COLORS)
        self.assertEqual(colors["2020"], OLDER_YEARS_COLOR)

    def test_no_folding_when_all_years_are_highlighted(self):
        ax = _cumulative_figure(range(2020, 2026)).axes[0]
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        self.assertEqual(legend, [str(year) for year in range(2020, 2026)])

if __name__ == "__main__":
    unittest.main()
