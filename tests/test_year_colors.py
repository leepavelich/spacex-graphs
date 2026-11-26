"""Tests for the cumulative chart: year colors, geometry, and direct labels.

The figures render on their own Agg canvases, without pyplot.
"""

import datetime
import itertools
import unittest
from unittest import mock

import numpy as np
from matplotlib.colors import to_hex
from matplotlib.path import Path
from matplotlib.text import Annotation, Text

from spacex_graphs import plotting
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.plotting import (
    MARGIN_LABEL_FROM_DAY,
    OLDER_YEARS_COLOR,
    YEAR_COLORS,
    plot_cumulative_payload_mass_to_orbit,
)
from spacex_graphs.transform import (
    build_cumulative_frame,
    build_dataframe,
    calendar_day,
)
from tests.test_plotting import contrast, worst_delta_e

# A late-year date, when every highlighted year is labelled in the margin
_LATE = datetime.date(2026, 11, 25)


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
    def test_lines_step_and_the_axis_spans_the_leap_year_calendar(self):
        ax = _cumulative_figure(range(2023, 2025)).axes[0]
        for line in ax.lines:
            self.assertEqual(line.get_drawstyle(), "steps-post")
        # Every year is drawn on the 366-day calendar: equal padding either
        # side of day 1 and day 366, whether or not today is in a leap year
        self.assertEqual(ax.get_xlim(), (-5, 372))
        leap = _cumulative_figure([2024], today=datetime.date(2024, 5, 1)).axes[0]
        self.assertEqual(leap.get_xlim(), (-5, 372))
        self.assertEqual(
            [label.get_text() for label in ax.get_xticklabels()],
            ["Jan 1", "Mar 1", "May 1", "Jul 1", "Sep 1", "Nov 1"],
        )
        self.assertEqual(
            [label.get_rotation() for label in ax.get_xticklabels()], [0] * 6
        )

    def test_month_ticks_use_the_leap_year_calendar_in_every_year(self):
        leap_calendar = [1, 61, 122, 183, 245, 306]
        for today in (datetime.date(2026, 10, 3), datetime.date(2028, 10, 3)):
            with self.subTest(today=today):
                ax = _cumulative_figure([today.year], today=today).axes[0]
                self.assertEqual(list(ax.get_xticks()), leap_calendar)

    def test_same_date_lines_up_across_leap_and_common_years(self):
        # A launch on March 1st steps every year's line at the same x, which
        # is also where the "Mar 1" tick sits
        records = [
            LaunchRecord(year, "LEO", "Sat", 1000, datetime.datetime(year, 3, 1), "F9")
            for year in (2023, 2024, 2025, 2026)
        ]
        today = datetime.date(2026, 10, 3)
        ax = plot_cumulative_payload_mass_to_orbit(
            build_cumulative_frame(build_dataframe(records), today), today
        ).axes[0]
        steps = {
            line.get_label(): next(
                x for x, y in np.asarray(line.get_xydata()) if y == 1000
            )
            for line in ax.lines
        }
        self.assertEqual(set(steps.values()), {61})
        ticks = dict(
            zip(
                [label.get_text() for label in ax.get_xticklabels()],
                ax.get_xticks(),
                strict=True,
            )
        )
        self.assertEqual(ticks["Mar 1"], 61)
        # Past years all end on December 31st, day 366
        ends = {line.get_label(): np.asarray(line.get_xdata())[-1] for line in ax.lines}
        self.assertEqual(ends, {"2023": 366, "2024": 366, "2025": 366, "2026": 277})

    def test_gridlines_are_drawn_behind_the_lines(self):
        ax = _cumulative_figure([2026]).axes[0]
        self.assertIs(ax.get_axisbelow(), True)


class TestCumulativeLabels(unittest.TestCase):
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
        day = calendar_day(today)
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
    def test_empty_frame_draws_an_empty_chart(self):
        today = datetime.date(2026, 10, 3)
        fig = plot_cumulative_payload_mass_to_orbit(
            build_cumulative_frame(build_dataframe([]), today), today
        )
        ax = fig.axes[0]
        self.assertEqual(len(ax.lines), 0)
        self.assertIsNone(ax.get_legend())
        self.assertEqual([t.get_text() for t in ax.texts], ["No launches to show"])


def _projected_records(first_year, today, annual_total):
    """Twice-monthly launches in each year up to today, a year's launches
    summing to annual_total(year)."""
    records = []
    for year in range(first_year, today.year + 1):
        for month, day in itertools.product(range(1, 13), (1, 15)):
            when = datetime.datetime(year, month, day, 12)
            if when.date() <= today:
                mass = round(annual_total(year) / 24)
                records.append(LaunchRecord(year, "LEO", "Starlink", mass, when, "F9"))
    return records


