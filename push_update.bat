@echo off
echo Removing git lock file...
if exist ".git\index.lock" del /f ".git\index.lock"

REM Find GitHub Desktop's bundled git
set GIT=
for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set GIT=%%D\resources\app\git\cmd\git.exe
)
if "%GIT%"=="" if exist "C:\Program Files\Git\cmd\git.exe" set GIT=C:\Program Files\Git\cmd\git.exe

if "%GIT%"=="" (
    echo ERROR: Could not find git.exe
    pause
    exit /b 1
)

echo Using git at: %GIT%
echo Committing changes...
"%GIT%" add templates/estimator.html app.py
"%GIT%" commit -m "Estimator: fix HTML/JS escaping, auto first frames, Superior Quote # field"
echo Pushing to GitHub...
"%GIT%" push origin main
echo Done!
pause
