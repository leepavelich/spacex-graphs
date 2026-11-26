"""Parses launch records out of Wikipedia launch-list HTML tables."""

import copy
import datetime
import math
import re
from collections.abc import Iterator, Sequence
from typing import NamedTuple, assert_never

from bs4 import BeautifulSoup, Tag

from spacex_graphs.config import TableLayout

# A footnote marker such as "[12]" or "[a]"
FOOTNOTE = re.compile(r"\[[^\]]*\]")


class LaunchRecord(NamedTuple):
    """A single launch parsed from Wikipedia, as Wikipedia reports it.

    payload_mass is the reported mass in kg, or None when Wikipedia gives no
    mass (unknown or classified payloads); it is kept for failed launches too.
    outcome is the launch outcome text, such as "Success" or "Failure".
    Whether a launch's mass counts in the graphs is decided in transform.

    A launch listed over several table rows (one per payload, sharing the
    date cell through rowspan) is one record: see parse_launch_page.
    """

    year: int
    orbit: str
    payload: str
    payload_mass: int | None
    launch_datetime: datetime.datetime
    vehicle: str
    outcome: str = "Success"


# English month names only, so the result never depends on the process locale
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
# Longest names first, so "sept" isn't read as "sep" followed by a stray "t"
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "26 August 2025" and "August 26, 2025"; the month must be a whole word, so
# "Maybe 12, 2026" isn't May
_DAY_FIRST = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s+({_MONTH})\b\.?,?\s*(\d{{4}})(?!\d)", re.IGNORECASE
)
_MONTH_FIRST = re.compile(
    rf"\b({_MONTH})\b\.?\s+(\d{{1,2}})(?:,\s*|\s+)(\d{{4}})(?!\d)", re.IGNORECASE
)
# A date right after "1–" or "April to" ends a range like "1–3 May 2026" or
# "30 April to 2 May 2026", and one followed by "– 3 May" or "to June"
# starts one
_RANGE_BEFORE = re.compile(
    rf"(?:\d|\b(?:{_MONTH}))\s*(?:[-\u2013\u2014]|\bto\b)\s*$", re.IGNORECASE
)
_RANGE_AFTER = re.compile(
    rf"^\s*(?:[-\u2013\u2014]|to\b)\s*(?:\d{{1,2}}(?=[\s,])|(?:{_MONTH})\b)",
    re.IGNORECASE,
)
_TIME = r"(?<![\d:])(\d{1,2}):(\d{2})(?!\d)"
_UTC_TIME = re.compile(rf"{_TIME}(?::\d{{2}})?\s*UTC\b", re.IGNORECASE)
_ANY_TIME = re.compile(_TIME)


def parse_launch_datetime(text: str) -> datetime.datetime | None:
    """Parses a launch date/time from a Wikipedia date cell.

    Handles "26 August 2025", "August 26, 2025", and "Sept 1, 2025", with an
    optional "H:MM" or "HH:MM" time anywhere in the cell. When several times
    appear, one marked UTC wins ("14:30 EST (19:30 UTC)" is 19:30), otherwise
    the first. Month names are English, whatever the process locale.

    Returns None if no single valid date is found, including when the cell
    looks like a date but isn't one ("Mid 2026 to 2027", "31 February 2026",
    "Maybe 12, 2026") or is a range ("1–3 May 2026", "May 31 – June 2,
    2026"), so one malformed cell can't abort the whole run. The result is a
    naive datetime in UTC, as Wikipedia gives launch times.
    """
    day_first = _DAY_FIRST.search(text)
    month_first = _MONTH_FIRST.search(text)
    # Whichever date comes first in the cell is the launch date
    if day_first and (not month_first or day_first.start() <= month_first.start()):
        match = day_first
        day, month_name, year = match.groups()
    elif month_first:
        match = month_first
        month_name, day, year = match.groups()
    else:
        return None
    if _RANGE_BEFORE.search(text[: match.start()]) or _RANGE_AFTER.match(
        text[match.end() :]
    ):
        return None

    time_match = _UTC_TIME.search(text) or _ANY_TIME.search(text)
    hour, minute = (int(part) for part in time_match.groups()) if time_match else (0, 0)

    try:
        date = datetime.date(int(year), _MONTHS[month_name.lower()], int(day))
        return datetime.datetime.combine(date, datetime.time(hour, minute))
    except ValueError:
        return None


