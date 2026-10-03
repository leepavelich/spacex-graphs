"""Checks that the parsed launches are complete enough to publish.

Each check raises one of the errors below when the data can't be trusted,
which fails the run instead of publishing graphs with launches missing. These
are pure functions; the CLI fetches the inputs and decides what to log.
"""

import datetime
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

from spacex_graphs.config import FIRST_CONTINUOUS_YEAR, MAX_DAYS_SINCE_LAUNCH
from spacex_graphs.parsing import LaunchRecord


class EmptyPageError(RuntimeError):
    """Raised when a Wikipedia page yields no launch records."""


class MissingYearsError(RuntimeError):
    """Raised when past years that should have launches have none."""


class PublishedLaunchesLostError(RuntimeError):
    """Raised when launches or masses that were published have gone missing."""


class NoRecentLaunchesError(RuntimeError):
    """Raised when the newest parsed launch is too old to be the latest."""


class PublishedLaunch(NamedTuple):
    """A launch as it appears in the published CSV."""

    date: datetime.date
    vehicle: str
    payload: str
    mass: int | None


def check_pages_not_empty(page_records: Mapping[str, Sequence[LaunchRecord]]) -> None:
    """Fails when any page parsed to no launches.

    page_records maps each page's display name to its records. A page with no
    launches almost always means Wikipedia changed the table layout.
    """
    empty = [name for name, records in page_records.items() if not records]
    if empty:
        raise EmptyPageError(
            "no launches parsed from: "
            + ", ".join(empty)
            + " (has the Wikipedia table layout changed?)"
        )


def drop_duplicate_launches(
    records: Sequence[LaunchRecord],
) -> tuple[list[LaunchRecord], int]:
    """Removes launches listed more than once, keeping the first listing.

    When Wikipedia splits a year out of the current list, both pages can list
    the same launches for a while. A vehicle can't launch twice at the same
    minute, so launch time and vehicle identify a launch. Returns the unique
    records and how many duplicates were dropped.
    """
    seen: set[tuple[datetime.datetime, str]] = set()
    unique = []
    for record in records:
        key = (record.launch_datetime, record.vehicle)
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique, len(records) - len(unique)


def drop_future_launches(
    records: Sequence[LaunchRecord], today: datetime.date
) -> tuple[list[LaunchRecord], int]:
    """Removes launches dated after today, returning the rest and the count."""
    kept = [r for r in records if r.launch_datetime.date() <= today]
    return kept, len(records) - len(kept)


def check_year_coverage(records: Iterable[LaunchRecord], today: datetime.date) -> None:
    """Fails when a past year since FIRST_CONTINUOUS_YEAR has no launches.

    That is what happens when Wikipedia moves last year's launches into a
    page that isn't in WIKIPEDIA_PAGES yet. The current year may be empty.
    """
    years = {record.year for record in records}
    missing = [y for y in range(FIRST_CONTINUOUS_YEAR, today.year) if y not in years]
    if missing:
        raise MissingYearsError(
            "no launches found for "
            + ", ".join(map(str, missing))
            + " (has Wikipedia moved them to a page not in WIKIPEDIA_PAGES?)"
        )


def check_recent_launch(records: Iterable[LaunchRecord], today: datetime.date) -> None:
    """Fails when the newest launch is more than MAX_DAYS_SINCE_LAUNCH old.

    If new launches stop parsing (say, the current table's layout changes),
    nothing is lost from the published data, so only this check notices.
    """
    latest = max(record.launch_datetime.date() for record in records)
    if (today - latest).days > MAX_DAYS_SINCE_LAUNCH:
        raise NoRecentLaunchesError(
            f"the newest launch found is from {latest.isoformat()}, more than "
            f"{MAX_DAYS_SINCE_LAUNCH} days ago (have new launches stopped parsing?)"
        )


def _describe(launch: PublishedLaunch) -> str:
    return f"{launch.date.isoformat()} {launch.vehicle} ({launch.payload})"


def check_published_launches(
    records: Iterable[LaunchRecord], published: Sequence[PublishedLaunch]
) -> None:
    """Fails when anything published has gone missing from the new data.

    Every published launch must still be found, matched on its date and
    vehicle (times are ignored, since Wikipedia refines them after launch).
    Dates aren't matched loosely: SpaceX launches nearly daily, so a launch
    "moved by a day" is indistinguishable from a lost launch next to a new
    one. A published launch with a known mass must not have lost it. Wikipedia only adds
    launches and masses, so any loss means part of a page stopped parsing,
    however small: two heavy Starship flights are a few percent of a year's
    mass. published is empty on a first run.
    """
    records = list(records)
    unmatched = Counter(
        (record.launch_datetime.date(), record.vehicle) for record in records
    )
    mass_known = {
        (record.launch_datetime.date(), record.vehicle)
        for record in records
        if record.payload_mass is not None
    }

    missing = []
    lost_mass = []
    for launch in published:
        key = (launch.date, launch.vehicle)
        if unmatched[key] == 0:
            missing.append(launch)
            continue
        unmatched[key] -= 1
        if launch.mass is not None and key not in mass_known:
            lost_mass.append(launch)

    problems = []
    if missing:
        problems.append(
            f"{len(missing)} published launches are missing: "
            + "; ".join(map(_describe, missing[:5]))
            + ("; ..." if len(missing) > 5 else "")
        )
    if lost_mass:
        problems.append(
            f"{len(lost_mass)} published launches lost their mass: "
            + "; ".join(map(_describe, lost_mass[:5]))
            + ("; ..." if len(lost_mass) > 5 else "")
        )
    if problems:
        raise PublishedLaunchesLostError(
            ". ".join(problems) + " (has part of a Wikipedia table stopped parsing?)"
        )
