@echo off

:: Start Google Drive (mounts G:\My Drive for backup)
start "" "C:\Program Files\Google\Drive File Stream\launch.bat"

:: Wait up to 30 seconds for G:\ to become available
set /a tries=0
:wait_drive
if exist "G:\My Drive\" goto drive_ready
set /a tries+=1
if %tries% geq 15 goto drive_timeout
timeout /t 2 /nobreak >nul
goto wait_drive

:drive_timeout
echo [run_and_sleep] Google Drive did not mount — backup will be skipped.
goto run_cron

:drive_ready

:run_cron
"C:\Users\thesa\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\thesa\claude kalshi\main.py" cron

:: Shut Google Drive back down
taskkill /IM "GoogleDriveFS.exe" /F >nul 2>&1

:: Only sleep if no active console session (PC was woken just for this task)
query session console | find "Active" >nul 2>&1
if errorlevel 1 rundll32.exe powrprof.dll,SetSuspendState 0,1,0
