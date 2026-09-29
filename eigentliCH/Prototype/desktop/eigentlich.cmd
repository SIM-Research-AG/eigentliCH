@echo off
rem The eigentliCH desktop icon's target. Double-click this, or make a shortcut to it.
rem
rem Starts the FastAPI backend and opens the default browser once the socket is listening. Closing this
rem window stops the program.
rem
rem UNLIKE the estate's andersCH.cmd, this one has its own virtual environment with real dependencies
rem (fastapi, sqlalchemy, alembic, uvicorn) and it writes to a SQLite file. The estate's no-dependency rule
rem applies to the ROOT environment, which this does not touch -- see DECISIONS.md A9.

setlocal
set HERE=%~dp0
set ROOT=%HERE%..
set PY=%ROOT%\.venv\Scripts\python.exe

if not exist "%PY%" (
  echo.
  echo   The prototype2 virtual environment is missing:
  echo     %PY%
  echo.
  echo   Create it:
  echo     python -m venv "%ROOT%\.venv"
  echo     "%PY%" -m pip install -e "%ROOT%\backend[test]" "uvicorn[standard]"
  echo.
  pause
  exit /b 1
)

title eigentliCH
echo.
"%PY%" "%HERE%run.py" %*

if errorlevel 1 (
  echo.
  echo   The program stopped with an error. The message above says why.
  echo.
  pause
)
endlocal
