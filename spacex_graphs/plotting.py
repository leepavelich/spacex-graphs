"""Builds the matplotlib figures."""

import calendar
import datetime

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from spacex_graphs.transform import add_end_of_period_entries

# Colors for each orbit category, in legend order
ORBIT_COLORS = {
    "LEO (Starlink)": "chocolate",
    "LEO (Other)": "coral",
    "SSO (Starlink)": "darkgoldenrod",
    "SSO (Other)": "orange",
    "MEO": "orchid",
    "GTO/GEO": "yellowgreen",
    "BLT": "gold",
    "Heliocentric": "wheat",
    "Transatmospheric": "lightblue",
    "Other": "lightgray",
}

# Most recent years get the first colors
YEAR_COLORS = [
    "red",
    "green",
    "blue",
    "orange",
    "purple",
    "pink",
    "lightblue",
    "lightgreen",
]


def create_figure(title, xlabel, ylabel, size=(10, 7)):
    """Creates a figure with the given title, x label, and y label"""
    fig, ax = plt.subplots(figsize=size)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True)
    ax.tick_params(axis="x", rotation=45)
    ax.ticklabel_format(style="plain", axis="y")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
    return fig, ax


def plot_payload_mass_to_orbit_by_year(payload_mass_by_year_orbit):
    """Plots the payload mass to orbit by year as a stacked bar chart."""
    fig, ax = create_figure(
        "Payload Mass to Type of Orbit by Year", "Year", "Payload Mass (kg)"
    )
    ordered_columns = list(ORBIT_COLORS)
    pivot_df = payload_mass_by_year_orbit.pivot(
        index="Year", columns="Orbit", values="PayloadMass"
    ).fillna(0)[ordered_columns]

    pivot_df.plot(
        kind="bar",
        stacked=True,
        color=[ORBIT_COLORS[col] for col in ordered_columns],
        ax=ax,
    )

    # A fixed amount of padding above the bars for the annotations
    fixed_padding = 10000

    # Annotate each bar with the total payload mass for the year
    for i, total in enumerate(pivot_df.sum(axis=1)):
        ax.text(
            i,
            total + fixed_padding,
            f"{int(total):,}",
            ha="center",
            va="bottom",
            color="grey",
            fontsize=8,
        )

    ax.legend(title="Orbit Type")
    ax.set_xlabel("")
    fig.tight_layout()
    return fig


def plot_cumulative_payload_mass_to_orbit(df_filtered):
    """Plots the cumulative payload mass to orbit by year as line charts."""
    fig, ax = create_figure(
        "Cumulative Payload Mass to Orbit By Year",
        "",
        "Cumulative Payload Mass (kg)",
    )
    df_extended = add_end_of_period_entries(df_filtered)

    sorted_years = sorted(df_extended["Year"].unique(), reverse=True)
    year_color_map = dict(zip(sorted_years, YEAR_COLORS))

    for year, group_data in df_extended.groupby("Year"):
        group_data = group_data.sort_values("DateTime")
        group_data["DayOfYear"] = group_data["DateTime"].dt.dayofyear
        cumulative_mass = group_data["PayloadMass"].cumsum()

        ax.plot(
            group_data["DayOfYear"],
            cumulative_mass,
            label=str(year),
            color=year_color_map.get(year, "grey"),
            drawstyle="steps-post",
        )

    ax.legend(title="Year", loc="upper left")

    # Set the x-axis ticks to the first of every other month
    months_to_label = [datetime.datetime(2020, month, 1) for month in range(1, 13, 2)]
    ax.set_xticks([date.timetuple().tm_yday for date in months_to_label])
    ax.set_xticklabels([date.strftime("%b 1") for date in months_to_label], rotation=0)

    # Set the x-axis limit to the maximum day of the year
    current_year = datetime.datetime.now().year
    days_in_year = 366 if calendar.isleap(current_year) else 365
    ax.set_xlim(-14, days_in_year + 7)

    fig.tight_layout()
    return fig
