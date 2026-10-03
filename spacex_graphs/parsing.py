"""Parses launch records out of Wikipedia launch-list HTML tables."""

import datetime
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

from bs4 import BeautifulSoup, Tag


class LaunchRecord(NamedTuple):
    """A single launch parsed from Wikipedia, as Wikipedia reports it.

    payload_mass is the reported mass in kg, or None when Wikipedia gives no
    mass (unknown or classified payloads); it is kept for failed launches too.
    outcome is the launch outcome text, such as "Success" or "Failure".
    Whether a launch's mass counts in the graphs is decided in transform.
    """

    year: int
    orbit: str
    payload: str
    payload_mass: int | None
    launch_datetime: datetime.datetime
    vehicle: str
    outcome: str = "Success"


def parse_launch_datetime(text: str) -> datetime.datetime | None:
    """Parses a launch date/time from a Wikipedia date cell.

    Handles "26 August 2025", "August 26, 2025", with an optional "HH:MM" time
    anywhere in the cell. Returns None if no valid date is found, including
    when the cell looks like a date but isn't one (e.g. "Mid 2026 to 2027",
    "31 February 2026"), so one malformed cell can't abort the whole run.
    """
    date_match = re.search(r"(\d{1,2})\s+(\w+)\s*(\d{4})", text)
    if date_match:
        day, month_name, year = date_match.groups()
    else:
        alt_match = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", text)
        if not alt_match:
            return None
        month_name, day, year = alt_match.groups()

    time_match = re.search(r"(\d{2}):(\d{2})", text)
    if time_match:
        hour, minute = (int(part) for part in time_match.groups())
    else:
        hour = minute = 0

    try:
        month = datetime.datetime.strptime(month_name[:3], "%b").month
        date = datetime.date(int(year), month, int(day))
        return datetime.datetime.combine(date, datetime.time(hour, minute))
    except ValueError:
        return None


_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_RANGE = rf"({_NUMBER})\s*(?:-|to)\s*({_NUMBER})"
_KG_PER_LB = 0.45359237


def _to_float(number: str) -> float:
    return float(number.replace(",", ""))


def _mass_before_unit(s: str, unit: str) -> float | None:
    """Returns the mass (or average of a range) immediately before a unit."""
    range_match = re.search(rf"{_RANGE}\s*{unit}\b", s, flags=re.IGNORECASE)
    if range_match:
        return (_to_float(range_match[1]) + _to_float(range_match[2])) / 2
    single_match = re.search(rf"({_NUMBER})\s*{unit}\b", s, flags=re.IGNORECASE)
    if single_match:
        return _to_float(single_match[1])
    return None


def parse_payload_mass_text(text: str | None) -> int | None:
    """Parses a payload mass cell into an integer mass in kg.

    Handles values like:
    - "5,000 kg" and "5 000 kg" (space or non-breaking-space thousands)
    - "5,000–6,000 kg" or "5000 to 6000 kg" (returns the average 5,500)
    - "~16,000 kg (35,000 lb)" (returns 16000)
    - "75,200 lb (34,100 kg)" (the kg figure wins wherever it appears)
    - "2,500 lb" with no kg figure (converted to kg)
    Footnote markers like "[12]" are removed first, so "Classified[12]" has no
    mass (None) rather than 12 kg. Numbers not attached to a unit (years, counts)
    are only used when the cell has no unit at all. Returns None when the cell
    holds no mass, such as "Unknown", "Classified", or "—".
    """
    if not text:
        return None

    s = re.sub(r"\[[^\]]*\]", "", str(text))
    s = s.replace("\u2013", "-").replace("\u2014", "-")  # en/em dash -> hyphen
    # Join digit groups separated by a space, nbsp, or narrow nbsp ("16 000")
    s = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))", "", s)

    kg = _mass_before_unit(s, "kg")
    if kg is not None:
        return round(kg)

    lb = _mass_before_unit(s, "lb")
    if lb is not None:
        return round(lb * _KG_PER_LB)

    range_match = re.search(_RANGE, s)
    if range_match:
        return round((_to_float(range_match[1]) + _to_float(range_match[2])) / 2)
    single_match = re.search(_NUMBER, s)
    if single_match:
        return round(_to_float(single_match[0]))

    return None


