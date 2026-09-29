@echo off
REM The eigentliCH desktop icon's target (eigentliCH.lnk). One click: starts what the client app needs
REM and opens it in the browser.
REM
REM Starts lbs (8013), report (8015), chatbot (8016) and the app (8017), each in its own minimised
REM window, unless it already answers on /health; closing a window stops that part. PostgreSQL must be up
REM (docker compose up -d in Projects\PostgreSQL). `desktop.cmd --no-browser` starts without opening it.

setlocal
cd /d "%~dp0"
set PY=%~dp0..\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo The eigentliCH_Engines virtual environment is missing: %PY%
  pause
  exit /b 1
)

call :ensure 8013 "%~dp0..\engines\lbs" lbs
call :ensure 8015 "%~dp0..\engines\report" report
call :ensure 8016 "%~dp0..\engines\chatbot" chatbot
call :ensure 8017 "%~dp0." eigentlich

for /l %%i in (1,1,40) do (
  curl -s -m 2 -o nul http://127.0.0.1:8017/health && goto up
  timeout /t 1 /nobreak > nul
)
echo The app did not come up on 8017. Look at its window for the reason.
pause
exit /b 1

:up
if /i "%~1"=="--no-browser" exit /b 0
start "" http://127.0.0.1:8017/
exit /b 0

:ensure
curl -s -m 2 -o nul http://127.0.0.1:%1/health && exit /b 0
start "eigentliCH %3 (%1)" /min /d %2 "%PY%" -X utf8 -m %3 serve
exit /b 0
