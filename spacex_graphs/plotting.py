"""Builds the matplotlib figures."""

import calendar
import datetime

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from spacex_graphs.config import HIGHLIGHT_FROM_YEAR
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

# Most recent years get the first colors. This eight-hue order is validated
# for colorblind-safe separation between adjacent slots. Years before
# HIGHLIGHT_FROM_YEAR, and any beyond the eight most recent, fold into one
# muted context group rather than reusing or inventing hues.
YEAR_COLORS = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]
OLDER_YEARS_COLOR = "#898781"


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
    """Plots launched payload mass by year and destination as a stacked bar chart.

    Includes suborbital (Transatmospheric) payloads, which is why the title
    says "launched" rather than "to orbit".
    """
    fig, ax = create_figure(
        "Payload Mass Launched by Year and Destination", "Year", "Payload Mass (kg)"
    )
    ordered_columns = list(ORBIT_COLORS)
    # reindex (not [ordered_columns]) so a category with no launches yet is
    # plotted as zero instead of raising KeyError
    pivot_df = payload_mass_by_year_orbit.pivot(
        index="Year", columns="Orbit", values="PayloadMass"
    ).reindex(columns=ordered_columns, fill_value=0).fillna(0)

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

    ax.legend(title="Destination")
    ax.set_xlabel("")
    fig.tight_layout()
    return fig


def plot_cumulative_payload_mass_to_orbit(df_filtered):
    """Plots cumulative launched payload mass by year as line charts."""
    fig, ax = create_figure(
        "Cumulative Payload Mass Launched by Year",
        "",
        "Cumulative Payload Mass (kg)",
    )
    df_extended = add_end_of_period_entries(df_filtered)

    sorted_years = sorted(df_extended["Year"].unique(), reverse=True)
    highlighted_years = [y for y in sorted_years if y >= HIGHLIGHT_FROM_YEAR]
    year_color_map = dict(zip(highlighted_years, YEAR_COLORS))
    older_years = [y for y in sorted_years if y not in year_color_map]
    if len(older_years) == 1:
        older_label = str(older_years[0])
    elif older_years:
        older_label = f"{min(older_years)}–{max(older_years)}"

    for year, group_data in df_extended.groupby("Year"):
        group_data = group_data.sort_values("DateTime")
        group_data["DayOfYear"] = group_data["DateTime"].dt.dayofyear
        cumulative_mass = group_data["PayloadMass"].cumsum()

        if year in year_color_map:
            style = {"label": str(year), "color": year_color_map[year]}
        else:
            # Only the newest of the older years carries the shared legend entry
            label = older_label if year == older_years[0] else "_nolegend_"
            style = {"label": label, "color": OLDER_YEARS_COLOR, "linewidth": 1}

        ax.plot(
            group_data["DayOfYear"],
            cumulative_mass,
            drawstyle="steps-post",
            **style,
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
