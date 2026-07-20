"""Command-line entry point: fetch, transform, plot, and save/show the graphs."""

import argparse
import os
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt

from spacex_graphs import cache, output, plotting, transform
from spacex_graphs.config import CACHE_DIR, OUTPUT_DIR, WIKIPEDIA_PAGES
from spacex_graphs.parsing import parse_launch_page


def _fetch_and_parse(url):
    """Fetches one page (using the HTTP cache) and parses its launch records."""
    content, not_modified = cache.fetch_with_cache(url)
    return parse_launch_page(url, content), not_modified


def load_launch_records():
    """Fetches and parses all Wikipedia pages concurrently.

    Returns (records, all_pages_unchanged).
    """
    print("Fetching Wikipedia pages:")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_fetch_and_parse, WIKIPEDIA_PAGES))

    records = [record for page_records, _ in results for record in page_records]
    all_unchanged = all(not_modified for _, not_modified in results)
    return records, all_unchanged


def run(save_output):
    """Generates the graphs, saving them as SVGs or displaying them on screen."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    records, all_unchanged = load_launch_records()

    # When saving, skip regeneration if nothing changed since the last run
    if save_output:
        if all_unchanged and cache.has_previous_run():
            print("All pages cached and data unchanged - skipping processing")
            return
        if not cache.has_data_changed(records):
            print("No changes detected in launch data - skipping graph regeneration")
            # Still update the date file so we know we checked today
            cache.write_last_run_date()
            return

    df = transform.build_dataframe(records)
    fig_by_year = plotting.plot_payload_mass_to_orbit_by_year(
        transform.payload_mass_by_year_orbit(df)
    )
    fig_cumulative = plotting.plot_cumulative_payload_mass_to_orbit(
        transform.build_cumulative_frame(df)
    )

    if save_output:
        output.save_plots(fig_by_year, fig_cumulative)
        output.save_launches_csv(records)
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
    run(args.output)
