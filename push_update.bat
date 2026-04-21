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
"%GIT%" add app.py templates/estimator.html templates/base.html templates/dashboard.html templates/admin_users.html templates/forms.html templates/login.html templates/job_detail.html templates/new_job.html templates/field.html static/style.css static/logo.png
"%GIT%" commit -m "Fix photo delete permission error; fix mobile nav sidebar close on tap"
echo Pushing to GitHub...
"%GIT%" push origin main
echo Done!
pause