def _starship_era(year):
    # Today's ~2.2 million kg a year, growing 60% a year from 2026 on
    return 2_200_000 * 1.6 ** max(0, year - 2025) * (year - 2005) / 20


def _plot(records, today, caption=""):
    return plot_cumulative_payload_mass_to_orbit(
        build_cumulative_frame(build_dataframe(records), today), today, caption=caption
    )


def _text_box(label):
    # The label's text alone, without its leader line
    return Text.get_window_extent(label)


def _step_path(line):
    """The line as drawn (with steps-post), in display coordinates."""
    xs, ys = line.get_data()
    vertices = []
    for (x0, y0), (x1, _) in itertools.pairwise(zip(xs, ys, strict=True)):
        vertices += [(x0, y0), (x1, y0)]
    vertices.append((xs[-1], ys[-1]))
    return Path(line.get_transform().transform(vertices))


class TestDirectLabels(unittest.TestCase):
    def _labels(self, ax):
        return [text for text in ax.texts if isinstance(text, Annotation)]

    def test_highlighted_years_are_labelled_with_leaders_in_their_colors(self):
        fig = _cumulative_figure(range(2017, 2027), today=_LATE)
        ax = fig.axes[0]
        colors = {line.get_label(): to_hex(line.get_color()) for line in ax.lines}
        labels = self._labels(ax)
        self.assertEqual(
            [label.get_text() for label in labels],
            [str(year) for year in range(2026, 2019, -1)],
        )
        for label in labels:
            with self.subTest(year=label.get_text()):
                assert label.arrow_patch is not None
                self.assertEqual(
                    to_hex(label.arrow_patch.get_edgecolor()),
                    colors[label.get_text()],
                )

    def test_labels_sit_level_with_their_lines_ends(self):
        records = [
            LaunchRecord(2024, "LEO", "A", 1_000, datetime.datetime(2024, 6, 1), "F9"),
            LaunchRecord(
                2025, "LEO", "B", 900_000, datetime.datetime(2025, 6, 1), "F9"
            ),
        ]
        today = datetime.date(2026, 10, 3)
        fig = _plot(records, today)
        fig.draw_without_rendering()
        ax = fig.axes[0]
        for label in self._labels(ax):
            line_end = ax.transData.transform((0, label.xy[1]))[1]
            with self.subTest(year=label.get_text()):
                # Far apart already, so neither was nudged
                self.assertAlmostEqual(
                    _text_box(label).y0 + _text_box(label).height / 2, line_end, delta=1
                )
                self.assertEqual(label.xyann[1], 0)

    def test_close_totals_are_nudged_apart_in_order(self):
        # Eight highlighted years that all end within 1% of each other
        today = datetime.date(2027, 11, 25)
        records = _projected_records(
            2020, today, lambda year: 2_000_000 + (year - 2020) * 2_000
        )
        fig = _plot(records, today, caption="Source: test")
        fig.draw_without_rendering()
        ax = fig.axes[0]
        labels = self._labels(ax)
        self.assertEqual(len(labels), 8)
        boxes = [_text_box(label) for label in labels]
        for (a, box_a), (b, box_b) in itertools.combinations(
            zip(labels, boxes, strict=True), 2
        ):
            with self.subTest(a=a.get_text(), b=b.get_text()):
                self.assertFalse(box_a.overlaps(box_b))
        # Ties keep their order, and every label stays within the axes' height
        by_height = sorted(zip(labels, boxes, strict=True), key=lambda pair: pair[1].y0)
        totals = [label.xy[1] for label, _ in by_height]
        self.assertEqual(totals, sorted(totals))
        axes_box = ax.get_window_extent()
        for box in boxes:
            self.assertGreaterEqual(box.y0, axes_box.y0 - 1)
            self.assertLessEqual(box.y1, axes_box.y1 + 1)

    def test_late_in_the_year_the_current_year_is_labelled_in_the_margin(self):
        self.assertGreaterEqual(calendar_day(_LATE), MARGIN_LABEL_FROM_DAY)
        fig = _cumulative_figure(range(2024, 2027), today=_LATE)
        fig.draw_without_rendering()
        ax = fig.axes[0]
        labels = self._labels(ax)
        self.assertEqual(
            [label.get_text() for label in labels], ["2026", "2025", "2024"]
        )
        axes_box = ax.get_window_extent()
        for label in labels:
            with self.subTest(year=label.get_text()):
                self.assertIsNotNone(label.arrow_patch)
                self.assertGreater(_text_box(label).x0, axes_box.x1)

    def test_mid_year_the_current_year_is_labelled_beside_its_dot(self):
        today = datetime.date(2026, 6, 15)
        self.assertLess(calendar_day(today), MARGIN_LABEL_FROM_DAY)
        fig = _plot(_projected_records(2020, today, _starship_era), today)
        fig.draw_without_rendering()
        ax = fig.axes[0]
        current, *others = self._labels(ax)
        self.assertEqual(current.get_text(), "2026")
        self.assertEqual(
            [label.get_text() for label in others],
            ["2025", "2024", "2023", "2022", "2021", "2020"],
        )
        # Anchored on the dot, with no leader, inside the axes
        (dot,) = ax.collections
        self.assertEqual(tuple(current.xy), tuple(dot.get_offsets()[0]))
        self.assertIsNone(current.arrow_patch)
        box = _text_box(current)
        axes_box = ax.get_window_extent()
        self.assertTrue(axes_box.contains(box.x0, box.y0))
        self.assertTrue(axes_box.contains(box.x1, box.y1))
        # Right beside the dot: within a few points of it
        dot_x, dot_y = ax.transData.transform(current.xy)
        points = fig.dpi / 72
        self.assertLess(abs(box.x0 - dot_x), 8 * points)
        self.assertLess(min(abs(box.y0 - dot_y), abs(box.y1 - dot_y)), 8 * points)
        # Clear of every line and the legend
        legend = ax.get_legend()
        assert legend is not None
        self.assertFalse(box.overlaps(legend.get_window_extent()))
        for line in ax.lines:
            with self.subTest(line=line.get_label()):
                self.assertFalse(_step_path(line).intersects_bbox(box))
        # Every other year stays in the margin
        for label in others:
            self.assertGreater(_text_box(label).x0, axes_box.x1)

    def test_dot_label_moves_off_a_line_that_runs_past_it(self):
        # Last year's line runs just above this year's dot, so the label
        # can't sit up and to the right of it
        today = datetime.date(2026, 6, 15)
        records = [
            LaunchRecord(2026, "LEO", "A", 1000, datetime.datetime(2026, 2, 1), "F9"),
            LaunchRecord(2025, "LEO", "B", 1030, datetime.datetime(2025, 2, 1), "F9"),
            LaunchRecord(2025, "LEO", "C", 5000, datetime.datetime(2025, 12, 1), "F9"),
        ]
        fig = _plot(records, today)
        fig.draw_without_rendering()
        ax = fig.axes[0]
        current = self._labels(ax)[0]
        self.assertEqual(current.get_text(), "2026")
        self.assertNotEqual(tuple(current.xyann), plotting._DOT_LABEL_OFFSETS[0])
        box = _text_box(current)
        for line in ax.lines:
            with self.subTest(line=line.get_label()):
                self.assertFalse(_step_path(line).intersects_bbox(box))

    def test_dot_label_keeps_its_first_place_when_nothing_is_clear(self):
        today = datetime.date(2026, 6, 15)
        fig = _plot(_projected_records(2020, today, _starship_era), today)
        ax = fig.axes[0]
        current = self._labels(ax)[0]
        with mock.patch.object(plotting, "_DOT_LABEL_OFFSETS", ((5, 4), (5, 4000))):
            plotting._place_beside_dot(ax, current)
            # Not clear: the label crosses the line; the far one isn't in the axes
        self.assertEqual(tuple(current.xyann), (5, 4))

    def test_level_line_ends_put_the_newer_year_above(self):
        today = _LATE
        records = [
            LaunchRecord(year, "LEO", "Sat", 5000, datetime.datetime(year, 3, 1), "F9")
            for year in (2023, 2024, 2025, 2026)
        ]
        fig = _plot(records, today)
        fig.draw_without_rendering()
        labels = self._labels(fig.axes[0])
        heights = {label.get_text(): _text_box(label).y0 for label in labels}
        self.assertGreater(heights["2026"], heights["2025"])
        self.assertGreater(heights["2025"], heights["2024"])
        self.assertGreater(heights["2024"], heights["2023"])

    def test_no_labels_without_highlighted_years(self):
        ax = _cumulative_figure(range(2017, 2020)).axes[0]
        self.assertEqual(self._labels(ax), [])


