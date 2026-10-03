"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import datetime
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt

from spacex_graphs import cache, output, plotting, transform
from spacex_graphs.config import (
    CACHE_DIR,
    FIRST_CONTINUOUS_YEAR,
    OUTPUT_DIR,
    WIKIPEDIA_PAGES,
)
from spacex_graphs.parsing import (
    LaunchRecord,
    drop_duplicate_launches,
    parse_launch_page,
)

logger = logging.getLogger(__name__)


class EmptyPageError(RuntimeError):
    """Raised when a Wikipedia page yields no launch records."""


class MissingYearsError(RuntimeError):
    """Raised when past years that should have launches have none."""


# Errors that mean the data can't be trusted: the run fails rather than
# publishing graphs built from it
DATA_ERRORS = (EmptyPageError, MissingYearsError, cache.StaleCacheError)


def _fetch_and_parse(url: str) -> list[LaunchRecord]:
    """Fetches one page (using the HTTP cache) and parses its launch records."""
    content, _ = cache.fetch_with_cache(url)
    return parse_launch_page(url, content)


def load_launch_records(today: datetime.date) -> list[LaunchRecord]:
    """Fetches, parses, and checks the launches from all Wikipedia pages.

    Raises EmptyPageError if any page parses to zero records, which almost
    always means Wikipedia changed the table layout, and MissingYearsError if
    a past year has no launches at all, which means a page is missing from
    WIKIPEDIA_PAGES. Either would otherwise publish graphs with launches
    silently missing. Launches listed twice or dated after today are dropped.
    """
    logger.info("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_fetch_and_parse, WIKIPEDIA_PAGES))

    empty_pages = [
        WIKIPEDIA_PAGES[url]
        for url, page_records in zip(WIKIPEDIA_PAGES, results, strict=True)
        if not page_records
    ]
    if empty_pages:
        raise EmptyPageError(
            "no launches parsed from: "
            + ", ".join(empty_pages)
            + " (has the Wikipedia table layout changed?)"
        )

    records, duplicates = drop_duplicate_launches(
        [record for page_records in results for record in page_records]
    )
    if duplicates:
        logger.warning("Dropped %d launches listed on more than one page", duplicates)

    future = [r for r in records if r.launch_datetime.date() > today]
    if future:
        logger.warning("Dropped %d launches dated after today", len(future))
        records = [r for r in records if r.launch_datetime.date() <= today]

    years = {record.year for record in records}
    missing = [y for y in range(FIRST_CONTINUOUS_YEAR, today.year) if y not in years]
    if missing:
        raise MissingYearsError(
            "no launches found for "
            + ", ".join(map(str, missing))
            + " (has Wikipedia moved them to a page not in WIKIPEDIA_PAGES?)"
        )

    return records


def run(save_output: bool, today: datetime.date | None = None) -> None:
    """Generates the graphs, saving them as SVGs or displaying them on screen.

    today defaults to the current UTC date; tests pass a fixed one.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    # Launch times are UTC, so "today" (where the current year's line ends)
    # is the UTC date too; computed once here so the transforms stay pure
    if today is None:
        today = datetime.datetime.now(datetime.UTC).date()
    records = load_launch_records(today)

    # When saving, skip regeneration if neither the data nor the date changed
    # since the last successful run and every output still exists. Parsing is
    # cheap, so this always parses rather than trusting HTTP 304s, which can't
    # see a new day.
    if (
        save_output
        and not output.missing_outputs()
        and not cache.has_data_changed(records, today)
    ):
        logger.info("No changes detected in launch data - skipping graph regeneration")
        cache.write_last_run_date(today)
        return

    df = transform.build_dataframe(records)
    fig_by_year = plotting.plot_payload_mass_to_orbit_by_year(
        transform.payload_mass_by_year_orbit(df)
    )
    fig_cumulative = plotting.plot_cumulative_payload_mass_to_orbit(
        transform.build_cumulative_frame(df, today), today
    )

    if save_output:
        output.save_plots(fig_by_year, fig_cumulative)
        output.save_launches_csv(df)
        cache.save_data_hash(records, today)
        cache.write_last_run_date(today)
        logger.info("Graphs updated successfully")
    else:
        plt.show()


def main() -> None:
    """Parses command-line arguments, configures logging, and runs."""
    parser = argparse.ArgumentParser(
        description="Generate and optionally output plots as SVG."
    )
    parser.add_argument(
        "--output", action="store_true", help="Output the plots as SVG files"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Only print warnings and errors"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )
    try:
        run(args.output)
    except DATA_ERRORS as error:
        logger.error("ERROR: %s", error)
        sys.exit(1)
