"""Builds the matplotlib figures.

Figures are built with matplotlib's object-oriented API only: each Figure gets
its own Agg canvas and is never registered with pyplot, so building one starts
no GUI backend and leaves nothing to close afterwards.
"""

import datetime
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from types import MappingProxyType
from typing import Final, Literal

import numpy as np
from matplotlib import style
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.path import Path
from matplotlib.text import Annotation
from matplotlib.ticker import FuncFormatter, MaxNLocator

from spacex_graphs.config import (
    BLT,
    GTO_GEO,
    HELIOCENTRIC,
    HIGHLIGHT_FROM_YEAR,
    LEO_OTHER,
    LEO_STARLINK,
    MEO,
    OTHER_ORBIT,
    SSO_OTHER,
    SSO_STARLINK,
    TRANSATMOSPHERIC,
    OrbitCategory,
)
from spacex_graphs.transform import (
    DAYS_IN_LEAP_YEAR,
    LEAP_REFERENCE_YEAR,
    Col,
    CumulativeFrame,
    YearOrbitFrame,
    calendar_day,
)

# Each orbit category's color, keyed by name so that reordering
# config.ORBIT_CATEGORIES can never hand a category another's color. Listed in
# that legend order, which the tests check. Every color has at least 3:1
# contrast against the white background, and every pair stays clearly apart
# (CIE76 ΔE ≥ 17.9) under normal vision and simulated protanopia, deuteranopia,
# and tritanopia; neighbors in the stack are further apart still (ΔE ≥ 32).
# The two Starlink categories share a blue family; "Other" is neutral grey.
ORBIT_COLORS: Final[Mapping[OrbitCategory, str]] = MappingProxyType(
    {
        LEO_STARLINK: "#5a87f0",  # cornflower blue
        LEO_OTHER: "#d278a5",  # pink
        SSO_STARLINK: "#5a5ab4",  # indigo
        SSO_OTHER: "#a5961e",  # olive gold
        MEO: "#69965a",  # sage green
        GTO_GEO: "#784b87",  # plum
        BLT: "#2d693c",  # forest green
        HELIOCENTRIC: "#a587d2",  # lavender
        TRANSATMOSPHERIC: "#964b00",  # brown
        OTHER_ORBIT: "#6e6e6e",  # grey
    }
)

# Most recent years get the first colors. Every color has at least 3:1
# contrast against white and against both dark backgrounds (the violet
# through its dark-mode shade). Under normal vision and simulated protanopia,
# deuteranopia, and tritanopia, every pair stays apart (CIE76 ΔE ≥ 11.9) and
# neighboring slots far apart (ΔE ≥ 42 in the light theme, ≥ 37 in the dark).
# Years before HIGHLIGHT_FROM_YEAR, and any beyond the eight most recent, fold
# into one muted context group rather than reusing or inventing hues.
YEAR_COLORS: Final[tuple[str, ...]] = (
    "#e34948",  # red: the current year
    "#2a78d6",  # blue
    "#d56d0b",  # orange
    "#0d7767",  # teal
    "#7a6600",  # olive
    "#cc3374",  # magenta
    "#00a308",  # green
    "#4a3aa7",  # violet
)
OLDER_YEARS_COLOR: Final = "#898781"

# Secondary text (captions, bar totals): 7:1 against white, passing WCAG AAA
SECONDARY_TEXT_COLOR: Final = "#595959"

# The light theme's neutrals, which are matplotlib's defaults. They are pinned
# in CHART_STYLE because output's dark-mode stylesheet finds the elements to
# recolor by these exact values.
BACKGROUND_COLOR: Final = "#ffffff"
TEXT_COLOR: Final = "#000000"
GRID_COLOR: Final = "#b0b0b0"
LEGEND_EDGE_COLOR: Final = "#cccccc"
# Thin edges between stacked bar segments, in the background color
SEGMENT_EDGE_COLOR: Final = BACKGROUND_COLOR

# The dark theme, shown when the viewer prefers a dark color scheme: GitHub's
# dark canvas, with text that keeps at least 7:1 (and secondary text 4.5:1)
DARK_BACKGROUND_COLOR: Final = "#0d1117"
DARK_LEGEND_COLOR: Final = "#161b22"
DARK_TEXT_COLOR: Final = "#e6edf3"
DARK_SECONDARY_TEXT_COLOR: Final = "#9ca3af"
DARK_GRID_COLOR: Final = "#30363d"

