@echo off
title The Life Balance Sheet
cd /d "%~dp0"
echo Starting the Life Balance Sheet engine...
echo (Your browser will open. Close this window to stop the app.)
echo.
".venv\Scripts\python.exe" -m personal_alm.app.server
echo.
echo The app has stopped.
pause
