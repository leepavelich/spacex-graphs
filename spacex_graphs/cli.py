"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import datetime
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt

from spacex_graphs import cache, output, plotting, transform
from spacex_graphs.config import CACHE_DIR, OUTPUT_DIR, WIKIPEDIA_PAGES
from spacex_graphs.parsing import parse_launch_page


class EmptyPageError(RuntimeError):
    """Raised when a Wikipedia page yields no launch records."""


def _fetch_and_parse(url):
    """Fetches one page (using the HTTP cache) and parses its launch records."""
    content, _ = cache.fetch_with_cache(url)
    return parse_launch_page(url, content)


def load_launch_records():
    """Fetches and parses all Wikipedia pages concurrently.

    Returns the combined records. Raises EmptyPageError if any page
    parses to zero records, which almost always means Wikipedia changed the
    table layout; continuing would publish graphs with that page's launches
    silently missing.
    """
    print("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_fetch_and_parse, WIKIPEDIA_PAGES))

    empty_pages = [
        WIKIPEDIA_PAGES[url]
        for url, page_records in zip(WIKIPEDIA_PAGES, results)
        if not page_records
    ]
    if empty_pages:
        raise EmptyPageError(
            "no launches parsed from: "
            + ", ".join(empty_pages)
            + " (has the Wikipedia table layout changed?)"
        )

    return [record for page_records in results for record in page_records]


def run(save_output):
    """Generates the graphs, saving them as SVGs or displaying them on screen."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    # Launch times are UTC, so "today" (where the current year's line ends)
    # is the UTC date too; computed once here so the transforms stay pure
    today = datetime.datetime.now(datetime.timezone.utc).date()
    records = load_launch_records()

    # When saving, skip regeneration if neither the data nor the date changed
    # since the last successful run. Parsing is cheap, so this always parses
    # rather than trusting HTTP 304s, which can't see a new day.
    if save_output and not cache.has_data_changed(records, today):
        print("No changes detected in launch data - skipping graph regeneration")
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
        print("Graphs updated successfully")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Generate and optionally output plots as SVG."
    )
    parser.add_argument(
        "--output", action="store_true", help="Output the plots as SVG files"
    )
    args = parser.parse_args()
    try:
        run(args.output)
    except EmptyPageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
