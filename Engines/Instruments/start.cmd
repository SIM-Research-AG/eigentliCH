@echo off
REM Start the Fund Map engine. Double-click this, or run it from a terminal.
REM
REM Docker gives you the *database* and comes back by itself after a reboot
REM (restart: always). The engine is a separate process and does not. That is the
REM difference this script exists to remove.
REM
REM Leave the window open while you use the test bench; closing it stops the engine.

cd /d "%~dp0"

echo Fund Map engine
echo   test bench:  http://127.0.0.1:8006/
echo   API docs:    http://127.0.0.1:8006/docs
echo   stop:        close this window, or Ctrl+C
echo.

python -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8006

REM If it exited immediately, the reason is above. The usual ones:
REM   - PostgreSQL not up          ->  docker compose up -d   (in Projects\PostgreSQL)
REM   - store never built          ->  python -m store.etl.bootstrap --create-database
echo.
echo The engine stopped. Any error is printed above.
pause
