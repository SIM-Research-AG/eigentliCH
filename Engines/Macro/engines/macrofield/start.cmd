@echo off
rem Starts the macrofield engine on the port in config.yaml (default 8003).
rem Needs PostgreSQL: `docker compose up -d` in Projects\PostgreSQL.
rem First time only: `python -m macrofield init-db` then `python -m macrofield load`.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
"%~dp0..\..\.venv\Scripts\python.exe" -X utf8 -m macrofield serve
pause