class TestCumulativeLayoutStress(unittest.TestCase):
    """Projected Starship-era data: 14 years, the newest above 20 million kg."""

    TODAY = datetime.date(2030, 11, 25)

    def setUp(self):
        self.fig = _plot(
            _projected_records(2017, self.TODAY, _starship_era),
            self.TODAY,
            caption="Data: Wikipedia contributors, CC BY-SA 4.0, launches through "
            "24 November 2030. 123 successful launches with unknown or classified "
            "payload mass count as 0 kg.",
        )
        self.fig.draw_without_rendering()
        self.ax = self.fig.axes[0]

    def test_legend_overlaps_no_data(self):
        legend = self.ax.get_legend()
        assert legend is not None
        legend_box = legend.get_window_extent()
        for line in self.ax.lines:
            with self.subTest(line=line.get_label()):
                self.assertFalse(_step_path(line).intersects_bbox(legend_box))
        for dot in self.ax.collections:
            for x, y in dot.get_offsets():
                point = self.ax.transData.transform((x, y))
                self.assertFalse(legend_box.contains(*point))

    def test_labels_are_clear_of_each_other_and_inside_the_figure(self):
        labels = [text for text in self.ax.texts if isinstance(text, Annotation)]
        self.assertEqual(
            [label.get_text() for label in labels],
            [str(year) for year in range(2030, 2022, -1)],
        )
        boxes = [_text_box(label) for label in labels]
        for box_a, box_b in itertools.combinations(boxes, 2):
            self.assertFalse(box_a.overlaps(box_b))
        axes_box = self.ax.get_window_extent()
        for label, box in zip(labels, boxes, strict=True):
            with self.subTest(year=label.get_text()):
                self.assertGreater(box.x0, axes_box.x1)
                self.assertLess(box.x1, self.fig.bbox.x1)

    def test_every_text_fits_in_the_figure(self):
        figure_box = self.fig.bbox
        low, high = self.ax.get_ylim()
        # Only the ticks within the axes' limits are drawn
        y_tick_labels = [
            label
            for tick, label in zip(
                self.ax.get_yticks(), self.ax.get_yticklabels(), strict=True
            )
            if low <= tick <= high
        ]
        texts = [
            self.ax.title,
            self.ax.yaxis.label,
            *self.ax.get_xticklabels(),
            *y_tick_labels,
            *self.fig.texts,
            *self.ax.texts,
        ]
        for text in texts:
            box = Text.get_window_extent(text)
            with self.subTest(text=text.get_text()):
                self.assertGreaterEqual(box.x0, figure_box.x0)
                self.assertLessEqual(box.x1, figure_box.x1)
                self.assertGreaterEqual(box.y0, figure_box.y0)
                self.assertLessEqual(box.y1, figure_box.y1)

    def test_y_ticks_stay_readable_at_tens_of_millions(self):
        labels = [label.get_text() for label in self.ax.get_yticklabels()]
        self.assertIn("20,000,000", labels)


