@echo off
REM ============================================================================
REM AR Daily Report wrapper — invoked by the Windows Scheduled Task "AR-Daily-Report".
REM
REM Changes to the repo root, runs the Node job, and APPENDS all stdout+stderr to
REM scripts\daily-report.log. Any extra args are forwarded to the job (e.g. --dry-run).
REM
REM Requires: node on PATH (v20+) and uv on PATH. The job starts its OWN ephemeral
REM backend on a spare port — it never touches the user's :8001 dev server.
REM ============================================================================
setlocal
set "REPO_ROOT=%~dp0.."
cd /d "%REPO_ROOT%"

echo.>> "%REPO_ROOT%\scripts\daily-report.log"
echo ==== AR Daily Report run: %DATE% %TIME% ====>> "%REPO_ROOT%\scripts\daily-report.log"

node "%REPO_ROOT%\frontend\scripts\daily-report.mjs" %*>> "%REPO_ROOT%\scripts\daily-report.log" 2>&1
set "RC=%ERRORLEVEL%"

echo ==== exit code: %RC% ====>> "%REPO_ROOT%\scripts\daily-report.log"
endlocal & exit /b %RC%
