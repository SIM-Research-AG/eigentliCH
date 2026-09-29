@echo off
REM Start the eigentliCH ChatBot (chatbot). Double-click this, or run it from a terminal.
REM
REM Docker gives you the database, and comes back by itself after a reboot. The engine is a
REM separate process and does not. Host and port come from config.yaml (8016 by default).
REM The spark7 token is read from the family .env (..\..\.env), never printed.
REM Leave the window open while you use it; closing it stops the engine.

cd /d "%~dp0"
set PY=python
if exist "..\..\.venv\Scripts\python.exe" set PY=..\..\.venv\Scripts\python.exe

echo eigentliCH ChatBot (chatbot)
echo   test bench:  http://127.0.0.1:8016/     (development builds only)
echo   API docs:    http://127.0.0.1:8016/docs
echo   stop:        close this window, or Ctrl+C
echo.

%PY% -X utf8 -m chatbot serve

REM If it stopped straight away, the reason is above. The usual ones:
REM   - PostgreSQL not up          ->  docker compose up -d        (in Projects\PostgreSQL)
REM   - role or schema missing     ->  python -m store.provision   (in Projects\Engines\Instruments)
REM   - engine not installed        ->  ..\..\.venv\Scripts\pip install --no-deps -e .   (in this folder)
REM   - spark7 refused (403)        ->  SPARK7_CLIENT_ID / SPARK7_CLIENT_SECRET in ..\..\.env
echo.
echo The engine stopped. Any error is printed above.
pause
