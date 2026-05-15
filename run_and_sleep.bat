@echo off
title Kalshi Cron

:: Set working directory so relative paths in .env resolve correctly
cd /d "C:\Users\thesa\claude kalshi"

:: Google Drive auto-starts with Windows; no need to launch/kill it here.
:: The Python backup code will sync to G:\My Drive if it's already mounted.

:run_cron
"C:\Users\thesa\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\thesa\claude kalshi\main.py" cron

:: Restore window after cron — ShowWindow(SW_RESTORE) + SetForegroundWindow
:: Using -File to avoid cmd.exe quote-escaping mangling the inline -Command string
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\thesa\claude kalshi\restore_window.ps1" 2>nul

:: Only sleep if:
::   1. No active console session (PC was woken just for this task), AND
::   2. No interactive user is currently logged on to the physical console
query session console 2>nul | findstr /i "Active" >nul 2>&1
if errorlevel 1 (
    query user 2>nul | findstr /v "^USERNAME" | findstr /i "console" >nul 2>&1
    if errorlevel 1 rundll32.exe powrprof.dll,SetSuspendState 0,1,0
)

echo.
echo Cron run complete. Press any key to close...
pause >nul
