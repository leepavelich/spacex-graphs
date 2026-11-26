"""Reads the published baseline and writes launch artifacts and change state."""

import csv
import datetime
import hashlib
import io
import json
import logging
import os
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final
from xml.sax.saxutils import escape

import pandas as pd
from matplotlib import style
from matplotlib.figure import Figure

from spacex_graphs import plotting
from spacex_graphs.cache import atomic_writer
from spacex_graphs.errors import PublishedCsvError
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import Col, LaunchFrame
from spacex_graphs.validation import PublishedLaunch

logger = logging.getLogger(__name__)

# matplotlib otherwise embeds a <dc:date> timestamp and random clip-path/glyph
# IDs, so identical data produced a different SVG (and a noisy commit) every run
_SVG_HASH_SALT: Final = "spacex-graphs"
# Saving reads rcParams too (savefig.*, path.*, svg.*), so it runs under the
# same pinned style as plotting, plus these, never the caller's settings
_SVG_STYLE: Final[Mapping[str, object]] = MappingProxyType(
    {"svg.hashsalt": _SVG_HASH_SALT, "svg.fonttype": "path"}
)


def _dark_mode_rules() -> list[str]:
    """CSS rules that recolor a chart for a dark color scheme.

    matplotlib writes each element's colors as inline styles, so the rules
    find elements by the IDs plotting gives the backgrounds, by matplotlib's
    "text_" group IDs, or by the exact light-theme colors plotting pins, and
    need !important to beat the inline styles. Data colors stay as they are, except the few too dark to see on
    the dark background, which get lighter shades.
    """
    background = plotting.DARK_BACKGROUND_COLOR
    rules = [
        # The figure's and the axes' backgrounds
        f"#{plotting.FIGURE_BACKGROUND_ID} > path, "
        f"#{plotting.AXES_BACKGROUND_ID} > path "
        f"{{ fill: {background} !important }}",
        # The legend's frame
        f"#{plotting.LEGEND_BACKGROUND_ID} > path "
        f"{{ fill: {plotting.DARK_LEGEND_COLOR} !important; "
        f"stroke: {plotting.DARK_GRID_COLOR} !important }}",
        # Text in the default color has no fill of its own, so it inherits this
        f'g[id^="text_"] {{ fill: {plotting.DARK_TEXT_COLOR} }}',
        f'[style*="fill: {plotting.SECONDARY_TEXT_COLOR}"] '
        f"{{ fill: {plotting.DARK_SECONDARY_TEXT_COLOR} !important }}",
        # Spines and tick marks
        f'[style*="stroke: {plotting.TEXT_COLOR}"] '
        f"{{ stroke: {plotting.DARK_SECONDARY_TEXT_COLOR} !important }}",
        f'[style*="stroke: {plotting.GRID_COLOR}"] '
        f"{{ stroke: {plotting.DARK_GRID_COLOR} !important }}",
        # The edges between stacked bar segments match the background
        f'[style*="stroke: {plotting.SEGMENT_EDGE_COLOR}"] '
        f"{{ stroke: {background} !important }}",
    ]
    for light, dark in plotting.DARK_MODE_DATA_COLORS.items():
        rules.append(f'[style*="fill: {light}"] {{ fill: {dark} !important }}')
        rules.append(f'[style*="stroke: {light}"] {{ stroke: {dark} !important }}')
    return rules


def dark_mode_css() -> str:
    """The stylesheet each SVG carries: _dark_mode_rules, applied only when
    the viewer prefers a dark color scheme."""
    rules = "".join(f"  {rule}\n" for rule in _dark_mode_rules())
    return f"@media (prefers-color-scheme: dark) {{\n{rules} }}"


def _figure_title(fig: Figure) -> str:
    if fig.axes:
        return fig.axes[0].get_title()
    return ""


