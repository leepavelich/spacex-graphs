"""Writes generated artifacts (SVG graphs, CSV export) to the outputs directory."""

import logging
import os
from collections import Counter

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

# matplotlib otherwise embeds a <dc:date> timestamp and random clip-path/glyph
# IDs, so identical data produced a different SVG (and a noisy commit) every run
_SVG_HASH_SALT = "spacex-graphs"


def _save_svg(fig: Figure, path: str) -> None:
    with plt.rc_context({"svg.hashsalt": _SVG_HASH_SALT}):
        fig.savefig(
            path,
            format="svg",
            metadata={"Date": None},
        )


BY_YEAR_SVG = "payload_mass_to_orbit_by_year.svg"
CUMULATIVE_SVG = "cumulative_payload_mass_to_orbit.svg"
LAUNCHES_CSV = "spacex_launches.csv"
# The README embeds the SVGs and the scheduled workflow commits these files
# by name, so they must stay stable
OUTPUT_FILES = (BY_YEAR_SVG, CUMULATIVE_SVG, LAUNCHES_CSV)


def missing_outputs(output_dir: str) -> list[str]:
    """Lists the output files that don't exist yet."""
    return [
        name
        for name in OUTPUT_FILES
        if not os.path.exists(os.path.join(output_dir, name))
    ]


def save_plots(fig_by_year: Figure, fig_cumulative: Figure, *, output_dir: str) -> None:
    """Saves the plots as SVG files, byte-identical for identical figures."""
    _save_svg(fig_by_year, os.path.join(output_dir, BY_YEAR_SVG))
    _save_svg(fig_cumulative, os.path.join(output_dir, CUMULATIVE_SVG))


def published_launch_counts(output_dir: str) -> dict[int, int]:
    """Counts launches per year in the published CSV, or {} if there isn't one.

    The committed CSV is the baseline the next run is checked against.
    """
    csv_path = os.path.join(output_dir, LAUNCHES_CSV)
    if not os.path.exists(csv_path):
        return {}
    years = pd.read_csv(csv_path, usecols=["Year"])["Year"]
    return dict(Counter(int(year) for year in years))


def save_launches_csv(df: pd.DataFrame, *, output_dir: str) -> None:
    """Saves all launches, with raw and categorized orbits, to a CSV file.

    "Payload Mass (kg)" is what Wikipedia reports, blank when unknown or
    classified; "Counted Mass (kg)" is what the graphs sum, which is 0 for
    failed launches and unknown masses.

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
            "Payload Mass (kg)": launches["ReportedMass"],
            "Orbit": launches["RawOrbit"],
            "Orbit Category": launches["Orbit"],
            "Outcome": launches["Outcome"],
            "Counted Mass (kg)": launches["PayloadMass"],
        }
    )

    csv_path = os.path.join(output_dir, LAUNCHES_CSV)
    csv_df.to_csv(csv_path, index=False)
    logger.info("Launch data saved to %s", csv_path)
