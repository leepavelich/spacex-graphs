"""Tests for the bar chart, the shared figure setup, and both palettes.

The figures render on their own Agg canvases, without pyplot.
"""

import datetime
import itertools
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.colors as mcolors
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.typing import RcKeyType

from spacex_graphs import output, plotting
from spacex_graphs.config import ORBIT_CATEGORIES
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.plotting import (
    ORBIT_COLORS,
    SECONDARY_TEXT_COLOR,
    _format_bar_total,
    plot_payload_mass_to_orbit_by_year,
)
from spacex_graphs.transform import (
    Col,
    YearOrbitFrame,
    build_cumulative_frame,
    build_dataframe,
    payload_mass_by_year_orbit,
)

ROOT = Path(__file__).resolve().parents[1]

# Machado, Oliveira & Fernandes (2009) full-severity simulation matrices, which
# act on linear RGB
CVD_SIMULATIONS = {
    "normal": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}


def _linear_rgb(color):
    return [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in mcolors.to_rgb(color)
    ]


def _relative_luminance(color):
    r, g, b = _linear_rgb(color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(color_a, color_b):
    """WCAG 2 contrast ratio between two colors."""
    darker, lighter = sorted(
        (_relative_luminance(color_a), _relative_luminance(color_b))
    )
    return (lighter + 0.05) / (darker + 0.05)


def contrast_against_white(color):
    """WCAG 2 contrast ratio between the color and white."""
    return contrast(color, "#ffffff")


def in_dark_mode(color):
    """The color as the dark-mode stylesheet shows it."""
    return plotting.DARK_MODE_DATA_COLORS.get(color, color)


def cielab(color, vision="normal"):
    """The color as seen with the given vision, in CIELAB (D65 white)."""
    rgb = _linear_rgb(color)
    r, g, b = (
        min(1.0, max(0.0, sum(m * c for m, c in zip(row, rgb, strict=True))))
        for row in CVD_SIMULATIONS[vision]
    )
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def worst_delta_e(color_a, color_b):
    """The smallest CIE76 ΔE between two colors across all simulated visions."""
    return min(
        math.dist(cielab(color_a, vision), cielab(color_b, vision))
        for vision in CVD_SIMULATIONS
    )


def _record(year, orbit, payload, mass):
    when = datetime.datetime(year, 6, 1)
    return LaunchRecord(year, orbit, payload, mass, when, "Falcon 9")


def _frame(totals_by_year):
    """A by-year frame with each year's whole total in one category."""
    return YearOrbitFrame(
        pd.DataFrame(
            {
                Col.YEAR: list(totals_by_year),
                Col.ORBIT: ["LEO (Starlink)"] * len(totals_by_year),
                Col.MASS: list(totals_by_year.values()),
            }
        )
    )


class TestOrbitPalette(unittest.TestCase):
    def test_keyed_by_category_name_in_legend_order(self):
        self.assertEqual(tuple(ORBIT_COLORS), ORBIT_CATEGORIES)

    def test_is_read_only(self):
        with self.assertRaises(TypeError):
            ORBIT_COLORS["MEO"] = "red"  # type: ignore[index]

    def test_simulation_matches_the_known_bad_pair(self):
        # The old LEO (Starlink) and SSO (Starlink) colors were nearly
        # identical with deuteranopia; this anchors the model to that figure
        self.assertAlmostEqual(
            math.dist(
                cielab("#d2691e", "deuteranopia"), cielab("#b8860b", "deuteranopia")
            ),
            3.4,
            places=1,
        )

    def test_every_color_stands_out_against_white(self):
        # WCAG 2.1 SC 1.4.11 asks 3:1 for graphical objects
        for category, color in ORBIT_COLORS.items():
            with self.subTest(category=category, color=color):
                self.assertGreaterEqual(contrast_against_white(color), 3.0)

    def test_every_pair_is_distinct_with_color_vision_deficiencies(self):
        for (a, color_a), (b, color_b) in itertools.combinations(
            ORBIT_COLORS.items(), 2
        ):
            with self.subTest(a=a, b=b):
                # As documented next to ORBIT_COLORS
                self.assertGreaterEqual(worst_delta_e(color_a, color_b), 17.9)

    def test_stacked_neighbors_are_far_apart(self):
        stack = list(ORBIT_COLORS.items())
        for (a, color_a), (b, color_b) in itertools.pairwise(stack):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(color_a, color_b), 30)


