"""Pure checks and filters for launch completeness and integrity before publication."""

import datetime
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import Enum, auto
from typing import NamedTuple

from spacex_graphs.config import (
    DEFAULT_MAX_PAYLOAD_MASS_KG,
    FIRST_CONTINUOUS_YEAR,
    MAX_DAYS_SINCE_LAUNCH,
    MAX_PAYLOAD_MASS_KG,
    MAX_PUBLISHED_MASS_DROP_FRACTION,
    MAX_UNRECOGNIZED_OUTCOME_FRACTION,
    MIN_PUBLISHED_MASS_DROP_KG,
)
from spacex_graphs.errors import DataError, ImplausibleMassError, OutcomeIntegrityError
from spacex_graphs.parsing import LaunchRecord


class EmptyPageError(DataError):
    """Raised when a Wikipedia page yields no launch records."""


class MissingYearsError(DataError):
    """Raised when past years that should have launches have none."""


class PublishedLaunchesLostError(DataError):
    """Raised when published launches or masses go missing or materially regress."""


class NoRecentLaunchesError(DataError):
    """Raised when no launches were found or the newest one is too old."""


class OutcomeKind(Enum):
    """The meaning of an outcome cell, without changing the reported text."""

    SUCCESS = auto()
    FAILURE = auto()
    UNLAUNCHED = auto()
    UNRECOGNIZED = auto()


_UNLAUNCHED = re.compile(
    r"^(?:launch )?(?:scheduled|planned|tbd|scrubbed|upcoming|delayed)\b"
)
_SUCCESS = re.compile(r"^success(?:ful)?\b")
_FAILURE = re.compile(
    r"^(?:failure|failed|partial success|partial failure|precluded|unsuccessful)\b"
)
_FAILED_QUALIFIER = re.compile(r"\b(?:failed|failure|partial|unsuccessful)\b")


def outcome_kind(outcome: str) -> OutcomeKind:
    """Classifies an outcome for integrity checks and the transform."""
    outcome = " ".join(outcome.split(";", 1)[0].casefold().split())
    if _UNLAUNCHED.match(outcome):
        return OutcomeKind.UNLAUNCHED
    # The Crew Dragon abort test successfully delivered its test payload.
    if outcome == "successful simulated failure":
        return OutcomeKind.SUCCESS
    if _SUCCESS.match(outcome):
        return (
            OutcomeKind.FAILURE
            if _FAILED_QUALIFIER.search(outcome)
            else OutcomeKind.SUCCESS
        )
    if _FAILURE.match(outcome):
        return OutcomeKind.FAILURE
    return OutcomeKind.UNRECOGNIZED


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
    """Removes launches listed more than once, preferring a reported mass.

    When Wikipedia splits a year out of the current list, both pages can list
    the same launches for a while. A vehicle can't launch twice at the same
    minute, so launch time and vehicle identify a launch. Among equally
    complete listings, keeps the first. Returns the unique records and the
    number of duplicates.
    """
    unique: dict[tuple[datetime.datetime, str], LaunchRecord] = {}
    for record in records:
        key = (record.launch_datetime, record.vehicle)
        previous = unique.get(key)
        if previous is None or (
            previous.payload_mass is None and record.payload_mass is not None
        ):
            unique[key] = record
    return list(unique.values()), len(records) - len(unique)


def drop_future_launches(
    records: Sequence[LaunchRecord], today: datetime.date
) -> tuple[list[LaunchRecord], int]:
    """Removes launches dated after today, returning the rest and the count."""
    kept = [r for r in records if r.launch_datetime.date() <= today]
    return kept, len(records) - len(kept)


def drop_unlaunched(records: Sequence[LaunchRecord]) -> tuple[list[LaunchRecord], int]:
    """Removes scheduled or scrubbed launches even if they are dated today."""
    kept = [r for r in records if outcome_kind(r.outcome) is not OutcomeKind.UNLAUNCHED]
    return kept, len(records) - len(kept)


def check_outcomes(records: Iterable[LaunchRecord]) -> None:
    """Fails if no successes were parsed or too many outcomes are unfamiliar."""
    counts = Counter(outcome_kind(record.outcome) for record in records)
    if not counts[OutcomeKind.SUCCESS]:
        raise OutcomeIntegrityError(
            "no successful launches found (has the Wikipedia outcome column changed?)"
        )
    unknown = counts[OutcomeKind.UNRECOGNIZED]
    total = counts.total()
    if unknown / total > MAX_UNRECOGNIZED_OUTCOME_FRACTION:
        raise OutcomeIntegrityError(
            f"{unknown} of {total} launch outcomes are unrecognized "
            "(has the Wikipedia outcome column changed?)"
        )


