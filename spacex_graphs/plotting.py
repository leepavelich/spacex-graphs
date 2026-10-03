"""Builds the matplotlib figures."""

import calendar
import datetime
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from spacex_graphs.config import HIGHLIGHT_FROM_YEAR, ORBIT_CATEGORIES

# Colors for each orbit category, in config.ORBIT_CATEGORIES (legend) order
ORBIT_COLORS = dict(
    zip(
        ORBIT_CATEGORIES,
        [
            "chocolate",
            "coral",
            "darkgoldenrod",
            "orange",
            "orchid",
            "yellowgreen",
            "gold",
            "wheat",
            "lightblue",
            "lightgray",
        ],
        strict=True,
    )
)

# Most recent years get the first colors. This eight-hue order is validated
# for colorblind-safe separation between adjacent slots. Years before
# HIGHLIGHT_FROM_YEAR, and any beyond the eight most recent, fold into one
# muted context group rather than reusing or inventing hues.
YEAR_COLORS = [
    "#e34948",  # red: the current year
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
]
OLDER_YEARS_COLOR = "#898781"


def create_figure(
    title: str, xlabel: str, ylabel: str, size: tuple[float, float] = (10, 7)
) -> tuple[Figure, Axes]:
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


def _finish(fig: Figure, caption: str) -> None:
    """Adds the caption, if any, under the chart and lays the figure out."""
    if caption:
        fig.text(0.01, 0.01, caption, fontsize=7, color="grey", ha="left", va="bottom")
        fig.tight_layout(rect=(0, 0.03, 1, 1))
    else:
        fig.tight_layout()


def plot_payload_mass_to_orbit_by_year(
    payload_mass_by_year_orbit: pd.DataFrame,
    *,
    current_year: int | None = None,
    caption: str = "",
) -> Figure:
    """Plots launched payload mass by year and destination as a stacked bar chart.

    Includes suborbital (Transatmospheric) payloads, which is why the title
    says "launched" rather than "to orbit". The current_year's bar is
    labelled "YTD", so a partial year doesn't read as a decline.
    """
    fig, ax = create_figure(
        "Payload Mass Launched by Year and Destination", "Year", "Payload Mass (kg)"
    )
    unknown = set(payload_mass_by_year_orbit["Orbit"]) - set(ORBIT_COLORS)
    if unknown:
        # reindex below would silently drop these categories' mass
        raise ValueError(f"orbit categories with no color: {sorted(unknown)}")
    ordered_columns = list(ORBIT_COLORS)
    # reindex (not [ordered_columns]) so a category with no launches yet is
    # plotted as zero instead of raising KeyError
    pivot_df = (
        payload_mass_by_year_orbit.pivot(
            index="Year", columns="Orbit", values="PayloadMass"
        )
        .reindex(columns=ordered_columns, fill_value=0)
        .fillna(0)
    )

    pivot_df.plot(
        kind="bar",
        stacked=True,
        color=[ORBIT_COLORS[col] for col in ordered_columns],
        ax=ax,
    )

    # Label each bar with the year's total, a few points above the bar so the
    # gap looks the same whatever the axis scale
    for i, total in enumerate(pivot_df.sum(axis=1)):
        ax.annotate(
            f"{int(total):,}",
            xy=(i, total),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color="grey",
            fontsize=8,
        )

    ax.set_xticklabels(
        [
            f"{year} YTD" if year == current_year else str(year)
            for year in pivot_df.index
        ]
    )
    ax.legend(title="Destination")
    ax.set_xlabel("")
    _finish(fig, caption)
    return fig


def plot_cumulative_payload_mass_to_orbit(
    cumulative: pd.DataFrame, today: datetime.date, *, caption: str = ""
) -> Figure:
    """Plots cumulative launched payload mass by year as line charts.

    Expects the frame from transform.build_cumulative_frame.
    """
    fig, ax = create_figure(
        "Cumulative Payload Mass Launched by Year",
        "",
        "Cumulative Payload Mass (kg)",
    )
    sorted_years = sorted(cumulative["Year"].unique(), reverse=True)
    # Colors follow each year's distance from today, so the current year is
    # always red, even in early January before its first launch (when red is
    # simply unused). Years past the palette, or before HIGHLIGHT_FROM_YEAR,
    # fall through to the grey group.
    year_color_map = {
        year: YEAR_COLORS[today.year - year]
        for year in sorted_years
        if year >= HIGHLIGHT_FROM_YEAR and 0 <= today.year - year < len(YEAR_COLORS)
    }
    older_years = [y for y in sorted_years if y not in year_color_map]
    older_label = (
        f"{min(older_years)}–{max(older_years)}"
        if len(older_years) > 1
        else "".join(map(str, older_years))
    )

    for year, points in cumulative.groupby("Year"):
        if year in year_color_map:
            style: dict[str, Any] = {"label": str(year), "color": year_color_map[year]}
        else:
            # Only the newest of the older years carries the shared legend entry
            label = older_label if year == older_years[0] else "_nolegend_"
            style = {"label": label, "color": OLDER_YEARS_COLOR, "linewidth": 1}

        ax.plot(
            points["DayOfYear"],
            points["CumulativePayloadMass"],
            drawstyle="steps-post",
            **style,
        )

    ax.legend(title="Year", loc="upper left")

    # Set the x-axis ticks to the first of every other month
    months_to_label = [datetime.datetime(2020, month, 1) for month in range(1, 13, 2)]
    ax.set_xticks([date.timetuple().tm_yday for date in months_to_label])
    ax.set_xticklabels([date.strftime("%b 1") for date in months_to_label], rotation=0)

    # Set the x-axis limit to the maximum day of the year
    days_in_year = 366 if calendar.isleap(today.year) else 365
    ax.set_xlim(-14, days_in_year + 7)

    _finish(fig, caption)
    return fig
