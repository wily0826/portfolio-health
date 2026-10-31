@echo off
REM Anomaly scan scheduled wrapper (SPEC-anomaly A-20).
REM Lives in scripts\; %~dp0 is this dir, ..\ is the project root, so it is relocatable.
REM Invoked by Windows Task Scheduler; appends to ..\logs\anomaly_scan.log.
REM ASCII-only comments: cmd.exe reads this file in the system codepage, not UTF-8.
setlocal
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
python -m scripts.run_anomaly_scan --backfill --quiet >> "logs\anomaly_scan.log" 2>&1
endlocal
