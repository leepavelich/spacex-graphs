#!/bin/sh
# Regenerates the hash-pinned lock files from requirements.in and
# requirements-dev.in. uv keeps the versions already pinned unless an .in file
# changed, so running this is also how CI checks that the locks are in sync.
# When passing --upgrade, set UV_EXCLUDE_NEWER to the UTC timestamp seven days
# ago, so uv upgrades only to releases that meet the Dependabot cooldown.
# Use the environment variable, not a flag that would change the lock header.
#
# The flags must match the command recorded in each lock file's header, which
# Dependabot reads to regenerate the locks the same way.
set -eu
cd "$(dirname "$0")/.."
for name in requirements requirements-dev; do
    uv pip compile --quiet --python-version 3.15 \
        --python-platform x86_64-manylinux_2_28 --generate-hashes \
        --emit-index-url "$@" "$name.in" -o "$name.txt"
done
