@echo off

:: Set working directory so relative paths in .env resolve correctly
cd /d "C:\Users\thesa\claude kalshi"

:: Google Drive auto-starts with Windows; no need to launch/kill it here.
:: The Python backup code will sync to G:\My Drive if it's already mounted.

:run_cron
"C:\Users\thesa\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\thesa\claude kalshi\main.py" cron

:: Only sleep if:
::   1. No active console session (PC was woken just for this task), AND
::   2. No interactive user is currently logged on to the physical console
:: This prevents accidental sleep when the user is at the PC but the window
:: happens to be in the background.
query session console 2>nul | findstr /i "Active" >nul 2>&1
if errorlevel 1 (
    query user 2>nul | findstr /v "^USERNAME" | findstr /i "console" >nul 2>&1
    if errorlevel 1 rundll32.exe powrprof.dll,SetSuspendState 0,1,0
)

echo.
echo Cron run complete. Press any key to close...
pause >nul
