"""Tests for cumulative chart year colors (rendered with the Agg backend)."""

import datetime
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import to_hex

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
        self.assertEqual(tuple(colors[year] for year in recent), YEAR_COLORS[:7])
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        # Newest first, with the grey group last
        expected = [str(year) for year in range(2026, 2019, -1)] + ["2017–2019"]
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
        self.assertEqual(tuple(colors[year] for year in recent), YEAR_COLORS)
        self.assertEqual(colors["2020"], OLDER_YEARS_COLOR)

    def test_no_folding_when_all_years_are_highlighted(self):
        ax = _cumulative_figure(range(2020, 2026)).axes[0]
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        self.assertEqual(legend, [str(year) for year in range(2025, 2019, -1)])

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
        # TODAY is in 2026, a 365-day year: equal padding either side of
        # day 1 and day 365
        self.assertEqual(ax.get_xlim(), (-5, 371))
        leap = _cumulative_figure([2024], today=datetime.date(2024, 5, 1)).axes[0]
        self.assertEqual(leap.get_xlim(), (-5, 372))
        self.assertEqual(
            [label.get_text() for label in ax.get_xticklabels()],
            ["Jan 1", "Mar 1", "May 1", "Jul 1", "Sep 1", "Nov 1"],
        )
        self.assertEqual(
            [label.get_rotation() for label in ax.get_xticklabels()], [0] * 6
        )

    def test_month_ticks_follow_the_current_years_calendar(self):
        common = _cumulative_figure([2026], today=datetime.date(2026, 10, 3)).axes[0]
        self.assertEqual(list(common.get_xticks()), [1, 60, 121, 182, 244, 305])
        leap = _cumulative_figure([2028], today=datetime.date(2028, 10, 3)).axes[0]
        self.assertEqual(list(leap.get_xticks()), [1, 61, 122, 183, 245, 306])

    def test_gridlines_are_drawn_behind_the_lines(self):
        ax = _cumulative_figure([2026]).axes[0]
        self.assertIs(ax.get_axisbelow(), True)


class TestCumulativeLabels(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_single_older_year_is_labelled_alone(self):
        ax = _cumulative_figure(range(2019, 2027)).axes[0]
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        self.assertEqual(legend[-1], "2019")

    def test_title_axis_labels_and_caption(self):
        records = [
            LaunchRecord(
                2026, "LEO", "Starlink", 1_234_567, datetime.datetime(2026, 6, 1), "F9"
            )
        ]
        today = datetime.date(2026, 10, 3)
        fig = plot_cumulative_payload_mass_to_orbit(
            build_cumulative_frame(build_dataframe(records), today),
            today,
            caption="Source: test",
        )
        ax = fig.axes[0]
        self.assertEqual(
            ax.get_title(), "SpaceX Cumulative Payload Mass Launched by Year"
        )
        self.assertEqual(ax.get_ylabel(), "Cumulative Payload Mass (kg)")
        self.assertEqual(ax.get_xlabel(), "")
        formatter = ax.yaxis.get_major_formatter()
        self.assertEqual(formatter(1_234_567, 0), "1,234,567")
        self.assertEqual([text.get_text() for text in fig.texts], ["Source: test"])
        self.assertEqual(to_hex(fig.texts[0].get_color()), "#595959")


class TestCurrentYearEmphasis(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_current_year_is_thicker_and_ends_in_a_dot(self):
        today = datetime.date(2026, 10, 3)
        ax = _cumulative_figure(range(2017, 2027), today=today).axes[0]
        widths = {line.get_label(): line.get_linewidth() for line in ax.lines}
        self.assertEqual(widths["2026"], 2.2)
        self.assertEqual(widths["2025"], 1.5)
        self.assertEqual(widths["2017–2019"], 1.0)

        self.assertEqual(len(ax.collections), 1)
        dot = ax.collections[0]
        # Today's position and the year's total so far
        day = today.timetuple().tm_yday
        self.assertEqual([list(point) for point in dot.get_offsets()], [[day, 1000]])
        self.assertEqual(to_hex(dot.get_facecolor()[0]), YEAR_COLORS[0])
        legend = [text.get_text() for text in ax.get_legend().get_texts()]
        self.assertEqual(legend.count("2026"), 1)

    def test_no_dot_before_the_current_years_first_launch(self):
        ax = _cumulative_figure(
            range(2020, 2027), today=datetime.date(2027, 1, 3)
        ).axes[0]
        self.assertEqual(len(ax.collections), 0)
        self.assertEqual({line.get_linewidth() for line in ax.lines}, {1.5})


class TestEmptyCumulative(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_empty_frame_draws_an_empty_chart(self):
        today = datetime.date(2026, 10, 3)
        fig = plot_cumulative_payload_mass_to_orbit(
            build_cumulative_frame(build_dataframe([]), today), today
        )
        ax = fig.axes[0]
        self.assertEqual(len(ax.lines), 0)
        self.assertIsNone(ax.get_legend())
        self.assertEqual([t.get_text() for t in ax.texts], ["No launches to show"])


class TestYearPalette(unittest.TestCase):
    def test_is_frozen(self):
        self.assertIsInstance(YEAR_COLORS, tuple)
        self.assertEqual(len(YEAR_COLORS), 8)


if __name__ == "__main__":
    unittest.main()
