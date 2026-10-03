"""Writes generated artifacts (SVG graphs, CSV export) to the outputs directory."""

import os

import matplotlib.pyplot as plt
import pandas as pd

from spacex_graphs import cache
from spacex_graphs.config import OUTPUT_DIR


# matplotlib otherwise embeds a <dc:date> timestamp and random clip-path/glyph
# IDs, so identical data produced a different SVG (and a noisy commit) every run
_DETERMINISTIC_SVG_RC = {"svg.hashsalt": "spacex-graphs"}
_DETERMINISTIC_SVG_METADATA = {"Date": None}


def _save_svg(fig, filename):
    with plt.rc_context(_DETERMINISTIC_SVG_RC):
        fig.savefig(
            os.path.join(OUTPUT_DIR, filename),
            format="svg",
            metadata=_DETERMINISTIC_SVG_METADATA,
        )


def save_plots(fig_by_year, fig_cumulative):
    """Saves the plots as SVG files, byte-identical for identical figures."""
    _save_svg(fig_by_year, "payload_mass_to_orbit_by_year.svg")
    _save_svg(fig_cumulative, "cumulative_payload_mass_to_orbit.svg")
    cache.write_last_run_date()


def save_launches_csv(df):
    """Saves all launches, with raw and categorized orbits, to a CSV file.

    Takes the frame from transform.build_dataframe so the CSV's orbit
    categories always match the graphs.
    """
    launches = df.sort_values("DateTime", kind="stable")
    csv_df = pd.DataFrame(
        {
            "Date": launches["DateTime"].dt.strftime("%Y-%m-%d"),
            "Time (UTC)": launches["DateTime"].dt.strftime("%H:%M:%S"),
            "Year": launches["Year"],
            "Vehicle": launches["Vehicle"],
            "Payload": launches["Payload"],
            "Payload Mass (kg)": launches["PayloadMass"],
            "Orbit": launches["RawOrbit"],
            "Orbit Category": launches["Orbit"],
        }
    )

    csv_path = os.path.join(OUTPUT_DIR, "spacex_launches.csv")
    csv_df.to_csv(csv_path, index=False)
    print(f"Launch data saved to {csv_path}")