def _accessible_svg(svg: bytes, title: str, description: str) -> bytes:
    """Adds a title, a description, and the dark-mode stylesheet to an SVG.

    Text is drawn as glyph outlines (svg.fonttype "path"), so without the
    <title> and <desc> a screen reader would find no text in the chart.
    """
    start = svg.index(b"<svg ")
    end = svg.index(b">", start)
    labelled_by = "chart-title chart-desc" if description else "chart-title"
    attributes = f' role="img" aria-labelledby="{labelled_by}"'
    elements = f'\n <title id="chart-title">{escape(title)}</title>'
    if description:
        elements += f'\n <desc id="chart-desc">{escape(description)}</desc>'
    elements += f'\n <style type="text/css">\n {dark_mode_css()}\n </style>'
    return svg[:end] + attributes.encode() + b">" + elements.encode() + svg[end + 1 :]


def _save_svg(fig: Figure, path: str, description: str) -> None:
    buffer = io.BytesIO()
    with style.context(["default", dict(plotting.CHART_STYLE), dict(_SVG_STYLE)]):
        fig.savefig(buffer, format="svg", metadata={"Date": None})
    captions = [text.get_text() for text in fig.texts]
    svg = _accessible_svg(
        buffer.getvalue(),
        _figure_title(fig),
        " ".join(part for part in (description, *captions) if part),
    )
    with atomic_writer(path) as f:
        f.write(svg)


BY_YEAR_SVG = "payload_mass_to_orbit_by_year.svg"
CUMULATIVE_SVG = "cumulative_payload_mass_to_orbit.svg"
LAUNCHES_CSV = "spacex_launches.csv"
# The README embeds the SVGs and the scheduled workflow commits these files
# by name, so they must stay stable
OUTPUT_FILES = (BY_YEAR_SVG, CUMULATIVE_SVG, LAUNCHES_CSV)

_CSV_DATE = "Date"
_CSV_VEHICLE = Col.VEHICLE
_CSV_PAYLOAD = Col.PAYLOAD
_CSV_REPORTED_MASS = "Payload Mass (kg)"
_BASELINE_COLUMNS = frozenset(
    {_CSV_DATE, _CSV_VEHICLE, _CSV_PAYLOAD, _CSV_REPORTED_MASS}
)


def missing_outputs(output_dir: str) -> list[str]:
    """Lists the output files that don't exist yet."""
    return [
        name
        for name in OUTPUT_FILES
        if not os.path.exists(os.path.join(output_dir, name))
    ]


def save_plots(
    figures: Mapping[str, Figure],
    *,
    output_dir: str,
    descriptions: Mapping[str, str] | None = None,
) -> None:
    """Saves each figure as an SVG under its file name (a key of figures),
    byte-identical for identical figures.

    Each SVG is titled after its chart, and described by its entry in
    descriptions (if any) followed by its caption, for screen readers. It also
    carries a stylesheet that switches it to dark colors when the viewer
    prefers a dark color scheme.
    """
    descriptions = descriptions or {}
    for filename, figure in figures.items():
        _save_svg(
            figure,
            os.path.join(output_dir, filename),
            descriptions.get(filename, ""),
        )


def published_launches(output_dir: str) -> list[PublishedLaunch]:
    """Reads the launches in the published CSV, or [] if there isn't one.

    The committed CSV is the baseline the next run is checked against. A CSV
    that exists but can't serve as one (malformed, holding no launches, or
    with a negative mass) raises PublishedCsvError rather than silently
    switching the regression checks off.
    """
    csv_path = os.path.join(output_dir, LAUNCHES_CSV)
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, strict=True)
            try:
                fields = reader.fieldnames or []
                if not _BASELINE_COLUMNS.issubset(fields) or len(set(fields)) != len(
                    fields
                ):
                    raise ValueError("missing or repeated column names")
                launches = []
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("incorrect number of fields")
                    launches.append(
                        PublishedLaunch(
                            date=datetime.date.fromisoformat(row[_CSV_DATE]),
                            vehicle=_unescape_formula(row[_CSV_VEHICLE]),
                            payload=_unescape_formula(row[_CSV_PAYLOAD]),
                            mass=_published_mass(row[_CSV_REPORTED_MASS]),
                        )
                    )
                if not launches:
                    raise ValueError("no launches")
            except (csv.Error, KeyError, ValueError) as error:
                raise PublishedCsvError(
                    f"malformed published CSV {csv_path} near line {reader.line_num}: {error}"
                ) from error
    except FileNotFoundError:
        return []
    return launches


