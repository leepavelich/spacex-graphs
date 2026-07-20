"""Writes generated artifacts (SVG graphs, CSV export) to the outputs directory."""

import os

import pandas as pd

from spacex_graphs import cache
from spacex_graphs.config import OUTPUT_DIR
from spacex_graphs.transform import categorize_starlink, clean_orbit_category


def save_plots(fig_by_year, fig_cumulative):
    """Saves the plots as SVG files"""
    fig_by_year.savefig(
        os.path.join(OUTPUT_DIR, "payload_mass_to_orbit_by_year.svg"), format="svg"
    )
    fig_cumulative.savefig(
        os.path.join(OUTPUT_DIR, "cumulative_payload_mass_to_orbit.svg"), format="svg"
    )
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
