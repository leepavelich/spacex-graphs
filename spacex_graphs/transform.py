"""Transforms parsed launch records into the DataFrames the plots consume."""

import datetime
import re
from collections.abc import Sequence
from types import MappingProxyType
from typing import Final

import pandas as pd

from spacex_graphs.config import (
    GTO_GEO,
    LEO_OTHER,
    LEO_STARLINK,
    MEO,
    MIN_CUMULATIVE_YEAR,
    ORBIT_MAPPING,
    OTHER_ORBIT,
    SSO_OTHER,
    SSO_STARLINK,
    TRANSATMOSPHERIC,
    OrbitCategory,
)
from spacex_graphs.parsing import FOOTNOTE, LaunchRecord
from spacex_graphs.validation import OutcomeKind, outcome_kind


class Col:
    """Column names of the frames built here.

    Plotting and output import these instead of repeating the strings, so the
    frames' shape is one visible contract rather than an implicit one.
    """

    YEAR: Final = "Year"
    RAW_ORBIT: Final = "RawOrbit"
    ORBIT: Final = "Orbit"
    PAYLOAD: Final = "Payload"
    REPORTED_MASS: Final = "ReportedMass"
    MASS: Final = "PayloadMass"
    DATETIME: Final = "DateTime"
    VEHICLE: Final = "Vehicle"
    OUTCOME: Final = "Outcome"
    DAY_OF_YEAR: Final = "DayOfYear"
    CUMULATIVE_MASS: Final = "CumulativePayloadMass"


_CASEFOLDED_ORBITS = MappingProxyType(
    {raw.casefold(): category for raw, category in ORBIT_MAPPING.items()}
)

_ORBIT_PATTERNS: tuple[tuple[re.Pattern[str], OrbitCategory], ...] = (
    (re.compile(r"\b(?:sub[-–— ]?orbital|transatmospheric)\b"), TRANSATMOSPHERIC),
    (re.compile(r"\b(?:sso|sun[-–— ]synchronous)\b"), SSO_OTHER),
    (re.compile(r"\b(?:gto|geo|geostationary)\b"), GTO_GEO),
    (re.compile(r"\b(?:meo|medium earth orbit)\b"), MEO),
    (re.compile(r"\b(?:leo|low earth orbit)\b"), LEO_OTHER),
)


def _starlink_category(category: OrbitCategory) -> OrbitCategory:
    if category == LEO_OTHER:
        return LEO_STARLINK
    if category == SSO_OTHER:
        return SSO_STARLINK
    return category


def clean_orbit_category(orbit: str) -> OrbitCategory:
    """Maps raw orbit text, without footnotes, to a configured category."""
    cleaned = " ".join(FOOTNOTE.sub("", orbit).casefold().split())
    known = _CASEFOLDED_ORBITS.get(cleaned)
    if known is not None:
        return known
    for pattern, category in _ORBIT_PATTERNS:
        if pattern.search(cleaned):
            return _starlink_category(category) if "(starlink)" in cleaned else category
    return OTHER_ORBIT


def categorize_starlink(payload: str, orbit: str) -> OrbitCategory:
    """Maps the raw orbit first, then tags Starlink payloads in LEO or SSO."""
    category = clean_orbit_category(orbit)
    return _starlink_category(category) if "Starlink" in payload else category


def launch_succeeded(outcome: str) -> bool:
    """Whether a launch's payload mass counts toward the graphs.

    Qualified failures (even after "Success") don't count. The Crew Dragon
    abort test is a success because it delivered its test payload.
    """
    return outcome_kind(outcome) is OutcomeKind.SUCCESS


