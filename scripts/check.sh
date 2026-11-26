#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

run() {
    printf '\n==> %s\n' "$*"
    "$@"
}

run ruff check .
run ruff format --check .
run mypy
run coverage erase
run coverage run --branch -m unittest discover -s tests
run coverage report --fail-under=95 --show-missing
run pip-audit --progress-spinner off --disable-pip --require-hashes -r requirements.txt
run pip-audit --progress-spinner off --disable-pip --require-hashes -r requirements-dev.txt
run scripts/update-locks.sh
run git diff --exit-code -- requirements.txt requirements-dev.txt

if command -v actionlint >/dev/null 2>&1; then
    run actionlint
else
    printf '\nSkipping actionlint (not installed locally).\n'
fi

printf '\nAll checks passed.\n'
