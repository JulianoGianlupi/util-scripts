#!/bin/bash


# Created by Juliano Ferrari Gianlupi

# Semi-linear merge with squash
# Inspired by Microsoft's semi-linear merge
# Thank to https://stackoverflow.com/a/63621528 for identifying the git cli commands
# commands that are implicit in Microsoft's implementation

# Will do a semi-linear merge from source branch to target branch. It
# will squash the source branch into a single commit

# TODO: add non-squash option

################################################################################

# Check if in git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "not a git repository. quitting."
  exit 1
fi
s
# Set source branch and target branch
SOURCE="$1"
TARGET="$2"

echo "Source branch: $SOURCE"
# Check if source and target branches are provided
if [ "$SOURCE" = "" ]; then
    echo "Source branch is not provided."
    exit 1
fi

if [ "$SOURCE" = " " ]; then
    echo "Source branch is not provided."
    exit 1
fi

# if target branch is not provided, use current branch as target branch
if [ "$TARGET" = "" ]; then
    echo "Target branch is not provided. Using current branch as target."
    TARGET=$(git branch --show-current)
fi
if [ "$TARGET" = " " ]; then
    echo "Target branch is not provided. Using current branch as target."
    TARGET=$(git branch --show-current)
fi

echo "Target branch: $TARGET"

if [ "$SOURCE" = "$TARGET" ]; then
    echo "Source and target branches are the same. Quitting."
    exit 1
fi

# making sure everything is up to date
git fetch --prune

git checkout "$TARGET"
git pull

git checkout "$SOURCE"
git pull

# rebase source branch on top of target branch
git rebase "$TARGET"
git push --force-with-lease

git checkout "$TARGET"

# --squash and --no-ff are incompatible, so we do a two-step merge

# create intermediary branch to squash source branch
SQUASH="-squashed"
echo "$SQUASH"

if [ "${SOURCE: -1}" = " " ]; then
    # if source branch ends with a space, remove it
    INTERMEDIARY="${SOURCE:0:-1}${SQUASH}"
else
    INTERMEDIARY="${SOURCE}${SQUASH}"
fi
echo "$INTERMEDIARY"

# squash merge source branch into intermediary branch
git checkout -b "$INTERMEDIARY"
git merge --squash "$SOURCE"
git commit --no-edit
# git push --set-upstream origin "$INTERMEDIARY"

# reset source branch to intermediary branch
git checkout "$SOURCE"
git reset --hard "$INTERMEDIARY"
git push --force-with-lease


# merge intermediary branch into target branch
git checkout "$TARGET"
git merge --no-ff --no-edit "$SOURCE"

# clean up intermediary branch
git branch -D "$INTERMEDIARY"
# git push -d origin "$INTERMEDIARY"