class TestDarkPalette(unittest.TestCase):
    """The dark-mode stylesheet keeps data and text readable on its background."""

    BACKGROUND = plotting.DARK_BACKGROUND_COLOR
    DATA_COLORS = (
        *ORBIT_COLORS.values(),
        *plotting.YEAR_COLORS,
        plotting.OLDER_YEARS_COLOR,
    )

    BACKGROUNDS = (BACKGROUND, plotting.DARK_LEGEND_COLOR)

    def test_every_data_color_stands_out_against_the_dark_backgrounds(self):
        # The legend's swatches sit on its own, slightly lighter background
        for color, background in itertools.product(self.DATA_COLORS, self.BACKGROUNDS):
            with self.subTest(color=color, background=background):
                self.assertGreaterEqual(contrast(in_dark_mode(color), background), 3.0)

    def test_only_data_colors_are_replaced(self):
        self.assertLessEqual(set(plotting.DARK_MODE_DATA_COLORS), set(self.DATA_COLORS))
        for light, dark in plotting.DARK_MODE_DATA_COLORS.items():
            with self.subTest(light=light):
                # Lowercase, as matplotlib writes colors in the SVG
                self.assertEqual(light, mcolors.to_hex(light))
                self.assertEqual(dark, mcolors.to_hex(dark))
                self.assertLess(
                    min(contrast(light, background) for background in self.BACKGROUNDS),
                    3.0,
                )
                self.assertNotIn(dark, self.DATA_COLORS)

    def test_dark_orbit_colors_stay_distinct_with_color_vision_deficiencies(self):
        dark = {name: in_dark_mode(color) for name, color in ORBIT_COLORS.items()}
        for (a, color_a), (b, color_b) in itertools.combinations(dark.items(), 2):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(color_a, color_b), 15)
        for (a, color_a), (b, color_b) in itertools.pairwise(dark.items()):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(color_a, color_b), 30)

    def test_dark_year_colors_stay_distinct_with_color_vision_deficiencies(self):
        dark = [in_dark_mode(color) for color in plotting.YEAR_COLORS]
        for a, b in itertools.combinations(dark, 2):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(a, b), 11.5)
        for a, b in itertools.pairwise(dark):
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(worst_delta_e(a, b), 35)

    def test_text_is_readable_on_the_dark_backgrounds(self):
        for background in (self.BACKGROUND, plotting.DARK_LEGEND_COLOR):
            with self.subTest(background=background):
                self.assertGreaterEqual(
                    contrast(plotting.DARK_TEXT_COLOR, background), 7.0
                )
                self.assertGreaterEqual(
                    contrast(plotting.DARK_SECONDARY_TEXT_COLOR, background), 4.5
                )

    def test_gridlines_are_subtle_but_visible(self):
        self.assertGreater(contrast(plotting.DARK_GRID_COLOR, self.BACKGROUND), 1.3)
        self.assertLess(contrast(plotting.DARK_GRID_COLOR, self.BACKGROUND), 3.0)

    def test_neutrals_are_never_data_colors(self):
        # The stylesheet finds neutral elements by these colors, so a series
        # in one of them would be recolored as if it were a gridline
        neutrals = {
            plotting.BACKGROUND_COLOR,
            plotting.TEXT_COLOR,
            plotting.GRID_COLOR,
            plotting.LEGEND_EDGE_COLOR,
            plotting.SEGMENT_EDGE_COLOR,
            SECONDARY_TEXT_COLOR,
        }
        self.assertEqual(neutrals & set(self.DATA_COLORS), set())


