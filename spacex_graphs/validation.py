"""Checks that the parsed launches are complete enough to publish.

Each check raises one of the errors below when the data can't be trusted,
which fails the run instead of publishing graphs with launches missing. These
are pure functions; the CLI fetches the inputs and decides what to log.
"""

import datetime
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from spacex_graphs.config import FIRST_CONTINUOUS_YEAR, MAX_LAUNCH_COUNT_DROP
from spacex_graphs.parsing import LaunchRecord


class EmptyPageError(RuntimeError):
    """Raised when a Wikipedia page yields no launch records."""


class MissingYearsError(RuntimeError):
    """Raised when past years that should have launches have none."""


class LaunchCountDropError(RuntimeError):
    """Raised when a year has far fewer launches than were last published."""


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


def launch_counts_by_year(records: Iterable[LaunchRecord]) -> dict[int, int]:
    """Counts launches per year."""
    return dict(Counter(record.year for record in records))


def check_launch_counts(
    records: Iterable[LaunchRecord], published: Mapping[int, int]
) -> None:
    """Fails when a year has lost launches since they were last published.

    Wikipedia only adds launches, apart from the odd correction, so a year
    with more than MAX_LAUNCH_COUNT_DROP fewer launches than the published
    CSV means part of a page stopped parsing, such as one year's table after
    a layout change. published maps years to their published launch counts
    and is empty on a first run.
    """
    counts = launch_counts_by_year(records)
    drops = {
        year: (before, counts.get(year, 0))
        for year, before in published.items()
        if before - counts.get(year, 0) > MAX_LAUNCH_COUNT_DROP
    }
    if drops:
        raise LaunchCountDropError(
            "fewer launches than last published: "
            + ", ".join(
                f"{year} has {now} (was {before})"
                for year, (before, now) in sorted(drops.items())
            )
            + " (has part of a Wikipedia table stopped parsing?)"
        )
