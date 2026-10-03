"""Writes generated artifacts (SVG graphs, CSV export) to the outputs directory."""

import logging
import os

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from spacex_graphs.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

# matplotlib otherwise embeds a <dc:date> timestamp and random clip-path/glyph
# IDs, so identical data produced a different SVG (and a noisy commit) every run
_SVG_HASH_SALT = "spacex-graphs"


def _save_svg(fig: Figure, filename: str) -> None:
    with plt.rc_context({"svg.hashsalt": _SVG_HASH_SALT}):
        fig.savefig(
            os.path.join(OUTPUT_DIR, filename),
            format="svg",
            metadata={"Date": None},
        )


def save_plots(fig_by_year: Figure, fig_cumulative: Figure) -> None:
    """Saves the plots as SVG files, byte-identical for identical figures."""
    _save_svg(fig_by_year, "payload_mass_to_orbit_by_year.svg")
    _save_svg(fig_cumulative, "cumulative_payload_mass_to_orbit.svg")


def save_launches_csv(df: pd.DataFrame) -> None:
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
    logger.info("Launch data saved to %s", csv_path)
