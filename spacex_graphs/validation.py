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

# The errors live in errors.py with the other DataErrors; they are re-exported
# here, next to the checks that raise them, for existing callers
from spacex_graphs.errors import EmptyPageError as EmptyPageError
from spacex_graphs.errors import ImplausibleMassError as ImplausibleMassError
from spacex_graphs.errors import MissingYearsError as MissingYearsError
from spacex_graphs.errors import NoRecentLaunchesError as NoRecentLaunchesError
from spacex_graphs.errors import OutcomeIntegrityError as OutcomeIntegrityError
from spacex_graphs.errors import (
    PublishedLaunchesLostError as PublishedLaunchesLostError,
)
from spacex_graphs.parsing import LaunchRecord


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
    r"^(?:failure|failed|launch failure|partial success|partial failure"
    r"|precluded|unsuccessful)\b"
)
_FAILED_QUALIFIER = re.compile(r"\b(?:failed|failure|partial|unsuccessful|lost)\b")


def outcome_kind(outcome: str) -> OutcomeKind:
    """Classifies an outcome for integrity checks and the transform.

    A launch whose payloads have their own outcomes is listed with them joined
    by "; " (see parsing.parse_launch_page), and its first, primary payload's
    outcome decides: "Success; Partial failure" (CRS-1) is a success. Text
    after a semicolon counts as a join only if every part is an outcome
    itself; otherwise it qualifies the outcome, so "Success; payload lost" is
    a failure and "Success; <anything else>" is unrecognized rather than
    silently read as a success.
    """
    parts = [_single_outcome_kind(part) for part in outcome.split(";")]
    if OutcomeKind.UNRECOGNIZED not in parts[1:]:
        return parts[0]
    whole = _single_outcome_kind(outcome)
    return whole if whole is OutcomeKind.FAILURE else OutcomeKind.UNRECOGNIZED


def _single_outcome_kind(outcome: str) -> OutcomeKind:
    outcome = " ".join(outcome.casefold().split())
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


def _unique_names(
    published: Sequence[PublishedLaunch], current: Sequence[PublishedLaunch]
) -> set[str]:
    """Payload names listed exactly once on both sides, which identify a launch."""
    old_names = Counter(launch.payload for launch in published)
    new_names = Counter(launch.payload for launch in current)
    return {name for name, count in old_names.items() if count == new_names[name] == 1}


def _match_launches(
    published: Sequence[PublishedLaunch], current: Sequence[PublishedLaunch]
) -> tuple[list[PublishedLaunch], list[PublishedLaunch]]:
    """Finds which launches on one date and vehicle lost their mass or are missing.

    Returns (lost their mass, missing). A payload named once on both sides is
    matched by name, so one payload's mass going unknown can't be masked by
    another's becoming known. The rest are matched by count: as many must
    still be listed, and as many of those with a known mass must still have one.
    """
    unique = _unique_names(published, current)
    by_name = {launch.payload: launch for launch in current if launch.payload in unique}
    lost = [
        launch
        for launch in published
        if launch.payload in unique
        and launch.mass is not None
        and by_name[launch.payload].mass is None
    ]
    others = [launch for launch in published if launch.payload not in unique]
    candidates = [launch for launch in current if launch.payload not in unique]
    found = others[: len(candidates)]
    missing = others[len(candidates) :]
    known = [launch for launch in found if launch.mass is not None]
    still_known = sum(launch.mass is not None for launch in candidates)
    lost.extend(known[still_known:])
    return lost, missing


def _pair_known_masses(
    published: Sequence[PublishedLaunch], current: Sequence[PublishedLaunch]
) -> Iterator[tuple[PublishedLaunch, int, int]]:
    """Pairs known masses for launches on one date and vehicle."""
    unique = _unique_names(published, current)
    exact = {
        launch.payload: launch.mass
        for launch in current
        if launch.mass is not None and launch.payload in unique
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
    one. No known mass may be lost: a payload named once on the date is
    matched by name, the rest by count. Large relative and absolute drops in a
    known mass can also indicate parser drift instead of a Wikipedia correction.
    published is empty on a first run.
    """
    if not published:
        return

    current: dict[tuple[datetime.date, str], list[PublishedLaunch]] = defaultdict(list)
    for record in records:
        date = record.launch_datetime.date()
        current[(date, record.vehicle)].append(
            PublishedLaunch(date, record.vehicle, record.payload, record.payload_mass)
        )

    published_by_day: dict[tuple[datetime.date, str], list[PublishedLaunch]] = (
        defaultdict(list)
    )
    for launch in published:
        published_by_day[(launch.date, launch.vehicle)].append(launch)

    missing: list[PublishedLaunch] = []
    lost_mass: list[PublishedLaunch] = []
    drops: list[str] = []
    for key, launches in published_by_day.items():
        lost, gone = _match_launches(launches, current[key])
        lost_mass.extend(lost)
        missing.extend(gone)
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