class TestFormatBarTotal(unittest.TestCase):
    def test_scales(self):
        cases = {
            0: "0",
            500: "500",
            950: "950",
            999.4: "999",
            999.6: "1.0k",
            5_800: "5.8k",
            9_949: "9.9k",
            9_950: "10k",
            91_200: "91k",
            999_499: "999k",
            999_500: "1.00M",
            1_571_352: "1.57M",
            2_190_555: "2.19M",
            9_995_000: "10.0M",
            12_400_000: "12.4M",
            123_456_789: "123M",
        }
        for total, expected in cases.items():
            with self.subTest(total=total):
                self.assertEqual(_format_bar_total(total), expected)

    def test_labels_stay_short(self):
        for exponent in range(0, 10):
            for mantissa in (1, 2.5, 4.99, 9.99):
                total = mantissa * 10**exponent
                with self.subTest(total=total):
                    self.assertLessEqual(len(_format_bar_total(total)), 5)


class TestPlotPayloadMassByYear(unittest.TestCase):
    def test_missing_orbit_categories_plot_as_zero(self):
        # Only two of the ten categories are present; this used to raise KeyError
        df = build_dataframe(
            [
                _record(2015, "LEO (ISS)", "CRS-6", 2000),
                _record(2015, "GTO", "TurkmenAlem52E", 4700),
            ]
        )
        fig = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df))
        ax = fig.axes[0]
        self.assertEqual(len(ax.containers), len(ORBIT_COLORS))
        legend = ax.get_legend()
        assert legend is not None
        legend_labels = [t.get_text() for t in legend.get_texts()]
        # Top to bottom in the order the segments are stacked
        self.assertEqual(legend_labels, list(ORBIT_COLORS)[::-1])

    def test_category_without_a_color_is_an_error_not_dropped(self):
        frame = payload_mass_by_year_orbit(
            build_dataframe([_record(2015, "LEO", "CRS-6", 2000)])
        )
        frame.loc[0, Col.ORBIT] = "Lunar"
        with self.assertRaises(ValueError) as ctx:
            plot_payload_mass_to_orbit_by_year(frame)
        self.assertIn("Lunar", str(ctx.exception))

    def test_bars_stack_each_category_with_its_color_and_label_totals(self):
        df = build_dataframe(
            [
                _record(2024, "LEO", "Starlink A", 1000),
                _record(2024, "GTO", "SES", 300),
                _record(2025, "LEO", "Starlink B", 2000),
            ]
        )
        ax = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df)).axes[0]
        segments = {
            container.get_label(): [patch.get_height() for patch in container]
            for container in ax.containers
        }
        self.assertEqual(segments["LEO (Starlink)"], [1000, 2000])
        self.assertEqual(segments["GTO/GEO"], [300, 0])

        # Stacked: each GTO/GEO segment sits on top of the categories before it
        gto = ax.containers[list(ORBIT_COLORS).index("GTO/GEO")]
        self.assertEqual(gto[0].get_y(), 1000)

        colors = {str(category): color for category, color in ORBIT_COLORS.items()}
        for container in ax.containers:
            expected = mcolors.to_rgba(colors[str(container.get_label())])
            self.assertEqual(container[0].get_facecolor(), expected)
            # Thin white edges separate the stacked segments
            self.assertEqual(container[0].get_edgecolor(), mcolors.to_rgba("white"))
            self.assertEqual(container[0].get_linewidth(), 0.35)

        totals = [text.get_text() for text in ax.texts]
        self.assertEqual(totals, ["1.3k", "2.0k"])
        for text in ax.texts:
            self.assertEqual(
                mcolors.to_hex(text.get_color()), SECONDARY_TEXT_COLOR.lower()
            )

    def test_current_year_is_marked_ytd_and_caption_is_shown(self):
        df = build_dataframe(
            [_record(2025, "LEO", "Starlink A", 1000), _record(2026, "GTO", "SES", 300)]
        )
        fig = plot_payload_mass_to_orbit_by_year(
            payload_mass_by_year_orbit(df), current_year=2026, caption="Source: test"
        )
        labels = [label.get_text() for label in fig.axes[0].get_xticklabels()]
        self.assertEqual(labels, ["2025", "2026 YTD"])
        self.assertEqual([text.get_text() for text in fig.texts], ["Source: test"])
        self.assertEqual(mcolors.to_hex(fig.texts[0].get_color()), "#595959")

    def test_titles_name_spacex_and_year_labels_are_angled(self):
        df = build_dataframe([_record(2025, "LEO", "Starlink A", 1000)])
        ax = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df)).axes[0]
        self.assertTrue(ax.get_title().startswith("SpaceX "))
        self.assertEqual(ax.get_ylabel(), "Payload Mass (kg)")
        self.assertEqual(ax.get_xlabel(), "")
        self.assertEqual(ax.get_xticklabels()[0].get_rotation(), 45)

    def test_gridlines_are_drawn_behind_the_bars(self):
        df = build_dataframe([_record(2025, "LEO", "Starlink A", 1000)])
        ax = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df)).axes[0]
        self.assertIs(ax.get_axisbelow(), True)
        # Horizontal gridlines only: vertical ones would run through the bars
        self.assertTrue(all(line.get_visible() for line in ax.get_ygridlines()))
        self.assertFalse(any(line.get_visible() for line in ax.get_xgridlines()))

    def test_totals_fit_their_bars_and_the_axes(self):
        # Nineteen years, the newest above 10 million kg: narrower bars and
        # longer totals than the charts have yet needed
        totals = {
            year: 12_400_000 - (2030 - year) * 600_000 for year in range(2012, 2031)
        }
        fig = plot_payload_mass_to_orbit_by_year(_frame(totals), current_year=2030)
        ax = fig.axes[0]
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
        axes_box = ax.get_window_extent(renderer)
        bars = list(ax.containers[0])
        pitch = (
            bars[1].get_window_extent(renderer).x0
            - bars[0].get_window_extent(renderer).x0
        )
        self.assertEqual(len(ax.texts), len(totals))
        for text in ax.texts:
            box = text.get_window_extent(renderer)
            with self.subTest(label=text.get_text()):
                self.assertLess(box.width, 0.9 * pitch)
                self.assertLess(box.x1, axes_box.x1)
                # Headroom keeps the tallest total off the top border
                self.assertLess(box.y1, axes_box.y1 - 2)

    def test_tallest_bar_leaves_headroom(self):
        ax = plot_payload_mass_to_orbit_by_year(_frame({2025: 2_190_555})).axes[0]
        self.assertAlmostEqual(ax.get_ylim()[1], 2_190_555 * 1.08)

    def test_small_totals_dont_repeat_zero_ticks(self):
        fig = plot_payload_mass_to_orbit_by_year(_frame({2025: 3}))
        ax = fig.axes[0]
        fig.canvas.draw()
        labels = [label.get_text() for label in ax.get_yticklabels()]
        self.assertEqual(len(labels), len(set(labels)), labels)

    def test_y_ticks_have_thousands_separators(self):
        fig = plot_payload_mass_to_orbit_by_year(_frame({2025: 2_190_555}))
        ax = fig.axes[0]
        fig.canvas.draw()
        labels = [label.get_text() for label in ax.get_yticklabels()]
        self.assertIn("2,000,000", labels)

    def test_legend_is_pinned_top_left(self):
        fig = plot_payload_mass_to_orbit_by_year(_frame({2024: 100, 2025: 200}))
        ax = fig.axes[0]
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
        legend = ax.get_legend()
        assert legend is not None
        legend_box = legend.get_window_extent(renderer)
        axes_box = ax.get_window_extent(renderer)
        self.assertLess(legend_box.x0 - axes_box.x0, 20)
        self.assertLess(axes_box.y1 - legend_box.y1, 20)

    def test_zero_mass_years_draw_zero_height_bars(self):
        # Only failures and unknown masses: bars of height 0, labelled "0",
        # on a unit axis that still starts at 0
        df = build_dataframe(
            [
                _record(2025, "LEO", "Starlink A", None),
                _record(2026, "LEO", "Lost", 5000)._replace(outcome="Failure"),
            ]
        )
        ax = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df)).axes[0]
        self.assertEqual([text.get_text() for text in ax.texts], ["0", "0"])
        self.assertTrue(
            all(patch.get_height() == 0 for c in ax.containers for patch in c)
        )
        self.assertEqual(ax.get_ylim(), (0, 1))

    def test_empty_frame_draws_an_empty_chart(self):
        df = build_dataframe([])
        fig = plot_payload_mass_to_orbit_by_year(
            payload_mass_by_year_orbit(df), current_year=2026, caption="Source: test"
        )
        ax = fig.axes[0]
        self.assertEqual(ax.containers, [])
        self.assertEqual([t.get_text() for t in ax.texts], ["No launches to show"])
        self.assertEqual([text.get_text() for text in fig.texts], ["Source: test"])


