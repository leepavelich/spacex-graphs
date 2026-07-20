"""Parses launch records out of Wikipedia launch-list HTML tables."""

import datetime
import re
from typing import NamedTuple, Optional

from bs4 import BeautifulSoup


class LaunchRecord(NamedTuple):
    """A single launch parsed from Wikipedia."""

    year: int
    orbit: str
    payload: str
    payload_mass: int
    launch_datetime: datetime.datetime
    vehicle: str


def parse_launch_datetime(text) -> Optional[datetime.datetime]:
    """Parses a launch date/time from a Wikipedia date cell.

    Handles "26 August 2025", "August 26, 2025", with an optional "HH:MM" time
    anywhere in the cell. Returns None if no date is found.
    """
    date_match = re.search(r"(\d{1,2})\s+(\w+)\s*(\d{4})", text)
    if date_match:
        day, month_name, year = date_match.groups()
    else:
        alt_match = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", text)
        if not alt_match:
            return None
        month_name, day, year = alt_match.groups()

    month = datetime.datetime.strptime(month_name[:3], "%b").month
    date = datetime.date(int(year), month, int(day))

    time_match = re.search(r"(\d{2}):(\d{2})", text)
    if time_match:
        hour, minute = (int(part) for part in time_match.groups())
    else:
        hour = minute = 0

    return datetime.datetime.combine(date, datetime.time(hour, minute))


def parse_payload_mass_text(text) -> int:
    """Parses a payload mass cell into an integer mass in kg.

    Handles values like:
    - "5,000 kg"
    - "5,000–6,000 kg" (returns the average 5,500)
    - "5000-6000 kg" (same as above)
    - "~16,000 kg" (returns 16000)
    - Any footnotes or extra text are ignored
    Returns 0 if not parseable.
    """
    if not text:
        return 0

    s = str(text).strip()
    s = s.replace("–", "-").replace("—", "-")  # en/em dash -> hyphen

    # If there's an explicit numeric range, average the bounds (hyphen or 'to')
    range_match = re.search(r"(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)", s, flags=re.IGNORECASE)
    if range_match:
        a, b = (int(part.replace(",", "")) for part in range_match.groups())
        return int(round((a + b) / 2))

    single_match = re.search(r"(\d[\d,]*)", s)
    if single_match:
        return int(single_match.group(1).replace(",", ""))

    return 0


def _parse_falcon_row(cols) -> Optional[LaunchRecord]:
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

    if "Heavy" in booster or "FH" in booster:
        vehicle = "Falcon Heavy"
    else:
        vehicle = "Falcon 9"

    return LaunchRecord(
        launch_datetime.year, orbit, payload, payload_mass, launch_datetime, vehicle
    )


def _parse_starship_row(cols) -> Optional[LaunchRecord]:
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
    if block_match:
        vehicle = f"Block {block_match.group(1)} Starship"
    else:
        vehicle = "Starship"

    # Only successful launches count payload mass
    if "success" in launch_outcome:
        payload_mass = parse_payload_mass_text(payload_mass_text)
    else:
        payload_mass = 0

    if payload == "—" or not payload:
        payload = "Starship Test"

    return LaunchRecord(
        launch_datetime.year, orbit, payload, payload_mass, launch_datetime, vehicle
    )


def parse_launch_page(url, content) -> list:
    """Parses all launch records from a Wikipedia launch-list page."""
    parse_row = _parse_starship_row if "Starship" in url else _parse_falcon_row

    soup = BeautifulSoup(content, "html.parser")
    records = []
    for table in soup.find_all("table", {"class": "wikitable"}):
        for row in table.find_all("tr"):
            record = parse_row(row.find_all("td"))
            if record is not None:
                records.append(record)
    return records