def check_payload_masses(records: Iterable[LaunchRecord]) -> None:
    """Fails if a reported mass is negative or implausibly high for its vehicle."""
    for record in records:
        mass = record.payload_mass
        if mass is None:
            continue
        vehicle = record.vehicle
        family = "Starship" if re.fullmatch(r"Block \d+ Starship", vehicle) else vehicle
        ceiling = MAX_PAYLOAD_MASS_KG.get(family, DEFAULT_MAX_PAYLOAD_MASS_KG)
        if not 0 <= mass <= ceiling:
            raise ImplausibleMassError(
                f"implausible payload mass for {record.launch_datetime:%Y-%m-%d} "
                f"{vehicle}: {mass:,} kg (expected 0–{ceiling:,} kg)"
            )


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
    latest = max((record.launch_datetime.date() for record in records), default=None)
    if latest is None:
        raise NoRecentLaunchesError("no launches found")
    if (today - latest).days > MAX_DAYS_SINCE_LAUNCH:
        raise NoRecentLaunchesError(
            f"the newest launch found is from {latest.isoformat()}, more than "
            f"{MAX_DAYS_SINCE_LAUNCH} days ago (have new launches stopped parsing?)"
        )


def _describe(launch: PublishedLaunch) -> str:
    return f"{launch.date.isoformat()} {launch.vehicle} ({launch.payload})"


def _summarize(items: Sequence[str]) -> str:
    return "; ".join(items[:5]) + ("; ..." if len(items) > 5 else "")


def _pair_known_masses(
    published: Sequence[PublishedLaunch], current: Sequence[PublishedLaunch]
) -> Iterator[tuple[PublishedLaunch, int, int]]:
    """Pairs known masses for launches on one date and vehicle."""
    old_names = Counter(launch.payload for launch in published)
    new_names = Counter(launch.payload for launch in current)
    exact = {
        launch.payload: launch.mass
        for launch in current
        if launch.mass is not None
        and old_names[launch.payload] == new_names[launch.payload] == 1
    }
    matched = set()
    remaining_old = []
    for launch in published:
        if (old_mass := launch.mass) is None:
            continue
        new_mass = exact.get(launch.payload)
        if new_mass is None:
            remaining_old.append((old_mass, launch))
        else:
            matched.add(launch.payload)
            yield launch, old_mass, new_mass

    remaining_new = [
        launch.mass
        for launch in current
        if launch.mass is not None and launch.payload not in matched
    ]
    # With fewer candidates, the separate missing-launch/mass checks already
    # fail. Don't attribute a drop to an arbitrarily chosen unmatched launch.
    if len(remaining_new) < len(remaining_old):
        return
    # Pair largest with largest so a newly added light launch can't displace
    # a heavier baseline launch if a payload name was also revised.
    remaining_old.sort(key=lambda pair: pair[0], reverse=True)
    remaining_new.sort(reverse=True)
    for (old_mass, launch), new_mass in zip(remaining_old, remaining_new, strict=False):
        yield launch, old_mass, new_mass


def check_published_launches(
    records: Iterable[LaunchRecord], published: Sequence[PublishedLaunch]
) -> None:
    """Fails when anything published has gone missing from the new data.

    Every published launch must still be found, matched on its date and
    vehicle (times are ignored, since Wikipedia refines them after launch).
    Dates aren't matched loosely: SpaceX launches nearly daily, so a launch
    "moved by a day" is indistinguishable from a lost launch next to a new
    one. No known mass may be lost. Large relative and absolute drops in a
    known mass can also indicate parser drift instead of a Wikipedia correction.
    published is empty on a first run.
    """
    if not published:
        return

    current: dict[tuple[datetime.date, str], list[PublishedLaunch]] = defaultdict(list)
    unmatched: Counter[tuple[datetime.date, str]] = Counter()
    mass_known: Counter[tuple[datetime.date, str]] = Counter()
    for record in records:
        date = record.launch_datetime.date()
        key = (date, record.vehicle)
        current[key].append(
            PublishedLaunch(date, record.vehicle, record.payload, record.payload_mass)
        )
        unmatched[key] += 1
        if record.payload_mass is not None:
            mass_known[key] += 1

    missing = []
    lost_mass = []
    published_by_day: dict[tuple[datetime.date, str], list[PublishedLaunch]] = (
        defaultdict(list)
    )
    for launch in published:
        key = (launch.date, launch.vehicle)
        published_by_day[key].append(launch)
        if unmatched[key] == 0:
            missing.append(launch)
            continue
        unmatched[key] -= 1
        if launch.mass is not None:
            if mass_known[key] == 0:
                lost_mass.append(launch)
            else:
                mass_known[key] -= 1

    drops = []
    for key, launches in published_by_day.items():
        for launch, old_mass, new_mass in _pair_known_masses(launches, current[key]):
            drop = old_mass - new_mass
            if (
                drop >= MIN_PUBLISHED_MASS_DROP_KG
                and drop > old_mass * MAX_PUBLISHED_MASS_DROP_FRACTION
            ):
                drops.append(f"{_describe(launch)}: {old_mass:,} kg -> {new_mass:,} kg")

    problems = []
    if missing:
        problems.append(
            f"{len(missing)} published launches are missing: "
            + _summarize(list(map(_describe, missing)))
        )
    if lost_mass:
        problems.append(
            f"{len(lost_mass)} published launches lost their mass: "
            + _summarize(list(map(_describe, lost_mass)))
        )
    if drops:
        problems.append(
            f"{len(drops)} published launches have large mass drops: "
            + _summarize(drops)
        )
    if problems:
        raise PublishedLaunchesLostError(
            ". ".join(problems) + " (has part of a Wikipedia table stopped parsing?)"
        )
