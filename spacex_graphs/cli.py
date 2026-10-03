"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import datetime
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt

from spacex_graphs import cache, output, plotting, transform, validation
from spacex_graphs.config import CACHE_DIR, OUTPUT_DIR, WIKIPEDIA_PAGES
from spacex_graphs.parsing import LaunchRecord, parse_launch_page

logger = logging.getLogger(__name__)


# Errors that mean the data can't be trusted: the run fails rather than
# publishing graphs built from it
DATA_ERRORS = (
    validation.EmptyPageError,
    validation.MissingYearsError,
    validation.LaunchCountDropError,
    cache.FetchError,
    cache.StaleCacheError,
)

# matplotlib backends that render to files only; with one of these, showing
# the graphs on screen would silently do nothing
_FILE_ONLY_BACKENDS = {"agg", "cairo", "pdf", "pgf", "ps", "svg", "template"}


def _fetch_and_parse(url: str) -> list[LaunchRecord]:
    """Fetches one page (using the HTTP cache) and parses its launch records."""
    # Parsing inside the fetch lets the cache refuse a download with no
    # launches in it, rather than replacing a good cached copy
    records, _ = cache.fetch_with_cache(
        url, lambda content: parse_launch_page(url, content)
    )
    return records


def load_launch_records(today: datetime.date) -> list[LaunchRecord]:
    """Fetches and parses every Wikipedia page, then checks the result.

    Raises one of the validation errors when the launches can't be trusted:
    a page with no launches, a past year with none, or a year with far fewer
    than were last published. Launches listed twice or dated after today are
    dropped with a warning.
    """
    logger.info("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_fetch_and_parse, WIKIPEDIA_PAGES))

    validation.check_pages_not_empty(
        dict(zip(WIKIPEDIA_PAGES.values(), results, strict=True))
    )

    records, duplicates = validation.drop_duplicate_launches(
        [record for page_records in results for record in page_records]
    )
    if duplicates:
        logger.warning("Dropped %d launches listed on more than one page", duplicates)

    records, future = validation.drop_future_launches(records, today)
    if future:
        logger.warning("Dropped %d launches dated after today", future)

    validation.check_year_coverage(records, today)
    validation.check_launch_counts(records, output.published_launch_counts())
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


def _configure_logging(quiet: bool) -> None:
    """Sends progress to stdout and warnings and errors to stderr."""
    progress = logging.StreamHandler(sys.stdout)
    progress.addFilter(lambda record: record.levelno < logging.WARNING)
    problems = logging.StreamHandler(sys.stderr)
    problems.setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.WARNING if quiet else logging.INFO,
        format="%(message)s",
        handlers=[progress, problems],
    )


def main() -> None:
    """Parses command-line arguments, configures logging, and runs."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch SpaceX launch lists from Wikipedia and graph the payload "
            "mass launched each year. Without --output the graphs are shown "
            "on screen; with it they are saved, with a CSV of every launch."
        ),
        epilog=(
            f"Files are written to {OUTPUT_DIR}/ and downloaded pages cached in "
            f"{CACHE_DIR}/, both relative to the current directory. With --output, "
            "nothing is regenerated when neither the launch data nor the date "
            "has changed since the last successful run."
        ),
    )
    parser.add_argument(
        "--output",
        action="store_true",
        help=f"save the graphs as SVG files and the launches as CSV in {OUTPUT_DIR}/",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="only print warnings and errors"
    )
    args = parser.parse_args()
    if not args.output and plt.get_backend().lower() in _FILE_ONLY_BACKENDS:
        parser.error(
            "there is no display to show the graphs on; pass --output to save them"
        )
    _configure_logging(args.quiet)
    try:
        run(args.output)
    except DATA_ERRORS as error:
        logger.error("ERROR: %s", error)
        sys.exit(1)
