"""Builds the matplotlib figures."""

import calendar
import datetime
from collections.abc import Iterator
from contextlib import contextmanager
from types import MappingProxyType

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator

from spacex_graphs.config import HIGHLIGHT_FROM_YEAR
from spacex_graphs.transform import Col

# Each orbit category's color, keyed by name so that reordering
# config.ORBIT_CATEGORIES can never hand a category another's color. Listed in
# that legend order, which the tests check. Every color has at least 3:1
# contrast against the white background, and every pair stays clearly apart
# (CIE76 ΔE ≥ 18) under normal vision and simulated protanopia, deuteranopia,
# and tritanopia; neighbors in the stack are further apart still (ΔE ≥ 32).
# The two Starlink categories share a blue family; "Other" is neutral grey.
ORBIT_COLORS: MappingProxyType[str, str] = MappingProxyType(
    {
        "LEO (Starlink)": "#5a87f0",  # cornflower blue
        "LEO (Other)": "#d278a5",  # pink
        "SSO (Starlink)": "#5a5ab4",  # indigo
        "SSO (Other)": "#a5961e",  # olive gold
        "MEO": "#69965a",  # sage green
        "GTO/GEO": "#784b87",  # plum
        "BLT": "#2d693c",  # forest green
        "Heliocentric": "#a587d2",  # lavender
        "Transatmospheric": "#964b00",  # brown
        "Other": "#6e6e6e",  # grey
    }
)

# Most recent years get the first colors. This eight-hue order is validated
# for colorblind-safe separation between adjacent slots. Years before
# HIGHLIGHT_FROM_YEAR, and any beyond the eight most recent, fold into one
# muted context group rather than reusing or inventing hues.
YEAR_COLORS = (
    "#e34948",  # red: the current year
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
)
OLDER_YEARS_COLOR = "#898781"

# Secondary text (captions, bar totals): 7:1 against white, passing WCAG AAA
SECONDARY_TEXT_COLOR = "#595959"

# Pinned so that a developer's own matplotlibrc can't change the renders.
# DejaVu Sans ships with matplotlib, so every machine has it.
_CHART_STYLE = {
    "font.family": ["DejaVu Sans"],
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}

# Bar totals sit this far above the tallest bar's top, as a fraction of it
_BAR_HEADROOM = 0.08

# The current year's cumulative line stands out from the others
_LINE_WIDTH = 1.5
_CURRENT_YEAR_LINE_WIDTH = 2.2
_OLDER_YEARS_LINE_WIDTH = 1.0

# Days of padding either side of the cumulative chart's year
_DAY_PADDING = 6


@contextmanager
def _chart_style() -> Iterator[None]:
    """Applies matplotlib's defaults plus _CHART_STYLE while a figure is built."""
    with plt.style.context(["default", _CHART_STYLE]):
        yield


def create_figure(
    title: str, ylabel: str, *, xlabel: str = "", size: tuple[float, float] = (10, 7)
) -> tuple[Figure, Axes]:
    """Creates a figure with the given title and axis labels, with whole-number,
    thousands-separated y ticks and gridlines drawn behind the data."""
    fig, ax = plt.subplots(figsize=size)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True)
    ax.set_axisbelow(True)
    # Whole-number ticks only, so a tiny range can't repeat "0" down the axis
    ax.yaxis.set_major_locator(
        MaxNLocator(nbins="auto", steps=[1, 2, 2.5, 5, 10], integer=True)
    )
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}"))
    return fig, ax


def _finish(fig: Figure, caption: str) -> None:
    """Adds the caption, if any, under the chart and lays the figure out."""
    if caption:
        fig.text(
            0.01,
            0.01,
            caption,
            fontsize=7,
            color=SECONDARY_TEXT_COLOR,
            ha="left",
            va="bottom",
        )
        fig.tight_layout(rect=(0, 0.03, 1, 1))
    else:
        fig.tight_layout()


def _show_no_data(ax: Axes) -> None:
    ax.text(
        0.5,
        0.5,
        "No launches to show",
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=SECONDARY_TEXT_COLOR,
    )


def _format_bar_total(total: float) -> str:
    """Formats a bar's total mass in kg compactly, e.g. "950", "5.8k", "91k",
    "2.19M", so that it stays narrower than a bar however large it gets.

    Each band's upper limit is where rounding would carry into the next, so
    999,600 is "1.00M" rather than "1000k".
    """
    if total < 999.5:
        return f"{total:.0f}"
    if total < 9_950:
        return f"{total / 1e3:.1f}k"
    if total < 999_500:
        return f"{total / 1e3:.0f}k"
    if total < 9_995_000:
        return f"{total / 1e6:.2f}M"
    if total < 99_950_000:
        return f"{total / 1e6:.1f}M"
    return f"{total / 1e6:.0f}M"


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
    with _chart_style():
        return _plot_by_year(
            payload_mass_by_year_orbit, current_year=current_year, caption=caption
        )