_DIGITS = r"\d[\d,]*(?:\.\d+)?"
# A number that isn't the tail of a word, another number, or a hyphenated
# label, so the "500" in "CAS500", the "5" in "1.5e3", and "-500" aren't masses
_NUMBER = rf"(?<![\w.,\-]){_DIGITS}"
# An optional count ("2 × 500 kg") and a value or range ("5,000–6,000 kg").
# A range's dash is a hyphen or an en dash, never an em dash, so "Flight 12
# — 5,000 kg" isn't a range from 12.
_TERM = (
    rf"(?:({_NUMBER})\s*[\u00d7xX]\s*|(?<![\w.,\-]))({_DIGITS})"
    rf"(?:(?:\s*[-\u2013]\s*|\s+to\s+)({_DIGITS}))?"
)
# Units in order of precedence: a cell's metric figure wins over pounds. A
# bare "t" needs a space before it and can't start a word or a "t-"/"t/"
# compound, so "Intelsat 15T" and "20 T-class satellites" have no mass.
_UNITS_TO_KG = (
    (r"\s*(?:kg|kilograms?)\b", re.IGNORECASE, 1.0),
    (r"(?i:\s*(?:metric\s+)?tonnes?\b)|\s+t(?![\w\-/])", 0, 1000.0),
    (r"\s*lbs?\b", re.IGNORECASE, 0.45359237),
)
# Spaces, nbsp, or narrow nbsp grouping thousands ("16 000"), in a number not
# glued to a word or hyphen, so "CAS500-2 500 kg" stays two numbers
_SPACE_GROUPED = re.compile(r"(?<![\w.,\-])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")
# A parenthetical conversion between summed masses: "1 kg (2 lb) + 3 kg"
_ASIDE = r"(?:\s*\([^()]*\))?"


def _to_float(number: str) -> float:
    return float(number.replace(",", ""))


def _term_value(count: str | None, low: str, high: str | None) -> float:
    """A term's mass in its unit: a range's average, times any count."""
    value = _to_float(low)
    if high is not None:
        top = _to_float(high)
        # Estimates span a narrow range: "Flight 12 – 5,000 kg" or "Group 9-3
        # kg" is a label then a mass, not a range
        value = (value + top) / 2 if value <= top <= 10 * value else top
    return value * (_to_float(count) if count else 1)


def _mass_in_unit(s: str, unit: str, flags: int) -> float | None:
    """Returns the first mass given in a unit, summing "a kg + b kg" terms."""
    term = re.compile(_TERM + f"(?:{unit})", flags)
    match = term.search(s)
    if match is None:
        return None
    total = _term_value(*match.groups())
    plus = re.compile(rf"{_ASIDE}\s*\+\s*")
    end = match.end()
    while (joiner := plus.match(s, end)) and (more := term.match(s, joiner.end())):
        total += _term_value(*more.groups())
        end = more.end()
    return total


def parse_payload_mass_text(text: str | None) -> int | None:
    """Parses a payload mass cell into an integer mass in kg.

    Handles values like:
    - "5,000 kg" and "5 000 kg" (space or non-breaking-space thousands)
    - "5,000–6,000 kg" or "5000 to 6000 kg" (returns the average 5,500)
    - "~16,000 kg (35,000 lb)" (returns 16000)
    - "75,200 lb (34,100 kg)" (the kg figure wins wherever it appears)
    - "1.5 t", "1.5 tonnes", or "1.5 metric tonnes" (1,500), "12 kilograms",
      and "2,500 lb" or "2,500 lbs" (1,134)
    - "1,500 kg + 800 kg" (2,300) and "2 × 500 kg" (1,000)
    Footnote markers like "[12]" are removed first, so "Classified[12]" has no
    mass (None) rather than 12 kg. Only numbers attached to a unit count, so
    "Unknown (22 satellites)", "Intelsat 15T", and "20 T-class satellites"
    have no mass either, nor does a negative figure. Returns None when the
    cell holds no mass, such as "Unknown", "Classified", or "—".
    """
    if not text:
        return None

    s = FOOTNOTE.sub("", str(text))
    s = s.replace("\u2011", "-").replace("\u2212", "-")  # nb hyphen, minus
    s = _SPACE_GROUPED.sub(lambda m: re.sub(r"\D", "", m[0]), s)

    for unit, flags, kg_per_unit in _UNITS_TO_KG:
        mass = _mass_in_unit(s, unit, flags)
        if mass is not None:
            kg = mass * kg_per_unit
            return round(kg) if math.isfinite(kg) else None
    return None


_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
_HIDDEN_CLASSES = {"sortkey", "sr-only"}


