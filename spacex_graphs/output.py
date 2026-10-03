"""Writes generated artifacts (SVG graphs, CSV export) to the outputs directory."""

import os

import matplotlib.pyplot as plt
import pandas as pd

from spacex_graphs import cache
from spacex_graphs.config import OUTPUT_DIR
from spacex_graphs.transform import categorize_starlink, clean_orbit_category


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


def save_launches_csv(records):
    """Saves all launch data to a CSV file for debugging"""
    csv_data = []
    for record in records:
        orbit_with_starlink = categorize_starlink(record.payload, record.orbit)
        orbit_category = clean_orbit_category(orbit_with_starlink)

        csv_data.append(
            {
                "Date": record.launch_datetime.strftime("%Y-%m-%d"),
                "Time (UTC)": record.launch_datetime.strftime("%H:%M:%S"),
                "Year": record.year,
                "Vehicle": record.vehicle,
                "Payload": record.payload,
                "Payload Mass (kg)": record.payload_mass,
                "Orbit": record.orbit,
                "Orbit Category": orbit_category,
            }
        )

    csv_df = pd.DataFrame(csv_data)
    csv_df["DateTime"] = pd.to_datetime(csv_df["Date"] + " " + csv_df["Time (UTC)"])
    csv_df = csv_df.sort_values("DateTime").drop(columns=["DateTime"])

    csv_path = os.path.join(OUTPUT_DIR, "spacex_launches.csv")
    csv_df.to_csv(csv_path, index=False)
    print(f"Launch data saved to {csv_path}")
