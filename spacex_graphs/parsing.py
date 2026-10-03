"""Parses launch records out of Wikipedia launch-list HTML tables."""

import datetime
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

from bs4 import BeautifulSoup, Tag


class LaunchRecord(NamedTuple):
    """A single launch parsed from Wikipedia."""

    year: int
    orbit: str
    payload: str
    payload_mass: int
    launch_datetime: datetime.datetime
    vehicle: str


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


def parse_payload_mass_text(text: str | None) -> int:
    """Parses a payload mass cell into an integer mass in kg.

    Handles values like:
    - "5,000 kg" and "5 000 kg" (space or non-breaking-space thousands)
    - "5,000–6,000 kg" or "5000 to 6000 kg" (returns the average 5,500)
    - "~16,000 kg (35,000 lb)" (returns 16000)
    - "75,200 lb (34,100 kg)" (the kg figure wins wherever it appears)
    - "2,500 lb" with no kg figure (converted to kg)
    Footnote markers like "[12]" are removed first, so "Classified[12]"
    returns 0 rather than 12. Numbers not attached to a unit (years, counts)
    are only used when the cell has no unit at all. Returns 0 if not parseable.
    """
    if not text:
        return 0

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

    return 0


def _parse_falcon_row(cols: Sequence[Tag]) -> LaunchRecord | None:
    """Parses a Falcon 9/Heavy table row.

    Columns: 0: Date, 1: Booster, 3: Payload, 4: Mass, 5: Orbit, 7: Outcome.
    """
    if len(cols) not in (9, 11):
        return None

    launch_datetime = parse_launch_datetime(cols[0].get_text(separator=" ", strip=True))
    if launch_datetime is None:
        return None

    booster = cols[1].text.strip()
    payload = cols[3].text.strip()
    payload_mass = parse_payload_mass_text(cols[4].text.strip())
    orbit = cols[5].text.strip()
    launch_outcome = cols[7].text.strip().lower()

    if "success" not in launch_outcome:
        payload_mass = 0

    vehicle = "Falcon Heavy" if "Heavy" in booster or "FH" in booster else "Falcon 9"

    return LaunchRecord(
        launch_datetime.year, orbit, payload, payload_mass, launch_datetime, vehicle
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

    ship_version = cols[2].text.strip()
    payload = cols[4].text.strip()
    payload_mass_text = cols[5].text.strip()
    orbit = cols[6].text.strip()
    launch_outcome = cols[8].text.strip().lower()

    # Extract block version from ship (e.g., "Block 1S24" -> "Block 1 Starship")
    block_match = re.search(r"Block\s+(\d+)", ship_version)
    vehicle = f"Block {block_match.group(1)} Starship" if block_match else "Starship"

    # Only successful launches count payload mass
    if "success" in launch_outcome:
        payload_mass = parse_payload_mass_text(payload_mass_text)
    else:
        payload_mass = 0

    # An empty payload cell renders as "—" followed by a hidden "N/a" sort key
    if payload.startswith("—") or not payload:
        payload = "Starship Test"

    return LaunchRecord(
        launch_datetime.year, orbit, payload, payload_mass, launch_datetime, vehicle
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
