"""Transforms parsed launch records into the DataFrames the plots consume."""

import datetime
import re

import pandas as pd

from spacex_graphs.config import MIN_CUMULATIVE_YEAR, ORBIT_MAPPING


def clean_orbit_category(orbit):
    """Cleans the orbit category by removing square brackets and mapping to a category"""
    orbit_cleaned = re.sub(r"\[.*?\]", "", orbit).strip()
    return ORBIT_MAPPING.get(orbit_cleaned, "Other")


def categorize_starlink(payload, orbit):
    """Categorizes the orbit as Starlink if the payload contains 'Starlink'"""
    if "Starlink" in payload:
        return f"{orbit} (Starlink)"
    return orbit


def build_dataframe(records):
    """Builds the launch DataFrame with standardized orbit categories."""
    df = pd.DataFrame(
        records,
        columns=["Year", "Orbit", "Payload", "PayloadMass", "DateTime", "Vehicle"],
    )
    df["Orbit"] = df.apply(
        lambda x: categorize_starlink(x["Payload"], x["Orbit"]), axis=1
    )
    df["Orbit"] = df["Orbit"].apply(clean_orbit_category)
    return df


def payload_mass_by_year_orbit(df):
    """Sums payload mass grouped by year and orbit category."""
    return df.drop(columns="DateTime").groupby(["Year", "Orbit"]).sum().reset_index()


def build_cumulative_frame(df):
    """Prepares the per-year cumulative payload mass frame for plotting.

    Adds a zero-mass entry at January 1st of each year so every year's line
    starts at the origin, and filters to MIN_CUMULATIVE_YEAR onwards.
    """
    df = df.sort_values(by="DateTime")
    df["CumulativePayloadMass"] = df.groupby("Year")["PayloadMass"].transform(
        pd.Series.cumsum
    )

    initial_entries = []
    for year in df["Year"].unique():
        if year >= MIN_CUMULATIVE_YEAR:
            initial_entries.append(
                {
                    "Year": year,
                    "Orbit": "",
                    "Payload": "",
                    "PayloadMass": 0,
                    "DateTime": datetime.datetime(year, 1, 1),
                    "Vehicle": "",
                    "CumulativePayloadMass": 0,
                }
            )

    df = pd.concat([pd.DataFrame(initial_entries), df], ignore_index=True)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["DayOfYear"] = df["DateTime"].dt.dayofyear
    return df[df["Year"] >= MIN_CUMULATIVE_YEAR]


def add_end_of_period_entries(df):
    """Adds an entry at the end of each year's period with the last known
    cumulative payload mass (end of year, or today for the current year)."""
    now = datetime.datetime.now()
    end_of_period_entries = []

    for year in df["Year"].unique():
        last_entry_for_year = df[df["Year"] == year].iloc[-1]
        last_cumulative_mass = last_entry_for_year["CumulativePayloadMass"]

        if year == now.year:
            period_end_date = datetime.datetime(year, 1, 1) + datetime.timedelta(
                days=now.timetuple().tm_yday - 1
            )
        else:
            period_end_date = datetime.datetime(year, 12, 31)

        end_of_period_entries.append(
            {
                "Year": year,
                "PayloadMass": 0,  # No additional payload, so mass is 0
                "DateTime": period_end_date,
                "CumulativePayloadMass": last_cumulative_mass,
                "DayOfYear": period_end_date.timetuple().tm_yday,
            }
        )

    return pd.concat(
        [df, pd.DataFrame(end_of_period_entries)], ignore_index=True
    ).sort_values(by="DateTime")
