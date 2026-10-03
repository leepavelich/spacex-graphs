"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import datetime
import hashlib
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path

import matplotlib.pyplot as plt

from spacex_graphs import cache, output, plotting, transform, validation
from spacex_graphs.config import CACHE_DIR, OUTPUT_DIR, WIKIPEDIA_PAGES, Page
from spacex_graphs.errors import DataError
from spacex_graphs.parsing import LaunchRecord, parse_launch_page

logger = logging.getLogger(__name__)


# matplotlib backends that render to files only; with one of these, showing
# the graphs on screen would silently do nothing
_FILE_ONLY_BACKENDS = {"agg", "cairo", "pdf", "pgf", "ps", "svg", "template"}


def _fetch_and_parse(page: Page, cache_dir: str) -> list[LaunchRecord]:
    """Fetches one page (using the HTTP cache) and parses its launch records."""
    # Parsing inside the fetch lets the cache refuse a download with no
    # launches in it, rather than replacing a good cached copy
    records, _ = cache.fetch_with_cache(
        page.url,
        lambda content: parse_launch_page(page.layout, content),
        cache_dir=cache_dir,
        name=page.name,
    )
    return records


# Libraries whose versions can change what the outputs look like
_RENDERING_LIBRARIES = ("beautifulsoup4", "matplotlib", "numpy", "pandas")


def code_version() -> str:
    """Fingerprints the code and libraries that produce the outputs.

    It goes into the change-detection hash, so a code change or a dependency
    update regenerates the outputs on its next run instead of waiting for
    the data or the date to change.
    """
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    for library in _RENDERING_LIBRARIES:
        digest.update(f"{library}=={metadata.version(library)}".encode())
    return digest.hexdigest()[:16]


def load_launch_records(
    today: datetime.date, *, cache_dir: str, output_dir: str
) -> list[LaunchRecord]:
    """Fetches and parses every Wikipedia page, then checks the result.

    Raises one of the validation errors when the launches can't be trusted:
    a page with no launches, a past year with none, or a year with far fewer
    than were last published. Launches listed twice or dated after today are
    dropped with a warning. Pages are cached in cache_dir, and the published
    CSV in output_dir is the baseline for the launch counts.
    """
    logger.info("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(
                lambda page: _fetch_and_parse(page, cache_dir), WIKIPEDIA_PAGES
            )
        )

    validation.check_pages_not_empty(
        {
            page.name: page_records
            for page, page_records in zip(WIKIPEDIA_PAGES, results, strict=True)
        }
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
    validation.check_recent_launch(records, today)
    validation.check_published_launches(records, output.published_launches(output_dir))
    return records


def run(
    save_output: bool,
    today: datetime.date | None = None,
    *,
    output_dir: str = OUTPUT_DIR,
    cache_dir: str = CACHE_DIR,
) -> None:
    """Generates the graphs, saving them as SVGs or displaying them on screen.

    today defaults to the current UTC date, and the directories to the
    config defaults; tests pass their own.
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    # Launch times are UTC, so "today" (where the current year's line ends)
    # is the UTC date too; computed once here so the transforms stay pure
    if today is None:
        today = datetime.datetime.now(datetime.UTC).date()
    records = load_launch_records(today, cache_dir=cache_dir, output_dir=output_dir)
    version = code_version()
    latest = max(record.launch_datetime for record in records)
    _summarize(f"Parsed {len(records)} launches; the latest is from {latest:%Y-%m-%d}.")

    # When saving, skip regeneration if neither the data nor the date changed
    # since the last successful run and every output still exists. Parsing is
    # cheap, so this always parses rather than trusting HTTP 304s, which can't
    # see a new day.
    if (
        save_output
        and not output.missing_outputs(output_dir)
        and not cache.has_data_changed(
            records, today, cache_dir=cache_dir, code_version=version
        )
    ):
        logger.info("No changes detected in launch data - skipping graph regeneration")
        _summarize("Nothing changed since the last run, so the outputs were kept.")
        return

    df = transform.build_dataframe(records)
    caption = transform.chart_caption(df)
    # Each graph, keyed by the SVG file it is saved to
    figures = {
        output.BY_YEAR_SVG: plotting.plot_payload_mass_to_orbit_by_year(
            transform.payload_mass_by_year_orbit(df),
            current_year=today.year,
            caption=caption,
        ),
        output.CUMULATIVE_SVG: plotting.plot_cumulative_payload_mass_to_orbit(
            transform.build_cumulative_frame(df, today), today, caption=caption
        ),
    }

    if save_output:
        output.save_plots(figures, output_dir=output_dir)
        output.save_launches_csv(df, output_dir=output_dir)
        cache.save_data_hash(records, today, cache_dir=cache_dir, code_version=version)
        logger.info("Graphs updated successfully")
        _summarize("Regenerated the graphs and CSV.")
    else:
        plt.show()


def _in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _summarize(line: str) -> None:
    """Adds a line to the GitHub Actions job summary, when running there."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"{line}\n\n")


class _AnnotationFormatter(logging.Formatter):
    """Formats warnings and errors as GitHub Actions annotations, which show on
    the run's page instead of only in the log (so a run that falls back to
    cached pages is visibly yellow, not silently green)."""

    def format(self, record: logging.LogRecord) -> str:
        level = "error" if record.levelno >= logging.ERROR else "warning"
        return f"::{level}::{record.getMessage().strip()}"


def _configure_logging(quiet: bool) -> None:
    """Sends progress to stdout and warnings and errors to stderr.

    In GitHub Actions, warnings and errors are written as annotations.
    """
    progress = logging.StreamHandler(sys.stdout)
    progress.addFilter(lambda record: record.levelno < logging.WARNING)
    problems = logging.StreamHandler(sys.stderr)
    problems.setLevel(logging.WARNING)
    if _in_github_actions():
        problems.setFormatter(_AnnotationFormatter())
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
    except DataError as error:
        logger.error("ERROR: %s", error)
        _summarize(f"**Failed:** {error}")
        sys.exit(1)
    except OSError as error:
        # Usually a permissions problem with the output or cache directory
        logger.error("ERROR: could not write the outputs or cache: %s", error)
        sys.exit(1)