# Data colors with less than 3:1 contrast against the dark background or the
# dark legend, and the lighter shades that replace them there. The dark
# palettes keep the same separation under simulated color vision deficiencies
# as the light ones, which the tests check.
DARK_MODE_DATA_COLORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "#5a5ab4": "#5e5eb6",  # SSO (Starlink) indigo, a shade lighter
        "#784b87": "#81588e",  # GTO/GEO plum, a shade lighter
        "#2d693c": "#38c75c",  # BLT forest green -> bright green
        "#964b00": "#a55300",  # Transatmospheric brown, a shade lighter
        "#4a3aa7": "#6752e0",  # the eighth year's violet, lighter
    }
)

# Fixed IDs for the backgrounds that output's dark-mode stylesheet recolors,
# so it doesn't depend on the order matplotlib numbers its SVG groups in
FIGURE_BACKGROUND_ID: Final = "sg-fig-bg"
AXES_BACKGROUND_ID: Final = "sg-axes-bg"
LEGEND_BACKGROUND_ID: Final = "sg-legend-bg"

# Pinned so that a developer's own matplotlibrc can't change the renders, both
# while a figure is built and (in output) while it is saved. DejaVu Sans ships
# with matplotlib, so every machine has it.
CHART_STYLE: Final[Mapping[str, object]] = MappingProxyType(
    {
        "font.family": ["DejaVu Sans"],
        "figure.facecolor": BACKGROUND_COLOR,
        "axes.facecolor": BACKGROUND_COLOR,
        "text.color": TEXT_COLOR,
        "axes.labelcolor": TEXT_COLOR,
        "axes.edgecolor": TEXT_COLOR,
        "xtick.color": TEXT_COLOR,
        "ytick.color": TEXT_COLOR,
        "grid.color": GRID_COLOR,
        "legend.edgecolor": LEGEND_EDGE_COLOR,
    }
)

# Bar totals sit this far above the tallest bar's top, as a fraction of it
_BAR_HEADROOM = 0.08
# Each bar's width, as a fraction of the distance between neighboring bars
_BAR_WIDTH = 0.5

# The current year's cumulative line stands out from the others
_LINE_WIDTH = 1.5
_CURRENT_YEAR_LINE_WIDTH = 2.2
_OLDER_YEARS_LINE_WIDTH = 1.0

# Days of padding either side of the cumulative chart's year
_DAY_PADDING = 6

# Direct year labels in the cumulative chart's right margin: their font size,
# how far right of the axes they sit, and the least distance between the
# centers of two labels, all in points
_END_LABEL_FONT_SIZE = 8
_END_LABEL_OFFSET = 10
_END_LABEL_SPACING = _END_LABEL_FONT_SIZE * 1.3

# Until this day on the shared calendar (early November), the current year's
# line ends well short of the right edge, so its label sits beside its dot
# rather than out in the margin, where it would float far from its line
MARGIN_LABEL_FROM_DAY: Final = 310
# Where that label may sit, in points from the dot: right of it first, above
# then below, then left of it, whichever first clears the other lines and the
# legend
_DOT_LABEL_OFFSETS: Final = ((5, 4), (5, -4), (-5, 4), (-5, -4))


@contextmanager
def chart_style() -> Iterator[None]:
    """Applies matplotlib's defaults plus CHART_STYLE."""
    with style.context(["default", dict(CHART_STYLE)]):
        yield


def create_figure(
    title: str,
    ylabel: str,
    *,
    xlabel: str = "",
    size: tuple[float, float] = (10, 7),
    grid_axis: Literal["both", "x", "y"] = "both",
) -> tuple[Figure, Axes]:
    """Creates a figure with the given title and axis labels, with whole-number,
    thousands-separated y ticks and gridlines drawn behind the data.

    The figure has its own Agg canvas and is not managed by pyplot.
    """
    fig = Figure(figsize=size)
    FigureCanvasAgg(fig)
    fig.patch.set_gid(FIGURE_BACKGROUND_ID)
    ax = fig.add_subplot()
    ax.patch.set_gid(AXES_BACKGROUND_ID)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis=grid_axis)
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


def _add_legend(
    ax: Axes, handles: Sequence[Artist], labels: Sequence[str], *, title: str
) -> None:
    """Adds the legend top left, with a fixed ID on its background."""
    legend = ax.legend(handles, labels, title=title, loc="upper left")
    legend.get_frame().set_gid(LEGEND_BACKGROUND_ID)


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
    payload_mass_by_year_orbit: YearOrbitFrame,
    *,
    current_year: int | None = None,
    caption: str = "",
) -> Figure:
    """Plots launched payload mass by year and destination as a stacked bar chart.

    Includes suborbital (Transatmospheric) payloads, which is why the title
    says "launched" rather than "to orbit". The current_year's bar is
    labelled "YTD", so a partial year doesn't read as a decline.
    """
    with chart_style():
        return _plot_by_year(
            payload_mass_by_year_orbit, current_year=current_year, caption=caption
        )


