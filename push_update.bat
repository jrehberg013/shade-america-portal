@echo off
echo Removing git lock file...
if exist ".git\index.lock" del /f ".git\index.lock"

REM Find git — try common locations
set GIT=
if exist "C:\Program Files\Git\cmd\git.exe" set GIT=C:\Program Files\Git\cmd\git.exe
if exist "C:\Program Files (x86)\Git\cmd\git.exe" set GIT=C:\Program Files (x86)\Git\cmd\git.exe

REM GitHub Desktop bundles git here
for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set GIT=%%D\resources\app\git\cmd\git.exe
)

if "%GIT%"=="" (
    echo ERROR: Could not find git.exe
    echo Please install Git for Windows from https://git-scm.com/download/win
    pause
    exit /b 1
)

echo Using git at: %GIT%
echo Committing changes...
"%GIT%" add app.py
"%GIT%" commit -m "Fix Trello filter names to match actual Trello column names"
echo Pushing to GitHub...
"%GIT%" push origin main
echo Done!
pause