class TestYearPalette(unittest.TestCase):
    def test_is_frozen(self):
        self.assertIsInstance(YEAR_COLORS, tuple)
        self.assertEqual(len(YEAR_COLORS), 8)
        self.assertEqual(len(set(YEAR_COLORS)), 8)

    def test_every_year_color_stands_out_against_white(self):
        # WCAG 2.1 SC 1.4.11 asks 3:1 for graphical objects
        for color in YEAR_COLORS:
            with self.subTest(color=color):
                self.assertGreaterEqual(contrast(color, plotting.BACKGROUND_COLOR), 3.0)

    def test_every_pair_is_distinct_with_color_vision_deficiencies(self):
        # Absolute floors, as documented next to YEAR_COLORS
        for a, b in itertools.combinations(YEAR_COLORS, 2):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(a, b), 11.5)

    def test_neighboring_slots_are_far_apart(self):
        for a, b in itertools.pairwise(YEAR_COLORS):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(a, b), 40)

    def test_dark_mode_shades_stand_out_against_both_dark_backgrounds(self):
        for color in YEAR_COLORS:
            dark = plotting.DARK_MODE_DATA_COLORS.get(color, color)
            for background in (
                plotting.DARK_BACKGROUND_COLOR,
                plotting.DARK_LEGEND_COLOR,
            ):
                with self.subTest(color=color, background=background):
                    self.assertGreaterEqual(contrast(dark, background), 3.0)

    def test_year_colors_are_not_orbit_colors(self):
        # The dark-mode stylesheet recolors by color, across both charts
        self.assertFalse(set(YEAR_COLORS) & set(plotting.ORBIT_COLORS.values()))


if __name__ == "__main__":
    unittest.main()
