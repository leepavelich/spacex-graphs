# AGENTS.md

Guidance for coding agents working in this repository. It covers only what the code can't tell you: design rules and the reasons for them, Wikipedia quirks, and how changes land. Read the code for layout, dependencies, and commands.

## Design rules

- Keep the module layering `config` → `cache` → `parsing` → `validation` → `transform` → `plotting` → `output` → `cli`: each module imports only modules to its left, and I/O happens only in `cache`, `output`, and `cli`. Nothing runs at import time. This keeps parsing and transforms pure and testable without mocks.
- Parsing and transform functions take everything they need as arguments, including the date: `cli.run` computes today's UTC date once and passes it down. Launch times on Wikipedia are UTC, so "today" is too.
- Identical data must produce byte-identical SVGs, which is why they are saved with no timestamp and a fixed `svg.hashsalt`. The scheduled workflow commits only files that changed, so any nondeterminism becomes a noisy daily commit.
- The change-detection hash includes today's date on purpose: the cumulative chart's current-year line extends to today, so the graphs legitimately change once a day. It also includes `cli.code_version()`, a fingerprint of the package source and rendering libraries, so a code change or dependency update regenerates the outputs without waiting a day.
- The program writes only to `outputs/` and `.cache/`.
- Keep SVG filenames and orbit category labels stable. The README embeds the SVGs by filename and the scheduled workflow commits `outputs/*.svg` and `outputs/*.csv`. Chart titles may change.
- Leave committing `outputs/` to the scheduled workflow. Font metrics differ by platform, so an SVG rendered on macOS differs byte for byte from CI's even for identical data.
- `config.ORBIT_CATEGORIES` is the one list of orbit categories. A new `ORBIT_MAPPING` value must be in it and get a color in `plotting.py`; the tests check both, and the bar chart refuses a category it can't color rather than dropping its mass.
- Records keep what Wikipedia reports: the outcome text, and the mass or `None` when there isn't one. Whether a launch's mass counts in the graphs is decided only by `transform.launch_succeeded`, so keep that policy out of the parsers.
- Data that can't be trusted raises one of the errors in `cli.DATA_ERRORS`, which exit with code 1 and a one-line message. Put new completeness checks in `validation.py` as pure functions and add their errors there, rather than logging a warning, so the daily job goes red instead of publishing.
- The committed `outputs/spacex_launches.csv` is also the baseline for `validation.check_launch_counts`: a year with more than `MAX_LAUNCH_COUNT_DROP` fewer launches than it fails the run. If Wikipedia really does remove launches, regenerate the outputs deliberately rather than raising the limit.
- In the cumulative chart, the current year is red and years before `HIGHLIGHT_FROM_YEAR` (2020) are grey on purpose: their payload mass is tiny next to recent years.
- Chart titles say "launched", not "to orbit", because the totals include suborbital (Transatmospheric) payloads.

## Wikipedia quirks

- Falcon and Starship tables use different column layouts, so `parsing.py` has a row parser for each. Planned launches sit in tables with fewer columns and must stay excluded.
- A page that parses to zero launches is a fatal error with exit code 1. That almost always means Wikipedia changed a table layout; keep it fatal, or the daily job would publish graphs with that page's launches missing.
- A payload's mass is the figure attached to "kg", or to "lb" converted when there is no kg figure. Other numbers in such a cell, like footnotes, years, or the "500-2" in "CAS500-2", are ignored. A bare number is used only when the cell has no unit at all. "Unknown", "Classified", and "—" mean no mass (`None`), not 0.
- Each year Wikipedia moves the previous year's launches out of the current Falcon list into a page of their own. When that happens, add the new page to `WIKIPEDIA_PAGES`. Until then, the run fails with `MissingYearsError`, because every past year since `FIRST_CONTINUOUS_YEAR` must have launches.
- When Wikipedia can't be reached, cached pages are used only if they were confirmed current within `STALE_CACHE_LIMIT`; past that the run fails. Keep it failing rather than raising the limit to get a green run: frozen data that looks current is worse than a red job.
- Keep the descriptive User-Agent and request timeout, which Wikimedia's User-Agent policy asks for, and keep fetch concurrency at its current level.

## Dependencies

- Edit `requirements.in` (runtime) or `requirements-dev.in` (tools), then run `scripts/update-locks.sh` to regenerate both locks; it needs uv, which `requirements-dev.txt` installs. The `requirements*.txt` locks carry hashes that pip enforces, so hand edits break installs, and CI fails when a lock doesn't match its `.in` file.
- Python 3.11 is the target for CI and Docker.

## Commits and pull requests

- Use Conventional Commits, such as `fix(parsing): …` or `ci: …`. The scheduled workflow's own commits are `chore(outputs): update graphs by scheduler`.
- To bring a PR branch up to date with `main`, rebase onto `main` and force-push with `--force-with-lease`. Don't merge `main` into the branch, including through `gh pr update-branch`'s default merge mode, so history stays linear.
- When a change alters the graphs, attach before-and-after renders to the PR, and update the README if behavior or outputs change.