def _published_mass(text: str) -> int | None:
    """A published mass in kg, or None if blank (unknown)."""
    if not text:
        return None
    mass = int(text)
    if mass < 0:
        raise ValueError(f"negative mass {mass}")
    return mass


# Spreadsheets treat a cell starting with one of these as a formula
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _escape_formula(text: str) -> str:
    """Stops spreadsheet apps from running Wikipedia text as a formula.

    Payload and orbit text comes from Wikipedia, which anyone can edit, and the
    CSV is published for download, so a cell like "=HYPERLINK(...)" is escaped
    with a leading apostrophe, the standard defense against CSV injection.
    """
    # Escape an existing apostrophe before a formula too, so reading the CSV
    # can distinguish it from an apostrophe we added.
    return f"'{text}" if text.lstrip("'").startswith(_FORMULA_PREFIXES) else text


def _unescape_formula(text: str) -> str:
    if text.startswith("'") and text.lstrip("'").startswith(_FORMULA_PREFIXES):
        return text[1:]
    return text


def save_launches_csv(df: LaunchFrame, *, output_dir: str) -> None:
    """Saves all launches, with raw and categorized orbits, to a CSV file.

    "Payload Mass (kg)" is what Wikipedia reports, blank when unknown or
    classified; "Counted Mass (kg)" is what the graphs sum, which is 0 for
    failed launches and unknown masses.

    Takes the frame from transform.build_dataframe so the CSV's orbit
    categories always match the graphs.
    """
    launches = df.sort_values([Col.DATETIME, Col.VEHICLE, Col.PAYLOAD], kind="stable")
    text = {
        column: launches[column].map(_escape_formula)
        for column in (Col.VEHICLE, Col.PAYLOAD, Col.RAW_ORBIT, Col.OUTCOME)
    }
    csv_df = pd.DataFrame(
        {
            _CSV_DATE: launches[Col.DATETIME].dt.strftime("%Y-%m-%d"),
            "Time (UTC)": launches[Col.DATETIME].dt.strftime("%H:%M:%S"),
            Col.YEAR: launches[Col.YEAR],
            _CSV_VEHICLE: text[Col.VEHICLE],
            _CSV_PAYLOAD: text[Col.PAYLOAD],
            _CSV_REPORTED_MASS: launches[Col.REPORTED_MASS],
            Col.ORBIT: text[Col.RAW_ORBIT],
            "Orbit Category": launches[Col.ORBIT],
            Col.OUTCOME: text[Col.OUTCOME],
            "Counted Mass (kg)": launches[Col.MASS],
        }
    )

    csv_path = os.path.join(output_dir, LAUNCHES_CSV)
    with atomic_writer(csv_path) as f:
        csv_df.to_csv(f, index=False, encoding="utf-8", lineterminator="\n")
    logger.info("Launch data saved to %s", csv_path)


def _hash_file_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, "data_hash.txt")


def compute_data_hash(
    records: Iterable[LaunchRecord], today: datetime.date, code_version: str = ""
) -> str:
    """Hashes the launches, date, and rendering code, regardless of record order."""
    # The current-year line extends to today even when the data is unchanged.
    # Sort serialized records, since a mass of None isn't comparable to an int.
    data = json.dumps(sorted(json.dumps(record, default=str) for record in records))
    combined = f"{today.isoformat()}:{code_version}:{data}"
    return hashlib.sha256(combined.encode()).hexdigest()


def has_data_changed(
    records: Iterable[LaunchRecord],
    today: datetime.date,
    *,
    cache_dir: str,
    code_version: str = "",
) -> bool:
    """Checks for changes since the last successful save without updating the hash."""
    try:
        with open(_hash_file_path(cache_dir), encoding="utf-8") as f:
            old_hash = f.read().strip()
    except FileNotFoundError:
        return True
    return old_hash != compute_data_hash(records, today, code_version)


def save_data_hash(
    records: Iterable[LaunchRecord],
    today: datetime.date,
    *,
    cache_dir: str,
    code_version: str = "",
) -> None:
    """Records the data hash only after outputs were generated successfully."""
    with atomic_writer(_hash_file_path(cache_dir)) as f:
        f.write(compute_data_hash(records, today, code_version).encode())
