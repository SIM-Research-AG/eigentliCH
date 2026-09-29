@echo off
rem The second desktop icon: opens the OVERVIEW rather than the client interview.
rem
rem Same program, same port, different landing page. The overview lists everything that is built -- client
rem dossiers, the Master Control page, the household cockpits, the Schulung pages -- and probes the separate
rem cockpit services to say whether they are running.
rem
rem Closing this window stops the program. Nothing is written to disk.

setlocal
set HERE=%~dp0
set ROOT=%HERE%..
set PY=%ROOT%\.venv\Scripts\python.exe

if not exist "%PY%" (
  echo.
  echo   The root virtual environment is missing:
  echo     %PY%
  echo.
  pause
  exit /b 1
)

title andersCH - Uebersicht
echo.
"%PY%" "%HERE%server.py" --landing hub %*

if errorlevel 1 (
  echo.
  echo   The program stopped with an error. The message above says why.
  echo.
  pause
)
endlocal