class TestBarLayoutStress(unittest.TestCase):
    """Projected Starship-era data: 21 years, the newest above 20 million kg,
    with every category in every year."""

    def setUp(self):
        years = range(2010, 2031)
        rows = [
            (year, category, _projected_total(year) * share)
            for year in years
            for category, share in zip(ORBIT_COLORS, _CATEGORY_SHARES, strict=True)
        ]
        frame = YearOrbitFrame(
            pd.DataFrame(rows, columns=[Col.YEAR, Col.ORBIT, Col.MASS])
        )
        self.fig = plot_payload_mass_to_orbit_by_year(
            frame, current_year=2030, caption="Source: test"
        )
        self.fig.draw_without_rendering()
        self.ax = self.fig.axes[0]

    def test_legend_covers_no_bars_or_totals(self):
        legend = self.ax.get_legend()
        assert legend is not None
        legend_box = legend.get_window_extent()
        for container in self.ax.containers:
            for bar in container:
                with self.subTest(category=container.get_label()):
                    self.assertFalse(bar.get_window_extent().overlaps(legend_box))
        for text in self.ax.texts:
            with self.subTest(total=text.get_text()):
                self.assertFalse(text.get_window_extent().overlaps(legend_box))

    def test_everything_fits_in_the_figure(self):
        figure_box = self.fig.bbox
        legend = self.ax.get_legend()
        assert legend is not None
        artists = [
            self.ax.title,
            self.ax.yaxis.label,
            legend,
            *self.ax.get_xticklabels(),
            *self.ax.texts,
            *self.fig.texts,
        ]
        for artist in artists:
            box = artist.get_window_extent()
            with self.subTest(artist=artist):
                self.assertGreaterEqual(box.x0, figure_box.x0)
                self.assertLessEqual(box.x1, figure_box.x1)
                self.assertGreaterEqual(box.y0, figure_box.y0)
                self.assertLessEqual(box.y1, figure_box.y1)


