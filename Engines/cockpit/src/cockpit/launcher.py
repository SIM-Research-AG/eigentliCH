"""Starts engines as background processes, for the desktop app and the System page.

Each engine is started exactly as its ``start.cmd`` would start it, from its own folder, with
the Python named in ``config.yaml``; output goes to ``<data_dir>/logs/<engine>.log``. The
launcher only ever stops what it started itself: an engine that was already running (for
example in its own console window) is left alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from .settings import Engine, Settings

CREATE_NO_WINDOW = 0x08000000  # Windows: no console window for the child
#: Why nothing starts when ``COCKPIT_LAUNCHER=off`` (C-39): the start route answers 409 with it.
OFF = ("The cockpit starts no engines here: its launcher is off (COCKPIT_LAUNCHER=off), "
       "because something else starts them.")


@dataclass
class Started:
    engine: Engine
    process: subprocess.Popen
    log: Path
    started_at: float

    def describe(self) -> dict[str, Any]:
        code = self.process.poll()
        return {"key": self.engine.key, "pid": self.process.pid, "running": code is None,
                "exit_code": code, "log": str(self.log),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at))}


class Launcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started: dict[str, Started] = {}
        self._lock = threading.Lock()

    @property
    def python(self) -> str:
        p = self.settings.python
        return str(p) if p and p.is_file() else sys.executable

    def python_for(self, engine: Engine) -> str:
        """The engine's own interpreter when the roster names one (another virtual environment,
        C-17), else the cockpit-wide one. A named interpreter that is missing is an error: falling
        back would start the engine without its packages."""
        if engine.python is None:
            return self.python
        if not engine.python.is_file():
            raise LookupError(f"{engine.key}: its python {engine.python} does not exist")
        return str(engine.python)

    def answering(self, engine: Engine, timeout: float = 1.5) -> bool:
        try:
            return httpx.get(engine.url + engine.health_path, timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    def start(self, engine: Engine) -> dict[str, Any]:
        """Start one engine unless it already answers or was already started here."""
        if not self.settings.launcher:
            raise LookupError(OFF)
        if engine.start_cwd is None:
            raise LookupError(f"{engine.key} has no start command: its status is {engine.status}")
        with self._lock:
            mine = self.started.get(engine.key)
            if mine and mine.process.poll() is None:
                return {**mine.describe(), "action": "already started by the cockpit"}
            if self.answering(engine):
                return {"key": engine.key, "running": True, "action": "already running elsewhere"}
            python = self.python_for(engine)
            logs = self.settings.data_dir / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            log = logs / f"{engine.key}.log"
            fh = log.open("ab")
            fh.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} starting {engine.key}\n".encode())
            fh.flush()
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
            proc = subprocess.Popen([python, *engine.start_args], cwd=engine.start_cwd,
                                    stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env=env, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            fh.close()  # the child holds its own handle
            self.started[engine.key] = Started(engine, proc, log, time.time())
            return {**self.started[engine.key].describe(), "action": "started"}

    def wait_until_up(self, engine: Engine, timeout: float = 45.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.answering(engine, 1.0):
                return True
            mine = self.started.get(engine.key)
            if mine and mine.process.poll() is not None:
                return False  # it died; the reason is in its log
            time.sleep(0.5)
        return False

    def start_autostart(self, wait: bool = True) -> list[dict[str, Any]]:
        """Start every ``autostart`` engine in roster order (datafeed first), waiting for each.
        Nothing when the launcher is off (C-39)."""
        out: list[dict[str, Any]] = []
        if not self.settings.launcher:
            return out
        for engine in self.settings.engines:
            if not engine.autostart or engine.start_cwd is None:
                continue
            try:
                result = self.start(engine)
            except LookupError as exc:
                out.append({"key": engine.key, "running": False, "action": f"not started: {exc}", "up": False})
                continue
            if wait and result.get("action") == "started":
                result["up"] = self.wait_until_up(engine)
            out.append(result)
        return out

    def state(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.describe() for s in self.started.values()]

    def log_tail(self, key: str, lines: int = 80) -> Optional[str]:
        path = self.settings.data_dir / "logs" / f"{key}.log"
        if not path.is_file():
            return None
        text = path.read_bytes()[-64_000:].decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])

    def stop_started(self) -> None:
        with self._lock:
            for s in self.started.values():
                if s.process.poll() is None:
                    s.process.terminate()
            for s in self.started.values():
                try:
                    s.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    s.process.kill()
