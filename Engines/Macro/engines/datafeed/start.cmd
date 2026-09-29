@echo off
REM Start the datafeed engine. Double-click this, or run it from a terminal.
REM Host and port come from config.yaml (8001 by default). Leave the window open.

cd /d "%~dp0"
set PY=python
if exist "..\..\.venv\Scripts\python.exe" set PY=..\..\.venv\Scripts\python.exe

echo Data Feed engine (datafeed)
echo   API docs:  http://127.0.0.1:8001/docs
echo   stop:      close this window, or Ctrl+C
echo.

%PY% -X utf8 -m datafeed serve

REM If it stopped straight away, the reason is above. The usual ones:
REM   - PostgreSQL not up       ->  docker compose up -d          (in Projects\PostgreSQL)
REM   - store never built       ->  python -m datafeed bootstrap --create-database
echo.
echo The engine stopped. Any error is printed above.
pause