# Each category's share of a year's mass, in ORBIT_COLORS order
_CATEGORY_SHARES = (0.62, 0.08, 0.12, 0.03, 0.02, 0.06, 0.01, 0.01, 0.04, 0.01)


def _projected_total(year):
    # Tiny early years, today's ~2.2 million kg, then 60% growth a year
    if year <= 2016:
        return 5_000 * (year - 2009)
    return (
        2_200_000 * 1.6 ** (year - 2025)
        if year >= 2025
        else 2_200_000 / 1.9 ** (2025 - year)
    )


# Local settings that savefig and the renderers read at save time
_SAVE_TIME_POLLUTION: dict[RcKeyType, Any] = {
    "savefig.transparent": True,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 1.5,
    "savefig.facecolor": "red",
    "savefig.edgecolor": "blue",
    "savefig.dpi": 37,
    "path.simplify": False,
    "path.simplify_threshold": 1.0,
    "path.sketch": (5, 50, 2),
    "svg.fonttype": "none",
    "svg.hashsalt": "local",
    "font.family": "serif",
    "grid.color": "red",
    "xtick.color": "green",
    "text.color": "blue",
}


def _saved_charts(directory):
    """Builds and saves both charts, returning each SVG's bytes."""
    today = datetime.date(2026, 10, 3)
    df = build_dataframe(
        [
            _record(2025, "LEO", "Starlink A", 1000),
            _record(2026, "GTO", "SES", 4000),
        ]
    )
    figures = {
        "by_year.svg": plot_payload_mass_to_orbit_by_year(
            payload_mass_by_year_orbit(df), current_year=today.year, caption="Test"
        ),
        "cumulative.svg": plotting.plot_cumulative_payload_mass_to_orbit(
            build_cumulative_frame(df, today), today, caption="Test"
        ),
    }
    output.save_plots(figures, output_dir=directory)
    return {name: Path(directory, name).read_bytes() for name in figures}


