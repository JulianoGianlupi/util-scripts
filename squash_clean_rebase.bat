:: Created by Juliano Ferrari Gianlupi

:: creates a new branch (NB) from the common ancestor of the current branch (CB) and the 
:: supplied branch (SB). Then squashes the commits from CB into a
:: single commit in NB. NB is then rebased onto the
:: SB. And finally, the CB is reset to NB.

:: TODO: create a shell script version

:: check if in git repo
if not exist .git (
    echo Not a Git repository. Quitting.
    exit /b
)

set SB=%1

:: check if SB is provided
if "%SB%"=="" (
    echo Compare branch is not provided.
    exit /b
)

if "%SB%"==" " (
    echo Compare branch is not provided.
    exit /b
)

:: remove space at the end of the branch name

if %SB:~-1%==" " (
    set SB=%SB:~0,-1%
)

:: get current branch
setlocal EnableDelayedExpansion
for /f %%a in ('git branch --show-current') do (
    set CB=%%a
)
endlocal & set CB=%CB%

set NB=%CB%_squashed

:: get common ancestor commit
setlocal EnableDelayedExpansion
for /f %%a in ('git merge-base %CB% %SB%') do (
    set ANCESTOR=%%a
)
endlocal & set ANCESTOR=%ANCESTOR%

git checkout %ANCESTOR%

:: create new branch from common ancestor
git checkout -b %NB%

:: squash commits from CB into a single commit
git merge --squash %CB%
git commit --no-edit

:: rebase NB onto SB
git rebase %SB%

:: reset CB to NB
git checkout %CB%
git reset --hard %NB%
git push --force-with-lease

:: clean up
git branch -D %NB%

