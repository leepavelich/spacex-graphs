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
        self.assertEqual(legend_labels, list(ORBIT_COLORS))


if __name__ == "__main__":
    unittest.main()
