"""Transforms parsed launch records into the DataFrames the plots consume."""

import datetime
import re
from collections.abc import Sequence

import pandas as pd

from spacex_graphs.config import MIN_CUMULATIVE_YEAR, ORBIT_MAPPING
from spacex_graphs.parsing import LaunchRecord


def clean_orbit_category(orbit: str) -> str:
    """Cleans the orbit category by removing square brackets and mapping to a category.

    Orbits not in ORBIT_MAPPING fall back to a LEO category when they are
    clearly a low Earth orbit variant (e.g. "Elliptical LEO"), otherwise "Other".
    """
    orbit_cleaned = re.sub(r"\[.*?\]", "", orbit).strip()
    if orbit_cleaned in ORBIT_MAPPING:
        return ORBIT_MAPPING[orbit_cleaned]
    if re.search(r"\bLEO\b|low earth orbit", orbit_cleaned, flags=re.IGNORECASE):
        return "LEO (Starlink)" if "(Starlink)" in orbit_cleaned else "LEO (Other)"
    return "Other"


def categorize_starlink(payload: str, orbit: str) -> str:
    """Categorizes the orbit as Starlink if the payload contains 'Starlink'.

    The tag is not doubled when Wikipedia already labels the orbit "(Starlink)".
    """
    if "Starlink" in payload and "(Starlink)" not in orbit:
        return f"{orbit} (Starlink)"
    return orbit


def launch_succeeded(outcome: str) -> bool:
    """Whether a launch's payload mass counts toward the graphs.

    Wikipedia's outcomes include "Success", "Failure", "Precluded (pre-flight
    failure)", and, for the 2020 Crew Dragon abort test, "Successful simulated
    failure", which did deliver its payload. Matching the start of the text
    keeps "Unsuccessful" or "Partial success" from counting.
    """
    return outcome.lower().startswith("success")


def build_dataframe(records: Sequence[LaunchRecord]) -> pd.DataFrame:
    """Builds the launch DataFrame with standardized orbit categories.

    "Orbit" holds the category used by the graphs and "RawOrbit" the
    Wikipedia text. "ReportedMass" is the mass Wikipedia gives (missing when
    unknown), and "PayloadMass" is the mass the graphs count: the reported
    mass for successful launches, and 0 for failures or unknown masses.
    """
    df = pd.DataFrame(
        {
            "Year": [r.year for r in records],
            "RawOrbit": [r.orbit for r in records],
            "Payload": [r.payload for r in records],
            "ReportedMass": pd.array([r.payload_mass for r in records], dtype="Int64"),
            "PayloadMass": [
                (r.payload_mass or 0) if launch_succeeded(r.outcome) else 0
                for r in records
            ],
            "DateTime": pd.to_datetime([r.launch_datetime for r in records]),
            "Vehicle": [r.vehicle for r in records],
            "Outcome": [r.outcome for r in records],
        }
    )
    df["Orbit"] = [
        clean_orbit_category(categorize_starlink(r.payload, r.orbit)) for r in records
    ]
    return df


def payload_mass_by_year_orbit(df: pd.DataFrame) -> pd.DataFrame:
    """Sums payload mass grouped by year and orbit category."""
    return df.groupby(["Year", "Orbit"])["PayloadMass"].sum().reset_index()


def _period_end(year: int, today: datetime.date) -> datetime.datetime:
    """The last day plotted for a year: today for the current year."""
    if year == today.year:
        return datetime.datetime.combine(today, datetime.time())
    return datetime.datetime(year, 12, 31)


def build_cumulative_frame(df: pd.DataFrame, today: datetime.date) -> pd.DataFrame:
    """Builds the per-year cumulative payload mass series for plotting.

    Each year from MIN_CUMULATIVE_YEAR onwards gets a zero-mass point on
    January 1st, so its line starts at the origin, and a point at the end of
    its period (December 31st, or `today` for the current year), so its line
    extends to there. Returns one row per point, with "DayOfYear" and
    "CumulativePayloadMass" ready to plot.
    """
    df = df[df["Year"] >= MIN_CUMULATIVE_YEAR]
    boundaries: list[dict[str, object]] = []
    for year in df["Year"].unique():
        for when in (datetime.datetime(year, 1, 1), _period_end(year, today)):
            boundaries.append({"Year": year, "PayloadMass": 0, "DateTime": when})

    points = pd.concat(
        [pd.DataFrame(boundaries), df[["Year", "PayloadMass", "DateTime"]]],
        ignore_index=True,
    )
    points["DateTime"] = pd.to_datetime(points["DateTime"])
    # Stable sort keeps the zero-mass January 1st point ahead of any launch
    # at exactly midnight, so cumulative sums never step backwards
    points = points.sort_values(["Year", "DateTime"], kind="stable")
    points["CumulativePayloadMass"] = points.groupby("Year")["PayloadMass"].cumsum()
    points["DayOfYear"] = points["DateTime"].dt.dayofyear
    return points.reset_index(drop=True)
