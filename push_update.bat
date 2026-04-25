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
echo Committing all changes...
"%GIT%" add app.py templates/estimator.html templates/base.html templates/dashboard.html templates/admin_users.html templates/admin_settings.html templates/forms.html templates/login.html templates/job_detail.html templates/new_job.html templates/jobs.html templates/field.html templates/report.html templates/pricing.html templates/hip_calc.html templates/change_password.html templates/error.html templates/estimate_result.html static/style.css static/app.js static/logo.png static/apple-touch-icon.png static/icon-192.png static/icon-512.png NOTES.md HOME_SCREEN_INSTRUCTIONS.md
"%GIT%" commit -m "Cut-optimization pipe pricing, waste rows, waste-note display, HSS size fix"
echo Pushing to GitHub...
"%GIT%" push origin main
echo Done!
pause