def build_dataframe(records: Sequence[LaunchRecord]) -> pd.DataFrame:
    """Builds the launch DataFrame with standardized orbit categories.

    "Orbit" holds the category used by the graphs and "RawOrbit" the
    Wikipedia text. "ReportedMass" is the mass Wikipedia gives (missing when
    unknown), and "PayloadMass" is the mass the graphs count: the reported
    mass for successful launches, and 0 for failures or unknown masses.
    """
    df = pd.DataFrame(
        {
            Col.YEAR: [r.year for r in records],
            Col.RAW_ORBIT: [r.orbit for r in records],
            Col.PAYLOAD: [r.payload for r in records],
            Col.REPORTED_MASS: pd.array(
                [r.payload_mass for r in records], dtype="Int64"
            ),
            Col.MASS: [
                (r.payload_mass or 0) if launch_succeeded(r.outcome) else 0
                for r in records
            ],
            Col.DATETIME: pd.to_datetime([r.launch_datetime for r in records]),
            Col.VEHICLE: [r.vehicle for r in records],
            Col.OUTCOME: [r.outcome for r in records],
        }
    )
    df[Col.ORBIT] = [categorize_starlink(r.payload, r.orbit) for r in records]
    return df


def chart_caption(df: pd.DataFrame) -> str:
    """The note under each chart: its source, how current it is, and the
    launches whose unknown mass counts as zero.

    Built only from the data (not the clock), so the charts change only when
    the launches do.
    """
    source = "Data: Wikipedia contributors, CC BY-SA 4.0"
    if df.empty:
        return f"{source}. No launches available."
    latest = df[Col.DATETIME].max()
    unknown = int(
        (df[Col.REPORTED_MASS].isna() & df[Col.OUTCOME].map(launch_succeeded)).sum()
    )
    launches = "launch" if unknown == 1 else "launches"
    count = "counts" if unknown == 1 else "count"
    return (
        f"{source}, launches through "
        f"{latest.day} {latest:%B %Y}. {unknown} successful {launches} with unknown or "
        f"classified payload mass {count} as 0 kg."
    )


def payload_mass_by_year_orbit(df: pd.DataFrame) -> pd.DataFrame:
    """Sums payload mass grouped by year and orbit category."""
    return df.groupby([Col.YEAR, Col.ORBIT])[Col.MASS].sum().reset_index()


def _period_end(year: int, today: datetime.date) -> datetime.datetime:
    """The end of the last day plotted: today for the current year."""
    last_day = today if year == today.year else datetime.date(year, 12, 31)
    return datetime.datetime.combine(last_day, datetime.time(23, 59, 59))


def build_cumulative_frame(df: pd.DataFrame, today: datetime.date) -> pd.DataFrame:
    """Builds the per-year cumulative payload mass series for plotting.

    Each year from MIN_CUMULATIVE_YEAR onwards gets a zero-mass point on
    January 1st, so its line starts at the origin, and a point at the end of
    its period (December 31st, or `today` for the current year), so its line
    extends to there. Returns one row per point, with "DayOfYear" and
    "CumulativePayloadMass" ready to plot.
    """
    df = df[df[Col.YEAR] >= MIN_CUMULATIVE_YEAR]
    years = df[Col.YEAR].unique()
    starts = pd.DataFrame(
        {
            Col.YEAR: years,
            Col.MASS: 0,
            Col.DATETIME: [datetime.datetime(y, 1, 1) for y in years],
        }
    )
    ends = pd.DataFrame(
        {
            Col.YEAR: years,
            Col.MASS: 0,
            Col.DATETIME: [_period_end(y, today) for y in years],
        }
    )

    points = pd.concat(
        [starts, df[[Col.YEAR, Col.MASS, Col.DATETIME]], ends],
        ignore_index=True,
    )
    points[Col.DATETIME] = pd.to_datetime(points[Col.DATETIME])
    # Keep boundaries on the correct side of any launches at the exact time.
    points = points.sort_values([Col.YEAR, Col.DATETIME], kind="stable")
    points[Col.CUMULATIVE_MASS] = points.groupby(Col.YEAR)[Col.MASS].cumsum()
    points[Col.DAY_OF_YEAR] = points[Col.DATETIME].dt.day_of_year
    return points.reset_index(drop=True)
