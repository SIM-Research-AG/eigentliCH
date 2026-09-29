@echo off
REM The eigentliCH desktop icon's target (eigentliCH.lnk). One click: starts what the client app needs
REM and opens it in the browser.
REM
REM Starts lbs (8013), report (8015), chatbot (8016), aggregation (8004), fmre (8006), pcp (8007), lbsim (8014, the API and
REM its plan workers: python -m lbsim serve) and the app (8017), each in its own minimised
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
rem Reports need aggregation (base Regime or scenario, EIG-63), fmre (the ReturnSets pcp reads) and pcp (the
rem allocation). They live in other families with their own environments, so they are started with those.
call :ensure_with 8004 "%~dp0..\..\Macro\engines\aggregation" aggregation "%~dp0..\..\Macro\.venv\Scripts\python.exe"
call :ensure_fmre
call :ensure_with 8007 "%~dp0..\..\Optimizer\engines\pcp" pcp "%~dp0..\..\Optimizer\.venv\Scripts\python.exe"
rem lbsim (Engine 14) reads lbs, pcp, aggregation and fmre; it lives in this family's environment (EIG-66).
call :ensure 8014 "%~dp0..\engines\lbsim" lbsim
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

:ensure_fmre
rem fmre (Instruments) is served by uvicorn on the system Python and answers on /v1/health.
curl -s -m 2 -o nul http://127.0.0.1:8006/v1/health && exit /b 0
start "eigentliCH fmre (8006)" /min /d "%~dp0..\..\Instruments" python -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8006
exit /b 0

:ensure_with
curl -s -m 2 -o nul http://127.0.0.1:%1/health && exit /b 0
if not exist %4 (
  echo %3 cannot be started: its environment %4 is missing.
  exit /b 0
)
start "eigentliCH %3 (%1)" /min /d %2 %4 -X utf8 -m %3 serve
exit /b 0
