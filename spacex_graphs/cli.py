"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import datetime
import hashlib
import logging
import os
import re
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path

import matplotlib
from matplotlib.figure import Figure

from spacex_graphs import cache, output, plotting, transform, validation
from spacex_graphs.config import (
    CACHE_DIR,
    MAX_FETCH_WORKERS,
    OUTPUT_DIR,
    WIKIPEDIA_PAGES,
    Page,
)
from spacex_graphs.errors import DataError
from spacex_graphs.parsing import LaunchRecord, parse_launch_page

logger = logging.getLogger(__name__)


# matplotlib backends that render to files only; with one of these, showing
# the graphs on screen would silently do nothing
_FILE_ONLY_BACKENDS = frozenset({"agg", "cairo", "pdf", "pgf", "ps", "svg", "template"})


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
_RENDERING_LIBRARIES = (
    "beautifulsoup4",
    "fonttools",
    "kiwisolver",
    "matplotlib",
    "numpy",
    "pandas",
    "pillow",
    "soupsieve",
)


def code_version() -> str:
    """Fingerprints the code and libraries that produce the outputs.

    It goes into the change-detection hash, so a code change or a dependency
    update regenerates the outputs on its next run instead of waiting for
    the data or the date to change.
    """
    digest = hashlib.sha256()
    package = Path(__file__).parent
    for source in sorted(package.rglob("*.py")):
        digest.update(source.relative_to(package).as_posix().encode())
        digest.update(source.read_bytes())
    for library in _RENDERING_LIBRARIES:
        digest.update(f"{library}=={metadata.version(library)}".encode())
    return digest.hexdigest()[:16]


def load_launch_records(
    today: datetime.date, *, cache_dir: str, output_dir: str
) -> list[LaunchRecord]:
    """Fetches and parses every Wikipedia page, then checks the result.

    Drops future, unlaunched, and duplicate entries before checking coverage,
    data integrity, and that no published launches or known masses were lost.
    """
    logger.info("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as executor:
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

    records, future = validation.drop_future_launches(
        [record for page_records in results for record in page_records], today
    )
    if future:
        logger.warning("Dropped %d launches dated after today", future)
    records, unlaunched = validation.drop_unlaunched(records)
    if unlaunched:
        logger.warning("Dropped %d launches that have not taken place", unlaunched)
    records, duplicates = validation.drop_duplicate_launches(records)
    if duplicates:
        logger.warning("Dropped %d launches listed on more than one page", duplicates)

    validation.check_recent_launch(records, today)
    validation.check_year_coverage(records, today)
    validation.check_payload_masses(records)
    validation.check_outcomes(records)
    validation.check_published_launches(records, output.published_launches(output_dir))
    return records


def run(
    save_output: bool,
    today: datetime.date | None = None,
    *,
    output_dir: str = OUTPUT_DIR,
    cache_dir: str = CACHE_DIR,
    summary_path: str | None = None,
) -> None:
    """Generates the graphs, saving them as SVGs or displaying them on screen.

    today defaults to the current UTC date, and the directories to the
    config defaults; tests pass their own.
    """
    if save_output:
        os.makedirs(output_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    # Launch times are UTC, so "today" (where the current year's line ends)
    # is the UTC date too; computed once here so the transforms stay pure
    if today is None:
        today = datetime.datetime.now(datetime.UTC).date()
    records = load_launch_records(today, cache_dir=cache_dir, output_dir=output_dir)
    version = code_version() if save_output else ""
    latest = max(record.launch_datetime for record in records)
    _summarize(
        summary_path,
        f"Parsed {len(records)} launches; the latest is from {latest:%Y-%m-%d}.",
    )

    # When saving, skip regeneration if neither the data nor the date changed
    # since the last successful run and every output still exists. Parsing is
    # cheap, so this always parses rather than trusting HTTP 304s, which can't
    # see a new day.
    if (
        save_output
        and not output.missing_outputs(output_dir)
        and not output.has_data_changed(
            records, today, cache_dir=cache_dir, code_version=version
        )
    ):
        logger.info("No changes detected in launch data - skipping graph regeneration")
        _summarize(
            summary_path,
            "Nothing changed since the last run, so the outputs were kept.",
        )
        return

    df = transform.build_dataframe(records)
    caption = transform.chart_caption(df)
    by_year = transform.payload_mass_by_year_orbit(df)
    cumulative = transform.build_cumulative_frame(df, today)
    # Each graph, keyed by the SVG file it is saved to. They are plain Figure
    # objects that pyplot never sees, so there is nothing to close afterwards.
    figures = {
        output.BY_YEAR_SVG: plotting.plot_payload_mass_to_orbit_by_year(
            by_year, current_year=today.year, caption=caption
        ),
        output.CUMULATIVE_SVG: plotting.plot_cumulative_payload_mass_to_orbit(
            cumulative, today, caption=caption
        ),
    }

    if save_output:
        output.save_plots(
            figures,
            output_dir=output_dir,
            descriptions={
                output.BY_YEAR_SVG: transform.by_year_summary(by_year, today.year),
                output.CUMULATIVE_SVG: transform.cumulative_summary(cumulative, today),
            },
        )
        output.save_launches_csv(df, output_dir=output_dir)
        output.save_data_hash(records, today, cache_dir=cache_dir, code_version=version)
        logger.info("Graphs updated successfully")
        _summarize(summary_path, "Regenerated the graphs and CSV.")
    else:
        _show(figures.values())


def _show(figures: Iterable[Figure]) -> None:
    """Shows the figures in windows until they are closed.

    pyplot is imported only here, so saving never starts a GUI backend.
    """
    import matplotlib.pyplot as plt

    for figure in figures:
        # Hands the figure to pyplot, which gives it a window
        plt.figure(figure)
    plt.show()


def _in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _summarize(summary_path: str | None, line: str) -> None:
    """Appends to the GitHub Actions job summary if a path was supplied."""
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"{line}\n\n")


class _AnnotationFormatter(logging.Formatter):
    """Formats warnings and errors as GitHub Actions annotations, which show on
    the run's page instead of only in the log (so a run that falls back to
    cached pages is visibly yellow, not silently green)."""

    def format(self, record: logging.LogRecord) -> str:
        level = "error" if record.levelno >= logging.ERROR else "warning"
        message = record.getMessage().strip(" \t")
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        return f"::{level}::{message}"


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
    if not args.output and matplotlib.get_backend().lower() in _FILE_ONLY_BACKENDS:
        parser.error(
            "there is no display to show the graphs on; pass --output to save them"
        )
    _configure_logging(args.quiet)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    try:
        run(args.output, summary_path=summary_path)
    except (DataError, OSError) as error:
        message = (
            f"file system error: {error}" if isinstance(error, OSError) else str(error)
        )
        logger.error("ERROR: %s", message)
        # Make the fence longer than any run of tildes in the error text.
        longest = max(map(len, re.findall(r"~+", message)), default=0)
        fence = "~" * max(3, longest + 1)
        try:
            _summarize(summary_path, f"**Failed**\n\n{fence}\n{message}\n{fence}")
        except OSError as summary_error:
            logger.warning("Could not write job summary: %s", summary_error)
        sys.exit(1)
