

:: Created by Juliano Ferrari Gianlupi

:: Semi-linear merge with squash
:: Inspired by Microsoft's semi-linear merge
:: Thank to https://stackoverflow.com/a/63621528 for identifying the git cli commands
:: commands that are implicit in Microsoft's implementation

:: Will do a semi-linear merge from source branch to target branch. It
:: will squash the source branch into a single commit

:: TODO: add non-squash option
:: TODO: shell script version

::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
@echo off

:: Check if in git repo
if not exist .git (
    echo Not a Git repository. Quitting.
    exit /b
)

:: Set source branch and target branch
set SOURCE=%1 
set TARGET=%2

echo Source branch: %SOURCE%
:: Check if source and target branches are provided
if "%SOURCE%"=="" (
    echo Source branch is not provided.
    exit /b
)

if "%SOURCE%"==" " (
    echo Source branch is not provided.
    exit /b
)

:: if target branch is not provided, use current branch as target branch
setlocal EnableDelayedExpansion
if "%TARGET%"==""  ( 
    echo Target branch is not provided. Using current branch as target.
    for /f %%a in ('git branch --show-current') do (
        set TARGET=%%a
    )
)
if "%TARGET%"==" " ( 
    echo Target branch is not provided. Using current branch as target.
    for /f %%a in ('git branch --show-current') do (
        set TARGET=%%a
    )
)
endlocal & set TARGET=%TARGET%

echo Target branch: %TARGET%

:: making sure everything is up to date
git fetch --prune

git checkout %TARGET%
git pull

git checkout %SOURCE%
git pull

:: rebase source branch on top of target branch
git rebase %TARGET%
git checkout %TARGET%

:: --squash and --no-ff are incompatible, so we do a two-step merge

:: create intermediary branch to squash source branch
set SQUASH=-squashed
echo %SQUASH%

if "%SOURCE:~-1%"==" " (
    :: if source branch ends with a space, remove it
    set INTERMEDIARY=%SOURCE:~0,-1%%SQUASH%
) else (
    set INTERMEDIARY=%SOURCE%%SQUASH%
)
echo %INTERMEDIARY%

:: squash merge source branch into intermediary branch
git checkout -b %INTERMEDIARY%
git merge --squash %SOURCE%
git commit --no-edit


:: merge intermediary branch into target branch
git checkout %TARGET%
git merge --no-ff --no-edit %INTERMEDIARY%

