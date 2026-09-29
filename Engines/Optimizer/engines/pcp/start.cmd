@echo off
REM Start the Portfolio Creation Program (pcp). Double-click this, or run it from a terminal.
REM
REM Docker gives you the database, and comes back by itself after a reboot. The engine is a
REM separate process and does not. Host and port come from config.yaml (8007 by default).
REM Leave the window open while you use it; closing it stops the engine.

cd /d "%~dp0"
set PY=python
if exist "..\..\.venv\Scripts\python.exe" set PY=..\..\.venv\Scripts\python.exe

echo Portfolio Creation Program (pcp)
echo   test bench:  http://127.0.0.1:8007/     (development builds only)
echo   API docs:    http://127.0.0.1:8007/docs
echo   stop:        close this window, or Ctrl+C
echo.

%PY% -X utf8 -m pcp serve

REM If it stopped straight away, the reason is above. The usual ones:
REM   - PostgreSQL not up         ->  docker compose up -d        (in Projects\PostgreSQL)
REM   - database never created    ->  python -m pcp init-db
REM   - engine not installed       ->  pip install -e .[dev]       (in this folder)
echo.
echo The engine stopped. Any error is printed above.
pause
