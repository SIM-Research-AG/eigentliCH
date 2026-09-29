@echo off
REM The desktop app: starts datafeed, honi and the Fund Map engine if they are not running,
REM opens the cockpit in its own window, and stops what it started when the window closes.
REM
REM For a desktop icon instead of this file, run once:   python -m cockpit shortcut

cd /d "%~dp0"
set PYW=pythonw
if exist "..\Macro\.venv\Scripts\pythonw.exe" set PYW=..\Macro\.venv\Scripts\pythonw.exe
start "" "%PYW%" -m cockpit desktop %*
