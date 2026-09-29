@echo off
REM Start the eigentliCH client app (the consumer side). Double-click this, or run it from a terminal.
REM
REM Docker gives you the database. The app is a separate process: leave this window open while you
REM use it; closing it stops the app. Host and port come from config.yaml (app:, 8017).
REM The engines it calls (lbs 8013, chatbot 8016, report 8015) are started on their own; while one
REM is down the app says so and keeps working.

cd /d "%~dp0"
set PY=python
if exist "..\.venv\Scripts\python.exe" set PY=..\.venv\Scripts\python.exe

echo eigentliCH client app
echo   app:       http://127.0.0.1:8017/
echo   API docs:  http://127.0.0.1:8017/docs
echo   stop:      close this window, or Ctrl+C
echo.

%PY% -X utf8 -m eigentlich serve

REM If it stopped straight away, the reason is above. The usual ones:
REM   - PostgreSQL not up         -^>  docker compose up -d          (in Projects\PostgreSQL)
REM   - schema not initialised    -^>  python -m eigentlich init-db, seed, migrate
REM   - port 8017 in use          -^>  another copy is running
echo.
echo The app stopped. Any error is printed above.
pause