def _plot_by_year(
    payload_mass_by_year_orbit: YearOrbitFrame,
    *,
    current_year: int | None,
    caption: str,
) -> Figure:
    # Horizontal gridlines only, behind the bars, to help read their heights;
    # vertical ones would run through the bars
    fig, ax = create_figure(
        "SpaceX Payload Mass Launched by Year and Destination",
        "Payload Mass (kg)",
        grid_axis="y",
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

    # Stack the categories in legend order: each segment starts where the
    # categories before it end
    positions = range(len(pivot_df.index))
    bottoms = pivot_df.cumsum(axis=1) - pivot_df
    for category in ordered_columns:
        ax.bar(
            positions,
            pivot_df[category],
            width=_BAR_WIDTH,
            bottom=bottoms[category],
            color=ORBIT_COLORS[category],
            # Thin edges keep neighboring segments cleanly apart
            edgecolor=SEGMENT_EDGE_COLOR,
            linewidth=0.35,
            label=category,
        )
    ax.set_xlim(-0.5, len(pivot_df.index) - 0.5)

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
    # Room above the tallest bar for its total; with nothing but zeros (only
    # failures or unknown masses), a unit range keeps the axis starting at 0
    top = float(totals.max()) * (1 + _BAR_HEADROOM)
    ax.set_ylim(0, top if top > 0 else 1)

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
    # List categories top to bottom in the order they're stacked on the bars
    handles, labels = ax.get_legend_handles_labels()
    _add_legend(ax, handles[::-1], labels[::-1], title="Destination")
    _finish(fig, caption)
    return fig


def plot_cumulative_payload_mass_to_orbit(
    cumulative: CumulativeFrame, today: datetime.date, *, caption: str = ""
) -> Figure:
    """Plots cumulative launched payload mass by year as line charts.

    Expects the frame from transform.build_cumulative_frame, whose days are on
    one shared leap-year calendar, so every year's lines and the month ticks
    line up date for date. The current year's line is drawn thicker, with a
    dot where it ends today, and each highlighted year is labelled at its
    line's end in the right margin, except the current year's while it is
    still early in the year (before MARGIN_LABEL_FROM_DAY), which sits
    beside its dot instead.
    """
    with chart_style():
        return _plot_cumulative(cumulative, today, caption=caption)


def _plot_cumulative(
    cumulative: CumulativeFrame, today: datetime.date, *, caption: str
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

    # Each highlighted year's label, final total, and color
    line_ends: list[tuple[str, float, str]] = []
    # Where the current year's line ends: today's day and total so far
    dot: tuple[float, float] | None = None
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
        if year in year_color_map:
            line_ends.append((label, points[Col.CUMULATIVE_MASS].iloc[-1], color))
        if year == today.year:
            # Mark where this year's line ends: today's total so far
            dot = (
                float(points[Col.DAY_OF_YEAR].iloc[-1]),
                float(points[Col.CUMULATIVE_MASS].iloc[-1]),
            )
            ax.scatter(
                *dot,
                s=30,
                color=color,
                zorder=3,
                label="_nolegend_",
            )

    if sorted_years:
        # Newest year first, matching the lines' order from top to bottom
        handles, labels = ax.get_legend_handles_labels()
        _add_legend(ax, handles[::-1], labels[::-1], title="Year")
    else:
        _show_no_data(ax)

    # Tick the first of every other month on the shared leap-year calendar the
    # lines use, so a tick marks the same date in every year
    months_to_label = [
        datetime.date(LEAP_REFERENCE_YEAR, month, 1) for month in range(1, 13, 2)
    ]
    ax.set_xticks(
        [calendar_day(date) for date in months_to_label],
        [date.strftime("%b 1") for date in months_to_label],
    )

    # Span the whole year, with equal padding either side
    ax.set_xlim(1 - _DAY_PADDING, DAYS_IN_LEAP_YEAR + _DAY_PADDING)

    # Newest first, so the current year's label is the first text either way
    dot_label = None
    if dot is not None and dot[0] < MARGIN_LABEL_FROM_DAY:
        dot_label = _label_dot(ax, str(today.year), dot)
        line_ends = [end for end in line_ends if end[0] != dot_label.get_text()]
    labels = _label_line_ends(ax, sorted(line_ends, reverse=True))
    # Lay out first: the labels' spacing depends on the axes' final height
    _finish(fig, caption)
    _spread_labels(fig, ax, labels)
    if dot_label is not None:
        _place_beside_dot(ax, dot_label)
    return fig


def _label_dot(ax: Axes, label: str, dot: tuple[float, float]) -> Annotation:
    """Labels the current year's line beside the dot where it ends today."""
    dx, dy = _DOT_LABEL_OFFSETS[0]
    return ax.annotate(
        label,
        xy=dot,
        xytext=(dx, dy),
        textcoords="offset points",
        ha="left",
        va="bottom",
        fontsize=_END_LABEL_FONT_SIZE,
        fontweight="bold",
    )


def _drawn_path(line: Line2D) -> Path:
    """A steps-post line as drawn, in display coordinates."""
    xs, ys = (np.asarray(values, dtype=float) for values in line.get_data())
    # Each point, then a corner at the next point's x and this point's y
    corners = np.column_stack((np.repeat(xs, 2)[1:], np.repeat(ys, 2)[:-1]))
    return Path(line.get_transform().transform(corners))


def _place_beside_dot(ax: Axes, label: Annotation) -> None:
    """Moves the dot's label to the first of _DOT_LABEL_OFFSETS that keeps it
    inside the axes and clear of every line and the legend, or leaves it at
    the first if none does."""
    # Applies any pending autoscaling, so transData maps to the final limits
    ax.get_ylim()
    lines = [_drawn_path(line) for line in ax.lines]
    legend = ax.get_legend()
    obstacles = [legend.get_window_extent()] if legend is not None else []
    for dx, dy in (*_DOT_LABEL_OFFSETS, _DOT_LABEL_OFFSETS[0]):
        label.xyann = (dx, dy)
        label.set_horizontalalignment("left" if dx > 0 else "right")
        label.set_verticalalignment("bottom" if dy > 0 else "top")
        box = label.get_window_extent()
        if (
            ax.bbox.contains(box.x0, box.y0)
            and ax.bbox.contains(box.x1, box.y1)
            and not any(box.overlaps(other) for other in obstacles)
            and not any(path.intersects_bbox(box) for path in lines)
        ):
            return


def _label_line_ends(
    ax: Axes, line_ends: Sequence[tuple[str, float, str]]
) -> list[Annotation]:
    """Labels each line in the right margin, level with its final total.

    A short leader in the line's color joins the label to the axes, so the
    label still points at its line once _spread_labels nudges it.
    """
    return [
        ax.annotate(
            label,
            xy=(1, total),
            # x in axes coordinates (the right edge), y in data
            xycoords=ax.get_yaxis_transform(),
            xytext=(_END_LABEL_OFFSET, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=_END_LABEL_FONT_SIZE,
            arrowprops={
                "arrowstyle": "-",
                "color": color,
                "linewidth": 1.2,
                "shrinkA": 2,
                "shrinkB": 0,
                # The leader starts at the label's left edge, not under it
                "relpos": (0, 0.5),
            },
            annotation_clip=False,
        )
        for label, total, color in line_ends
    ]


def _spread_labels(fig: Figure, ax: Axes, labels: Sequence[Annotation]) -> None:
    """Nudges the direct labels apart vertically so that none overlap, while
    keeping every label within the axes' height.

    labels are newest first, and of two lines ending level, the newer
    year's label goes above the older's.
    """
    if not labels:
        return
    # Applies any pending autoscaling, so transData maps to the final limits
    ax.get_ylim()
    points_per_pixel = 72 / fig.dpi
    bottom = ax.bbox.y0
    height = ax.bbox.height * points_per_pixel
    wanted = [
        (ax.transData.transform((0, label.xy[1]))[1] - bottom) * points_per_pixel
        for label in labels
    ]
    # Bottom to top; on a tie, the older (later in labels) goes below
    order = sorted(range(len(labels)), key=lambda i: (wanted[i], -i))
    placed = [wanted[i] for i in order]
    half = _END_LABEL_SPACING / 2
    # Push labels up from the bottom so each clears the one below it, then
    # down from the top so none ends up above the axes
    placed[0] = max(placed[0], half)
    for k in range(1, len(placed)):
        placed[k] = max(placed[k], placed[k - 1] + _END_LABEL_SPACING)
    placed[-1] = min(placed[-1], height - half)
    for k in range(len(placed) - 2, -1, -1):
        placed[k] = min(placed[k], placed[k + 1] - _END_LABEL_SPACING)
    for k, i in enumerate(order):
        labels[i].xyann = (_END_LABEL_OFFSET, placed[k] - wanted[i])
