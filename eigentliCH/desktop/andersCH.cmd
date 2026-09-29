@echo off
rem Task P1: the desktop icon's target. Double-click this, or make a shortcut to it.
rem
rem It starts the local server, which opens the default browser at the onboarding chat once the socket is
rem listening. Closing this window stops the program, which is the intended way to quit: the server holds the
rem submission in memory only, so nothing is left behind.
rem
rem Deliberately the ROOT interpreter, not the engine's. This process must not import personal_alm -- it reaches
rem the engine by subprocess under engines\Life_Balance_Sheet\.venv instead. See desktop\server.py.

setlocal
set HERE=%~dp0
set ROOT=%HERE%..
set PY=%ROOT%\.venv\Scripts\python.exe

if not exist "%PY%" (
  echo.
  echo   The root virtual environment is missing:
  echo     %PY%
  echo.
  echo   Create it and install nothing beyond the standard library -- this program needs no dependencies.
  echo.
  pause
  exit /b 1
)

title andersCH
echo.
"%PY%" "%HERE%server.py" %*

rem If the server exits on its own (a port already in use is the usual reason), keep the window open so the
rem message is readable rather than vanishing with the console.
if errorlevel 1 (
  echo.
  echo   The program stopped with an error. The message above says why.
  echo.
  pause
)
endlocal
