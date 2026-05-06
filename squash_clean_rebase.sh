#!/bin/bash

# Created by Juliano Ferrari Gianlupi

# creates a new branch (NB) from the common ancestor of the current branch (CB) and the
# supplied branch (SB). Then squashes the commits from CB into a
# single commit in NB. NB is then rebased onto the
# SB. And finally, the CB is reset to NB.

# check if in git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "Not a Git repository. Quitting."
  exit 1
fi
SB="$1"

# check if SB is provided
if [ "$SB" = "" ]; then
    echo "Compare branch is not provided."
    exit 1
fi

if [ "$SB" = " " ]; then
    echo "Compare branch is not provided."
    exit 1
fi

# remove space at the end of the branch name

if [ "${SB: -1}" = " " ]; then
    SB="${SB:0:-1}"
fi

# get current branch
CB=$(git branch --show-current)

NB="${CB}_squashed"

# get common ancestor commit
ANCESTOR=$(git merge-base "$CB" "$SB")

echo "Checkout common ancestor commit"
git checkout -q "$ANCESTOR"

# create new branch from common ancestor
echo "create new temp branch from common ancestor"
git checkout -b "$NB"

# squash commits from CB into a single commit
echo "squash commits from orig branch into a single commit"
git merge --quiet --squash "$CB"
git commit --no-edit

# rebase NB onto SB
echo "rebase onto target branch"
git rebase --quiet "$SB"

# reset CB to NB
echo "reset original branch to temp branch"
git checkout "$CB"
git reset --hard "$NB"
# git push --force-with-lease

# clean up
echo "remove temp branch"
git branch -D "$NB"