def _cell_text(cell: Tag, line_separator: str = " ") -> str:
    """Returns a table cell's visible text as one clean line.

    Footnote superscripts and hidden sort keys are removed, line breaks become
    line_separator (so "SPHEREx<br>PUNCH" doesn't read as "SPHERExPUNCH"), and
    runs of whitespace, including non-breaking spaces, collapse to one space.
    """
    for hidden in cell.select('sup.reference, [style*="display:none"]'):
        hidden.decompose()
    for line_break in cell.find_all("br"):
        line_break.replace_with("\n")
    text = re.sub(r"\[[^\]]*\]", "", cell.get_text())
    lines = (" ".join(line.split()) for line in text.splitlines())
    return line_separator.join(line for line in lines if line)


def _parse_falcon_row(cols: Sequence[Tag]) -> LaunchRecord | None:
    """Parses a Falcon 9/Heavy table row.

    Columns: 0: Date, 1: Booster, 3: Payload, 4: Mass, 5: Orbit, 7: Outcome.
    """
    if len(cols) not in (9, 11):
        return None

    launch_datetime = parse_launch_datetime(cols[0].get_text(separator=" ", strip=True))
    if launch_datetime is None:
        return None

    booster = _cell_text(cols[1])
    payload = _cell_text(cols[3])
    # "; " keeps separate lines from being read as one space-grouped number
    payload_mass = parse_payload_mass_text(_cell_text(cols[4], "; "))
    orbit = _cell_text(cols[5])
    outcome = _cell_text(cols[7])
    vehicle = "Falcon Heavy" if "Heavy" in booster or "FH" in booster else "Falcon 9"

    return LaunchRecord(
        year=launch_datetime.year,
        orbit=orbit,
        payload=payload,
        payload_mass=payload_mass,
        launch_datetime=launch_datetime,
        vehicle=vehicle,
        outcome=outcome,
    )


def _parse_starship_row(cols: Sequence[Tag]) -> LaunchRecord | None:
    """Parses a Starship table row.

    Columns: 0: Date, 2: Ship version, 4: Payload, 5: Mass, 6: Orbit, 8: Outcome.
    """
    if len(cols) != 11:
        return None

    launch_datetime = parse_launch_datetime(cols[0].get_text(separator=" ", strip=True))
    if launch_datetime is None:
        return None

    ship_version = _cell_text(cols[2])
    payload = _cell_text(cols[4])
    payload_mass = parse_payload_mass_text(_cell_text(cols[5], "; "))
    orbit = _cell_text(cols[6])
    outcome = _cell_text(cols[8])

    # Extract block version from ship (e.g., "Block 1S24" -> "Block 1 Starship")
    block_match = re.search(r"Block\s+(\d+)", ship_version)
    vehicle = f"Block {block_match.group(1)} Starship" if block_match else "Starship"

    # An empty payload cell shows just "—" (its "N/a" sort key is hidden)
    if payload.startswith("—") or not payload:
        payload = "Starship Test"

    return LaunchRecord(
        year=launch_datetime.year,
        orbit=orbit,
        payload=payload,
        payload_mass=payload_mass,
        launch_datetime=launch_datetime,
        vehicle=vehicle,
        outcome=outcome,
    )


def parse_launch_page(url: str, content: bytes | str) -> list[LaunchRecord]:
    """Parses all launch records from a Wikipedia launch-list page."""
    parse_row: Callable[[Sequence[Tag]], LaunchRecord | None] = (
        _parse_starship_row if "Starship" in url else _parse_falcon_row
    )

    soup = BeautifulSoup(content, "html.parser")
    records: list[LaunchRecord] = []
    for table in soup.find_all("table", {"class": "wikitable"}):
        for row in table.find_all("tr"):
            cells = [cell for cell in row.find_all("td") if isinstance(cell, Tag)]
            record = parse_row(cells)
            if record is not None:
                records.append(record)
    return records
