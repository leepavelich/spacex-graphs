# AGENTS.md

Guidance for coding agents working in this repository. It covers only what the code can't tell you: design rules and the reasons for them, Wikipedia quirks, and how changes land. Read the code for layout, dependencies, and commands.

## Design rules

- Keep the module layering `config` → `cache` → `parsing` → `transform` → `plotting` → `output` → `cli`: each module imports only modules to its left, and I/O happens only in `cache`, `output`, and `cli`. Nothing runs at import time. This keeps parsing and transforms pure and testable without mocks.
- Parsing and transform functions take everything they need as arguments, including the date: `cli.run` computes today's UTC date once and passes it down. Launch times on Wikipedia are UTC, so "today" is too.
- Identical data must produce byte-identical SVGs, which is why they are saved with no timestamp and a fixed `svg.hashsalt`. The scheduled workflow commits only files that changed, so any nondeterminism becomes a noisy daily commit.
- The change-detection hash includes today's date on purpose: the cumulative chart's current-year line extends to today, so the graphs legitimately change once a day.
- The program writes only to `outputs/` and `.cache/`.
- Keep SVG filenames and orbit category labels stable. The README embeds the SVGs by filename and the scheduled workflow commits `outputs/*.svg` and `outputs/*.csv`. Chart titles may change.
- In the cumulative chart, the current year is red and years before `HIGHLIGHT_FROM_YEAR` (2020) are grey on purpose: their payload mass is tiny next to recent years.
- Chart titles say "launched", not "to orbit", because the totals include suborbital (Transatmospheric) payloads.

## Wikipedia quirks

- Falcon and Starship tables use different column layouts, so `parsing.py` has a row parser for each. Planned launches sit in tables with fewer columns and must stay excluded.
- A page that parses to zero launches is a fatal error with exit code 1. That almost always means Wikipedia changed a table layout; keep it fatal, or the daily job would publish graphs with that page's launches missing.
- A payload's mass is the number attached to "kg". Other numbers in the cell, such as footnotes, years, or satellite names like "CAS500-2", are not masses.
- Keep the descriptive User-Agent and request timeout, which Wikimedia's User-Agent policy asks for, and keep fetch concurrency at its current level.

## Dependencies

- Edit `requirements.in` (runtime) or `requirements-dev.in` (tools), then regenerate the matching lock with the command in its header. The `requirements*.txt` locks carry hashes that pip enforces, so hand edits break installs.
- Python 3.11 is the target for CI and Docker.

## Commits and pull requests

- Use Conventional Commits, such as `fix(parsing): …` or `ci: …`. The scheduled workflow's own commits are `chore(outputs): update graphs by scheduler`.
- To bring a PR branch up to date with `main`, rebase onto `main` and force-push with `--force-with-lease`. Don't merge `main` into the branch, including through `gh pr update-branch`'s default merge mode, so history stays linear.
- When a change alters the graphs, attach before-and-after renders to the PR, and update the README if behavior or outputs change.
