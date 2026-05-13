@echo off
start "Kalshi Backend" powershell -NoExit -Command "Set-Location 'C:\Users\thesa\claude kalshi'; .\.venv\Scripts\Activate.ps1; python web_app.py"

:: Wait briefly for Flask to start, then open the dashboard
timeout /t 2 /nobreak >nul
start http://localhost:5000
