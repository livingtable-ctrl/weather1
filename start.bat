@echo off
start "Kalshi Backend" powershell -NoExit -Command "Set-Location 'C:\Users\thesa\claude kalshi'; .\.venv\Scripts\Activate.ps1; python web_app.py"
start "Kalshi Frontend" powershell -NoExit -Command "Set-Location 'C:\Users\thesa\claude kalshi\frontend'; npm run dev"
