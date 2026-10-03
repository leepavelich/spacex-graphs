"""Smoke tests for the matplotlib figures (rendered with the Agg backend)."""

import datetime
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.plotting import (
    ORBIT_COLORS,
    plot_payload_mass_to_orbit_by_year,
)
from spacex_graphs.transform import (
    build_dataframe,
    payload_mass_by_year_orbit,
)


def _record(year, orbit, payload, mass):
    when = datetime.datetime(year, 6, 1)
    return LaunchRecord(year, orbit, payload, mass, when, "Falcon 9")


class TestPlotPayloadMassByYear(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

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
        frame.loc[0, "Orbit"] = "Lunar"
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

        for container in ax.containers:
            expected = matplotlib.colors.to_rgba(
                ORBIT_COLORS[str(container.get_label())]
            )
            self.assertEqual(container[0].get_facecolor(), expected)

        totals = [text.get_text() for text in ax.texts]
        self.assertEqual(totals, ["1,300", "2,000"])

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

    def test_titles_name_spacex_and_year_labels_are_angled(self):
        df = build_dataframe([_record(2025, "LEO", "Starlink A", 1000)])
        ax = plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit(df)).axes[0]
        self.assertTrue(ax.get_title().startswith("SpaceX "))
        self.assertEqual(ax.get_xticklabels()[0].get_rotation(), 45)


if __name__ == "__main__":
    unittest.main()
