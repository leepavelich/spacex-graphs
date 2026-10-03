# SpaceX Mass-to-Orbit Graphs

This project contains a Python script that fetches data about SpaceX launches from Wikipedia, analyzes the payload mass launched to different destinations over the years, and provides a cumulative sum of the payload mass launched. Suborbital flights, such as Starship test flights carrying Starlink simulators, count as launched mass under the Transatmospheric category.

The scraper reads Wikipedia's year-specific Falcon launch archives as well as the current Falcon and Starship launch pages.

## Payload Mass Launched by Year and Destination

![Payload Mass Launched by Year and Destination](outputs/payload_mass_to_orbit_by_year.svg)

## Cumulative Payload Mass Launched (2017 onwards)

![Cumulative Payload Mass Launched](outputs/cumulative_payload_mass_to_orbit.svg)

## Running with Docker (recommended)

Docker installs the pinned dependencies for you. You need Docker with Docker Compose.

```bash
docker compose run --rm graphs
```

This fetches the Wikipedia pages and saves the graphs and CSV to `outputs/`. A container has no display, so Docker always saves rather than showing the graphs on screen. Downloaded pages are kept in a Docker volume, so later runs only re-download pages that changed.

## Running locally

You need Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Show the graphs on screen
python3 graphs.py

# Save the graphs and CSV to outputs/
python3 graphs.py --output
```

Add `-q` to print only warnings and errors.

## Outputs

With `--output`, the script writes three files to `outputs/`:

- `payload_mass_to_orbit_by_year.svg`: a stacked bar chart of payload mass launched to each destination by year
- `cumulative_payload_mass_to_orbit.svg`: a line chart of cumulative payload mass launched, from 2017 onwards
- `spacex_launches.csv`: every parsed launch, with its raw and categorized orbit

Downloaded pages are cached in `.cache/`, and Wikipedia is asked only for pages that changed. If neither the launch data nor the date has changed since the last successful run, the script skips regenerating the outputs.

A GitHub Actions workflow runs the script daily and commits any changed outputs, which keeps the graphs above current.

## Project Structure

`graphs.py` is the entry point; the implementation lives in the `spacex_graphs/` package:

- `config.py` — Wikipedia URLs, HTTP settings, orbit-category mapping
- `cache.py` — HTTP caching (ETag/Last-Modified) and change detection
- `parsing.py` — parses launch records from Wikipedia's HTML tables
- `transform.py` — orbit categorization and DataFrame preparation
- `plotting.py` — builds the matplotlib figures
- `output.py` — writes the SVG and CSV files
- `cli.py` — command-line interface and orchestration

## Development

Install the development tools, which include the runtime dependencies:

```bash
pip install -r requirements-dev.txt
```

CI runs these checks on every pull request:

```bash
ruff check .
ruff format --check .
mypy
python3 -m unittest discover -s tests
```

Dependencies are declared in `requirements.in` and `requirements-dev.in` and locked, with hashes, in the matching `.txt` files. To change a dependency, edit the `.in` file and rerun the command shown at the top of its lock file.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or create an issue if you have suggestions for improvements.
