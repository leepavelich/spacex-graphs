#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

run() {
    printf '\n==> %s\n' "$*"
    "$@"
}

check_locks() (
    lock_dir=$(mktemp -d)
    trap 'rm -rf -- "$lock_dir"' EXIT
    mkdir "$lock_dir/scripts"
    cp scripts/update-locks.sh "$lock_dir/scripts/"
    # Seed uv with the existing pins and keep relative paths identical so
    # the compiler writes the same command and source paths into the locks.
    cp requirements.in requirements.txt requirements-dev.in requirements-dev.txt "$lock_dir/"
    "$lock_dir/scripts/update-locks.sh"

    status=0
    diff -u requirements.txt "$lock_dir/requirements.txt" || status=1
    diff -u requirements-dev.txt "$lock_dir/requirements-dev.txt" || status=1
    exit "$status"
)

run_if_installed() {
    if command -v "$1" >/dev/null 2>&1; then
        run "$@"
    else
        printf '\nSkipping %s (not installed locally).\n' "$1"
    fi
}

if [[ "${1:-}" == --locks-only ]]; then
    run check_locks
    exit 0
fi

run ruff check .
run ruff format --check .
run mypy
run coverage erase
run coverage run --branch -m unittest discover -s tests
run coverage report --fail-under=95 --show-missing
run pip-audit --progress-spinner off --disable-pip --require-hashes -r requirements.txt
run pip-audit --progress-spinner off --disable-pip --require-hashes -r requirements-dev.txt
run check_locks
run_if_installed actionlint
run_if_installed hadolint Dockerfile
run_if_installed shellcheck scripts/*.sh

printf '\nAll checks passed.\n'