def _plot_by_year(
    payload_mass_by_year_orbit: pd.DataFrame, *, current_year: int | None, caption: str
) -> Figure:
    fig, ax = create_figure(
        "SpaceX Payload Mass Launched by Year and Destination", "Payload Mass (kg)"
    )
    unknown = set(payload_mass_by_year_orbit[Col.ORBIT]) - set(ORBIT_COLORS)
    if unknown:
        # reindex below would silently drop these categories' mass
        raise ValueError(f"orbit categories with no color: {sorted(unknown)}")
    if payload_mass_by_year_orbit.empty:
        _show_no_data(ax)
        _finish(fig, caption)
        return fig

    ordered_columns = list(ORBIT_COLORS)
    # reindex (not [ordered_columns]) so a category with no launches yet is
    # plotted as zero instead of raising KeyError
    pivot_df = (
        payload_mass_by_year_orbit.pivot(
            index=Col.YEAR, columns=Col.ORBIT, values=Col.MASS
        )
        .reindex(columns=ordered_columns, fill_value=0)
        .fillna(0)
    )

    pivot_df.plot(
        kind="bar",
        stacked=True,
        color=[ORBIT_COLORS[col] for col in ordered_columns],
        # Thin white edges keep neighboring segments cleanly apart
        edgecolor="white",
        linewidth=0.35,
        ax=ax,
    )
    # pandas turns the grid off; horizontal lines, behind the bars, help read
    # their heights
    ax.grid(True, axis="y")

    # Label each bar with the year's total, a few points above the bar so the
    # gap looks the same whatever the axis scale
    totals = pivot_df.sum(axis=1)
    for i, total in enumerate(totals):
        ax.annotate(
            _format_bar_total(total),
            xy=(i, total),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=SECONDARY_TEXT_COLOR,
            fontsize=8,
        )
    # Room above the tallest bar for its total
    if totals.max() > 0:
        ax.set_ylim(0, totals.max() * (1 + _BAR_HEADROOM))

    ax.set_xticks(
        range(len(pivot_df.index)),
        [
            f"{year} YTD" if year == current_year else str(year)
            for year in pivot_df.index
        ],
        rotation=45,
        ha="right",
        rotation_mode="anchor",
    )
    # pandas names the x axis after the index; the years speak for themselves
    ax.set_xlabel("")
    # List categories top to bottom in the order they're stacked on the bars
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], title="Destination", loc="upper left")
    _finish(fig, caption)
    return fig


def plot_cumulative_payload_mass_to_orbit(
    cumulative: pd.DataFrame, today: datetime.date, *, caption: str = ""
) -> Figure:
    """Plots cumulative launched payload mass by year as line charts.

    Expects the frame from transform.build_cumulative_frame. The current
    year's line is drawn thicker, with a dot where it ends today.
    """
    with _chart_style():
        return _plot_cumulative(cumulative, today, caption=caption)


def _plot_cumulative(
    cumulative: pd.DataFrame, today: datetime.date, *, caption: str
) -> Figure:
    fig, ax = create_figure(
        "SpaceX Cumulative Payload Mass Launched by Year",
        "Cumulative Payload Mass (kg)",
    )
    sorted_years = sorted(cumulative[Col.YEAR].unique(), reverse=True)
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

    for year, points in cumulative.groupby(Col.YEAR):
        if year in year_color_map:
            label = str(year)
            color = year_color_map[year]
            linewidth = _CURRENT_YEAR_LINE_WIDTH if year == today.year else _LINE_WIDTH
        else:
            # Only the newest of the older years carries the shared legend entry
            label = older_label if year == older_years[0] else "_nolegend_"
            color = OLDER_YEARS_COLOR
            linewidth = _OLDER_YEARS_LINE_WIDTH

        ax.plot(
            points[Col.DAY_OF_YEAR],
            points[Col.CUMULATIVE_MASS],
            drawstyle="steps-post",
            label=label,
            color=color,
            linewidth=linewidth,
        )
        if year == today.year:
            # Mark where this year's line ends: today's total so far
            ax.scatter(
                points[Col.DAY_OF_YEAR].iloc[-1],
                points[Col.CUMULATIVE_MASS].iloc[-1],
                s=30,
                color=color,
                zorder=3,
                label="_nolegend_",
            )

    if sorted_years:
        # Newest year first, matching the lines' order from top to bottom
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles[::-1], labels[::-1], title="Year", loc="upper left")
    else:
        _show_no_data(ax)

    # Tick the first of every other month, positioned for this year's calendar
    # (from March on, a leap year's months start a day later)
    months_to_label = [datetime.date(today.year, month, 1) for month in range(1, 13, 2)]
    ax.set_xticks(
        [date.timetuple().tm_yday for date in months_to_label],
        [date.strftime("%b 1") for date in months_to_label],
    )

    # Span the whole year, with equal padding either side
    days_in_year = 366 if calendar.isleap(today.year) else 365
    ax.set_xlim(1 - _DAY_PADDING, days_in_year + _DAY_PADDING)

    _finish(fig, caption)
    return fig