def _is_hidden(tag: Tag) -> bool:
    """Whether a tag holds markup a reader doesn't see as part of the cell."""
    if tag.name in ("style", "script"):
        return True
    classes = set(tag.get_attribute_list("class"))
    if tag.name == "sup" and "reference" in classes:
        return True
    if classes & _HIDDEN_CLASSES:
        return True
    return bool(_DISPLAY_NONE.search(str(tag.get("style") or "")))


def _cell_text(cell: Tag, line_separator: str = " ") -> str:
    """Returns a table cell's visible text as one clean line.

    Footnote superscripts, hidden sort keys, screen-reader-only text, and
    embedded styles and scripts are removed, line breaks become
    line_separator (so "SPHEREx<br>PUNCH" doesn't read as "SPHERExPUNCH"),
    and runs of whitespace, including non-breaking spaces, collapse
    to one space. It works on a copy, so the cell itself is left intact for
    the other rows a rowspan cell belongs to.
    """
    cell = copy.copy(cell)
    for hidden in cell.find_all(_is_hidden):
        if not hidden.decomposed:
            hidden.decompose()
    for line_break in cell.find_all("br"):
        line_break.replace_with("\n")
    text = FOOTNOTE.sub("", cell.get_text())
    lines = (" ".join(line.split()) for line in text.splitlines())
    return line_separator.join(line for line in lines if line)


# HTML's own caps on spans, which also bound the grid a malformed page builds
_MAX_COLSPAN = 1000
_MAX_ROWSPAN = 65534


def _span(cell: Tag, attribute: str, limit: int) -> int:
    """A cell's rowspan or colspan: at least 1, at most limit."""
    match = re.match(r"\s*(\d+)", str(cell.get(attribute) or ""))
    return min(max(int(match[1]), 1), limit) if match else 1


def _children(tag: Tag, names: tuple[str, ...]) -> Iterator[Tag]:
    """A tag's direct children with one of the given names."""
    return (c for c in tag.children if isinstance(c, Tag) and c.name in names)


def _table_rows(table: Tag) -> Iterator[Tag]:
    """A table's own rows, not those of tables nested in its cells."""
    for child in _children(table, ("tr", "thead", "tbody", "tfoot")):
        if child.name == "tr":
            yield child
        else:
            yield from _children(child, ("tr",))


def _table_grid(table: Tag) -> list[list[Tag]]:
    """Lays out a table's cells as a grid of rows, resolving rowspan and colspan.

    A cell spanning several rows or columns appears in each slot it covers,
    as the same Tag, so callers can tell a shared cell from a repeated value.
    """
    grid: list[list[Tag]] = []
    # Column -> (cell, rows it still covers below the current row)
    spans: dict[int, tuple[Tag, int]] = {}
    for tr in _table_rows(table):
        row: list[Tag] = []
        new_spans: dict[int, tuple[Tag, int]] = {}
        for cell in [*_children(tr, ("td", "th")), None]:
            while len(row) in spans:  # slots taken by cells from rows above
                row.append(spans[len(row)][0])
            if cell is None:
                break
            rowspan = _span(cell, "rowspan", _MAX_ROWSPAN)
            for _ in range(_span(cell, "colspan", _MAX_COLSPAN)):
                if rowspan > 1:
                    new_spans[len(row)] = (cell, rowspan - 1)
                row.append(cell)
        spans = {
            col: (cell, left - 1) for col, (cell, left) in spans.items() if left > 1
        }
        spans.update(new_spans)
        grid.append(row)
    return grid


def _launch_rows(table: Tag) -> Iterator[list[list[Tag]]]:
    """Groups a table's data rows into launches.

    A row's columns are its data (td) cells, so the header (th) cell holding
    the flight number doesn't shift them. Rows that share their date cell
    through rowspan list one launch's payloads and form one group. A row whose
    first cell spans several columns, such as a launch's description, is not
    a launch row.
    """
    group: list[list[Tag]] = []
    for grid_row in _table_grid(table):
        cols = [cell for cell in grid_row if cell.name == "td"]
        if len(cols) < 2 or cols[0] is cols[1]:
            continue
        if group and cols[0] is group[0][0] and len(cols) == len(group[0]):
            group.append(cols)
            continue
        if group:
            yield group
        group = [cols]
    if group:
        yield group


