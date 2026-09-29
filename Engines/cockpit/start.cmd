@echo off
REM Start the cockpit on http://127.0.0.1:8000/ in this window. Double-click, or run from a terminal.
REM
REM This serves the page only. The engines are separate processes: start them with their own
REM start.cmd, from the cockpit's System page, or use "sim-tech Cockpit.cmd" (the desktop app),
REM which starts the engines it needs and opens the cockpit in its own window.

cd /d "%~dp0"
set PY=python
if exist "..\Macro\.venv\Scripts\python.exe" set PY=..\Macro\.venv\Scripts\python.exe

echo sim-tech cockpit
echo   open:   http://127.0.0.1:8000/
echo   stop:   close this window, or Ctrl+C
echo.

%PY% -X utf8 -m cockpit serve %*

REM If it stopped straight away, the reason is above. The usual ones:
REM   - cockpit not installed   ->  ..\Macro\.venv\Scripts\pip install -e .[dev]   (in this folder)
REM   - port 8000 taken         ->  another cockpit is running; use that one
echo.
echo The cockpit stopped. Any error is printed above.
pause