class TestRenderIsolation(unittest.TestCase):
    def test_local_settings_change_neither_building_nor_saving(self):
        with tempfile.TemporaryDirectory() as clean_dir:
            clean = _saved_charts(clean_dir)
        with (
            tempfile.TemporaryDirectory() as polluted_dir,
            matplotlib.rc_context(_SAVE_TIME_POLLUTION),
        ):
            polluted = _saved_charts(polluted_dir)
            # The caller's settings are back in force afterwards
            self.assertIs(matplotlib.rcParams["savefig.transparent"], True)
            self.assertEqual(matplotlib.rcParams["svg.hashsalt"], "local")
        self.assertEqual(polluted, clean)
        for content in clean.values():
            self.assertNotIn(b"<text", content)  # glyphs are paths

    def test_local_matplotlib_settings_dont_change_the_render(self):
        df = build_dataframe([_record(2025, "LEO", "Starlink A", 1000)])
        with matplotlib.rc_context(
            {
                "font.family": "serif",
                "figure.facecolor": "black",
                "axes.facecolor": "black",
                "lines.linewidth": 5,
                "grid.color": "red",
                "text.color": "blue",
            }
        ):
            fig = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df))
            # The caller's settings are back in force afterwards
            self.assertEqual(matplotlib.rcParams["font.family"], ["serif"])
        ax = fig.axes[0]
        self.assertEqual(fig.get_facecolor(), mcolors.to_rgba("white"))
        self.assertEqual(ax.get_facecolor(), mcolors.to_rgba("white"))
        self.assertEqual(ax.title.get_fontfamily(), ["DejaVu Sans"])
        # The neutrals the dark-mode stylesheet matches are pinned too
        self.assertEqual(mcolors.to_hex(ax.title.get_color()), plotting.TEXT_COLOR)
        gridline = ax.get_ygridlines()[0]
        self.assertEqual(mcolors.to_hex(gridline.get_color()), plotting.GRID_COLOR)


class TestObjectOrientedFigures(unittest.TestCase):
    def test_figures_have_their_own_agg_canvas(self):
        fig = plot_payload_mass_to_orbit_by_year(_frame({2025: 1000}))
        self.assertIsInstance(fig, Figure)
        self.assertIsInstance(fig.canvas, FigureCanvasAgg)
        # Not registered with pyplot, so there is nothing to close
        self.assertIsNone(fig.canvas.manager)

    def test_building_and_saving_charts_never_imports_pyplot(self):
        script = """
import datetime, sys, tempfile
from spacex_graphs import cli, output, plotting, transform
from spacex_graphs.parsing import LaunchRecord
today = datetime.date(2026, 10, 3)
df = transform.build_dataframe(
    [LaunchRecord(2026, "LEO", "Sat", 5, datetime.datetime(2026, 9, 1), "F9")]
)
figures = {
    output.BY_YEAR_SVG: plotting.plot_payload_mass_to_orbit_by_year(
        transform.payload_mass_by_year_orbit(df), current_year=2026
    ),
    output.CUMULATIVE_SVG: plotting.plot_cumulative_payload_mass_to_orbit(
        transform.build_cumulative_frame(df, today), today
    ),
}
with tempfile.TemporaryDirectory() as directory:
    output.save_plots(figures, output_dir=directory)
print("matplotlib.pyplot" in sys.modules)
"""
        # The interpreter and script are fixed by this test, not user input
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