def _distinct_cell_texts(
    rows: Sequence[Sequence[Tag]], index: int, line_separator: str = " "
) -> Iterator[str]:
    """The non-empty texts of a column's distinct cells across a launch's rows.

    A rowspan cell shared by several rows counts once.
    """
    seen: list[Tag] = []
    for row in rows:
        cell = row[index]
        if any(cell is other for other in seen):
            continue
        seen.append(cell)
        text = _cell_text(cell, line_separator)
        if text:
            yield text


def _distinct_texts(rows: Sequence[Sequence[Tag]], index: int) -> list[str]:
    """The unique non-empty texts of a column, in table order."""
    return list(dict.fromkeys(_distinct_cell_texts(rows, index)))


def _total_mass(rows: Sequence[Sequence[Tag]], index: int) -> int | None:
    """The sum of a launch's reported payload masses, or None if it has none.

    Every payload's reported mass counts, whatever that payload's own outcome:
    the launch's outcome decides, in transform, whether its mass counts.
    """
    # "; " keeps separate lines from being read as one space-grouped number
    masses = [
        mass
        for text in _distinct_cell_texts(rows, index, "; ")
        if (mass := parse_payload_mass_text(text)) is not None
    ]
    return sum(masses) if masses else None


def _parse_falcon_launch(rows: Sequence[Sequence[Tag]]) -> LaunchRecord | None:
    """Parses a Falcon 9/Heavy launch from its table rows.

    Columns: 0: Date, 1: Booster, 3: Payload, 4: Mass, 5: Orbit, 7: Outcome.
    """
    first = rows[0]
    if len(first) not in (9, 11):
        return None

    launch_datetime = parse_launch_datetime(_cell_text(first[0]))
    if launch_datetime is None:
        return None

    booster = _cell_text(first[1])
    vehicle = "Falcon Heavy" if "Heavy" in booster or "FH" in booster else "Falcon 9"

    return LaunchRecord(
        year=launch_datetime.year,
        orbit=_cell_text(first[5]),
        payload=" + ".join(_distinct_texts(rows, 3)),
        payload_mass=_total_mass(rows, 4),
        launch_datetime=launch_datetime,
        vehicle=vehicle,
        outcome="; ".join(_distinct_texts(rows, 7)),
    )


def _parse_starship_launch(rows: Sequence[Sequence[Tag]]) -> LaunchRecord | None:
    """Parses a Starship launch from its table rows.

    Columns: 0: Date, 2: Ship version, 4: Payload, 5: Mass, 6: Orbit, 8: Outcome.
    """
    first = rows[0]
    if len(first) != 11:
        return None

    launch_datetime = parse_launch_datetime(_cell_text(first[0]))
    if launch_datetime is None:
        return None

    # Extract block version from ship (e.g., "Block 1S24" -> "Block 1 Starship")
    block_match = re.search(r"Block\s+(\d+)", _cell_text(first[2]))
    vehicle = f"Block {block_match.group(1)} Starship" if block_match else "Starship"

    # An empty payload cell shows just "—" (its "N/a" sort key is hidden)
    payloads = [p for p in _distinct_texts(rows, 4) if not p.startswith("—")]

    return LaunchRecord(
        year=launch_datetime.year,
        orbit=_cell_text(first[6]),
        payload=" + ".join(payloads) or "Starship Test",
        payload_mass=_total_mass(rows, 5),
        launch_datetime=launch_datetime,
        vehicle=vehicle,
        outcome="; ".join(_distinct_texts(rows, 8)),
    )


def parse_launch_page(layout: TableLayout, content: bytes | str) -> list[LaunchRecord]:
    """Parses all launch records from a Wikipedia launch-list page.

    layout names the page's table layout (config.Page.layout), which picks
    the row parser. Only the rows of each wikitable itself are read, never
    those of a table nested in a cell, with rowspan and colspan resolved so
    each row's cells line up with its columns.

    A launch with several payloads is listed as one row per payload, sharing
    the date cell through rowspan; it becomes one record. Its payload names
    are joined with " + " and its outcomes (when payloads have their own)
    with "; ", and its mass is the sum of the payloads' reported masses, or
    None if none is reported. Its orbit is the first payload's.
    """
    match layout:
        case "falcon":
            parse_launch = _parse_falcon_launch
        case "starship":
            parse_launch = _parse_starship_launch
        case _:
            assert_never(layout)

    soup = BeautifulSoup(content, "html.parser")
    records: list[LaunchRecord] = []
    for table in soup.find_all("table", {"class": "wikitable"}):
        for rows in _launch_rows(table):
            record = parse_launch(rows)
            if record is not None:
                records.append(record)
    return records
