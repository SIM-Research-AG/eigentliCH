"""The desktop app: the cockpit in its own window, with the engines it needs started.

No GUI toolkit is added (DECISIONS.md C-05). The window is Microsoft Edge (on every Windows
11 machine) or Chrome in app mode: no tabs, no address bar, its own profile under
``%LOCALAPPDATA%\\sim-tech\\cockpit``, so it looks and behaves like an application. Closing
the window stops the cockpit and the engines this app started; engines that were already
running are left alone.

If neither browser is found the default browser opens a tab instead, and the page's
heartbeat decides when the app ends.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import httpx
import uvicorn

from .launcher import Launcher
from .settings import ROOT, STATIC, Settings

APP_NAME = "sim-tech Cockpit"
#: With no window to watch, the app ends this long after the last page stopped pinging.
HEARTBEAT_GRACE_S = 45.0


def profile_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "sim-tech" / "cockpit"


def find_browser() -> Optional[str]:
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                           Path(base) / "Google/Chrome/Application/chrome.exe"]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def _answering(url: str) -> bool:
    try:
        return httpx.get(url, timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def run(settings: Settings, start_engines: bool = True, browser: Optional[str] = None) -> int:
    from .api import create_app

    base = f"http://{settings.host}:{settings.port}"
    launcher = Launcher(settings)
    server: Optional[uvicorn.Server] = None

    if _answering(base + "/api/config"):
        # A cockpit is already serving (another window, or start.cmd): just open a window.
        _open_window(base, browser, wait=False)
        return 0

    app = create_app(settings, launcher=launcher)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, name="cockpit-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not _answering(base + "/api/config"):
        if time.monotonic() > deadline or not thread.is_alive():
            print(f"The cockpit did not start on {base}. Is the port taken?")
            return 1
        time.sleep(0.2)

    if start_engines:
        # In the background: the window opens at once and the System page shows engines
        # coming up one after the other.
        threading.Thread(target=launcher.start_autostart, name="engine-autostart", daemon=True).start()

    try:
        open_for = _open_window(base, browser, wait=True)
        if open_for is None or open_for < 5.0:
            # No app window to watch (default browser, or the window was handed to an
            # already open instance): end when the page stops sending its heartbeat.
            _wait_for_heartbeat(app)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        launcher.stop_started()
        thread.join(timeout=10)
    return 0


def _open_window(base: str, browser: Optional[str], wait: bool) -> Optional[float]:
    """Open the app window. Returns how long it stayed open when waited on, else None."""
    exe = browser or find_browser()
    url = base + "/"
    if not exe:
        webbrowser.open(url)
        return None
    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1440,920", f"--class={APP_NAME}"]
    started = time.monotonic()
    proc = subprocess.Popen(args)
    if not wait:
        return None
    proc.wait()
    return time.monotonic() - started


def _wait_for_heartbeat(app) -> None:
    # The grace runs from the last ping, or from now if no page has pinged yet: a window
    # closed before its first ping must not leave the app running for ever.
    since = time.monotonic()
    while True:
        time.sleep(2)
        last = getattr(app.state, "last_heartbeat", None) or since
        if time.monotonic() - max(last, since) > HEARTBEAT_GRACE_S:
            return


def create_shortcut(settings: Settings, start_menu: bool = False) -> Path:
    """A Windows shortcut that starts the desktop app without a console window."""
    python = settings.python if settings.python and settings.python.is_file() else None
    pythonw = python.with_name("pythonw.exe") if python else None
    if not pythonw or not pythonw.is_file():
        raise FileNotFoundError(f"pythonw.exe not found beside {python}; set `python` in config.yaml")
    icon = STATIC / "cockpit.ico"
    folder = ("[Environment]::GetFolderPath('Programs')" if start_menu
              else "[Environment]::GetFolderPath('Desktop')")
    ps = (
        f"$d = {folder}; $p = Join-Path $d '{APP_NAME}.lnk'; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); "
        f"$s.TargetPath = '{pythonw}'; $s.Arguments = '-m cockpit desktop'; "
        f"$s.WorkingDirectory = '{ROOT}'; $s.IconLocation = '{icon},0'; "
        "$s.Description = 'CIO workspace, engine status and test benches'; $s.Save(); $p"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip().splitlines()[-1])
