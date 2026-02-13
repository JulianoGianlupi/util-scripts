#!/usr/bin/env bash
# Adds "slide-out=no" to every branch in .git/machete that doesn't already have it.
# Safe to run multiple times — skips branches that already have the annotation.


# --git-common-dir resolves to the main .git directory even from a worktree,
# where .git is a file (containing "gitdir: ...") rather than a directory.
MACHETE_FILE="$(git rev-parse --git-common-dir)/machete"

if [[ ! -f "$MACHETE_FILE" ]]; then
    echo "No machete file found at: $MACHETE_FILE" >&2
    exit 1
fi

sed -i.bak -E '/slide-out=no/! s/^([[:space:]]*)([^[:space:]#].*)$/\1\2 slide-out=no/' "$MACHETE_FILE"
rm -f "${MACHETE_FILE}.bak"

echo "All branches in .git/machete annotated with slide-out=no."