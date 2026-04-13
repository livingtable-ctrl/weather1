@echo off

:: Set working directory so relative paths in .env resolve correctly
cd /d "C:\Users\thesa\claude kalshi"

:: Google Drive auto-starts with Windows; no need to launch/kill it here.
:: The Python backup code will sync to G:\My Drive if it's already mounted.

:run_cron
"C:\Users\thesa\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\thesa\claude kalshi\main.py" cron

:: Only sleep if no active console session (PC was woken just for this task)
query session console | find "Active" >nul 2>&1
if errorlevel 1 rundll32.exe powrprof.dll,SetSuspendState 0,1,0
