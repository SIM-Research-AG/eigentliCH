"""Task P1: the desktop program. A local server that serves the onboarding chat and runs the real engine.

    python desktop/server.py                 # then open http://127.0.0.1:8810/
    python desktop/server.py --no-browser    # for tests and scripts

**Why a program and not a web page.** The chat computes a *Sofortbefund* in JavaScript — the deterministic
identities only. The engine adds the three things a browser cannot: the allocation over the macro states, the CVaR
chance constraint at the client's own epsilon, and the costates that answer whether an hour is better spent
earning or networking. It also replaces the page's fixed assumptions with the household's own figures.

**Why stdlib and no new dependency.** This process CANNOT import `personal_alm`: `optim.problem` and
`optim.symbolic` import casadi, which is absent from the root `.venv`, and the package is only importable from
inside `engines/Life_Balance_Sheet`. So the engine is reached by subprocess under its own interpreter — the same
seam `engines/lbs/adapter.py` and `tools/schulung/data.py` already use — and this file stays on the standard
library so the root environment gains nothing. That also rules out `jsonschema`: the cheap structural guard below
is deliberately not a schema validation, because the **engine** is the authority on what it will accept and it
already refuses with reasons (`SubmissionError`). Duplicating that here would be a second copy of one rule.

**Two constraints this program respects rather than works around.**

*The regulated wall.* A *Befund* is education; a Recommendation requires a named Curator and a Decision Record
(G7). This program cannot emit one, and `/befund` returns figures and caveats — including `publishable: false`
when the engine does not stand behind them.

*Nothing is written to disk.* `cockpit/server.py` states "Nothing here writes" and this program keeps that. A
submission is held in memory for the duration of one request and then forgotten. Persisting it is task P4's
decision and needs its own record: it is the moment a client record exists, not a convenience.

**Localhost only.** Bound to 127.0.0.1 on a fixed high port. Nothing is exposed and nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# `hub` is imported at module level for its two CONSTANTS — the allow-list of linkable folders and the servable
# extensions — which the file handler needs before any request arrives. Importing the module is cheap; only
# `hub.render()` touches the filesystem and probes ports, and that is still called per request.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub  # noqa: E402

#: 8801 is the Macro_Model cockpit, 8802 PCP, 8804 the andersCH cockpit. 8810 keeps clear of all three.
PORT = 8810
HOST = "127.0.0.1"

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "andersCH-prototype" / "onboarding-chat.html"
ENGINE_DIR = ROOT / "engines" / "Life_Balance_Sheet"
ENGINE_PY = ENGINE_DIR / ".venv" / "Scripts" / "python.exe"
#: Saved submissions, so a case can be replayed without re-interviewing. Gitignored: real answers about a real
#: person's finances belong on the machine that collected them, not in version control.
REPLAYS = Path(__file__).resolve().parent / "replays"

#: **One hour, and 900 s was measurably too short.** A real submission with a 20-year horizon (`dt_opt = 1.0`, so
#: `K = 20`) is a substantially bigger NLP than the flagship's `K = 10`, and six solves at `M = 32` ran past the
#: quarter-hour cap — so the client waited fifteen minutes and then got a timeout, which is the worst of both.
#: This is a local desktop program with a visible progress state: the cost of waiting is patience, while the cost
#: of a premature cap is the whole computation thrown away.
ENGINE_TIMEOUT_S = 3600

#: Versions this program will forward. Kept in step with `personal_alm.app.onboarding.SUPPORTED_VERSIONS`; the
#: engine refuses anything else anyway, so this is a fast path rather than a second authority.
KNOWN_VERSIONS = ("onb@0.1.0", "onb@0.1.1", "onb@0.1.2", "onb@0.1.3")


def _ollama_up(timeout: float = 1.5) -> bool:
    """Whether the local model daemon answers. Short timeout: this is on the health path, not a request path."""
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _questionnaire_info() -> dict:
    """What the interview file currently is: its schema version, its hash, its size and its date.

    The hash is what makes "one source of truth" checkable rather than asserted. Somebody holding a copy can
    compare it against this and know whether they have the current file, which a filename and a date cannot
    tell them: both survive an edit.
    """
    import hashlib  # noqa: PLC0415 - only this function needs it
    if not PAGE.exists():
        return {"present": False}
    body = PAGE.read_bytes()
    text = body.decode("utf-8", errors="replace")
    version = None
    marker = "schema_version:"
    at = text.find(marker)
    if at >= 0:
        chunk = text[at + len(marker):at + len(marker) + 40]
        for quote in ("'", '"'):
            if quote in chunk:
                start = chunk.index(quote) + 1
                end = chunk.find(quote, start)
                if end > start:
                    version = chunk[start:end]
                    break
    return {"present": True, "schema_version": version, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "modified": __import__("datetime").datetime.fromtimestamp(
                PAGE.stat().st_mtime).isoformat(timespec="seconds"),
            "accepted_versions": list(KNOWN_VERSIONS),
            "version_is_accepted": version in KNOWN_VERSIONS if version else None}


#: The child is told to speak UTF-8 explicitly. Windows hands a subprocess the console codepage, so a Python
#: traceback or an engine message containing an umlaut -- which nearly all of them do -- arrives as cp1252 and
#: the UTF-8 decode of it misbehaves. `desktop/gameplan.py` documents the same constant and the same reason.
_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


class EngineUnavailable(RuntimeError):
    """The engine could not be reached. Distinct from the engine refusing a submission."""


def run_engine(payload: dict, *, preview: bool = False, risk: bool = True,
               timeout: float = ENGINE_TIMEOUT_S) -> dict:
    """Call `personal_alm.app.befund` in the engine's own interpreter. JSON in, JSON out.

    Returns the engine's object verbatim, including its `{"error": ...}` on a refusal — the server does not
    reinterpret a refusal, because the engine's reason is better than any summary of it.
    """
    if not ENGINE_PY.exists():
        raise EngineUnavailable(
            f"the engine interpreter is missing at {ENGINE_PY}. This program needs "
            f"engines/Life_Balance_Sheet/.venv to exist with casadi installed."
        )
    cmd = [str(ENGINE_PY), "-m", "personal_alm.app.befund"]
    if preview:
        cmd.append("--preview")
    if not risk:
        cmd.append("--no-risk")

    # **The engine writes what it reaches, so a timeout stops discarding hours of finished solving.** A run
    # reaches several states worth having on their own: the main solve assembled, then the achievable search's
    # bracket after each probe, each of which is a further full solve. One household's run took three hours,
    # of which the search was the last two -- and this timeout would have thrown all of it away, including the
    # main solve, whose facts are the deliverable. The snapshot lives in a temporary file for the duration of
    # the call; the engine writes it atomically, so a read on the timeout cannot catch a half-written object.
    snap = Path(tempfile.gettempdir()) / f"andersch-befund-{os.getpid()}-{time.time_ns()}.json"
    cmd += ["--progress", str(snap)]
    try:
        # **The same treatment `desktop/gameplan.py` needed, and for the same reason.** That seam works from
        # inside a request handler and this one returned `stdout=None` with exit 0 from exactly there, while
        # working in-process. The two differed only in `errors=` and the child environment: without
        # `PYTHONIOENCODING` the child inherits the console codepage, and every message in this engine has an
        # umlaut in it. Decoding that as UTF-8 is what goes wrong, and it goes wrong differently depending on
        # how the parent's own handles were set up — which is why it never reproduced outside the server.
        proc = subprocess.run(
            cmd, cwd=str(ENGINE_DIR), input=json.dumps(payload), capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=_CHILD_ENV, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # **Keep whatever finished.** An unfinished run is not the same as no run: the main solve may have
        # been done for an hour. The snapshot carries `partial: True` and the probe count it reached, so
        # nothing downstream can mistake an interrupted search for a completed one.
        salvaged = _read_snapshot(snap)
        if salvaged is not None:
            salvaged["timed_out_after_s"] = float(timeout)
            return salvaged
        raise EngineUnavailable(f"the engine did not finish within {timeout:.0f}s") from exc
    finally:
        try:
            snap.unlink(missing_ok=True)
        except OSError:
            pass
    # **`proc.stdout` can be None and the bare `.strip()` took the whole server down with it.** Observed on
    # this route: an AttributeError inside the handler thread, so the client saw a dropped connection with no
    # status at all rather than a reason — the least useful of the possible failures. Whatever produces a None
    # here, a request handler must turn it into a message; `or ""` costs nothing and the returncode and stderr
    # are reported alongside so the cause is visible rather than guessed at.
    out = proc.stdout or ""
    err = proc.stderr or ""
    if not out.strip():
        raise EngineUnavailable(
            f"the engine returned nothing (exit {proc.returncode}, stdout {type(proc.stdout).__name__}): "
            f"{err[-400:]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise EngineUnavailable(f"the engine returned unreadable output: {exc}: {out[:200]}") from exc


def _read_snapshot(path: "Path") -> dict | None:
    """The last snapshot the engine wrote, or None.

    Never raises: this runs on a path where something has already gone wrong, and a reader that throws would
    replace a partial answer with no answer. An unreadable or absent file simply means nothing was salvaged.
    """
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def structural_complaint(payload: object) -> str | None:
    """A cheap guard, NOT a schema validation. Returns a reason to refuse, or None.

    Deliberately shallow: it catches the three mistakes worth catching before spending a subprocess — not an
    object, an unknown version, a missing block — and leaves every judgement about content to the engine.
    """
    if not isinstance(payload, dict):
        return "the body must be a JSON object"
    v = payload.get("schema_version")
    if v not in KNOWN_VERSIONS:
        return (f"unrecognised schema_version {v!r}; this program forwards {list(KNOWN_VERSIONS)}. "
                f"Refusing rather than guessing.")
    for block in ("state", "params"):
        if not isinstance(payload.get(block), dict):
            return f"the submission has no {block!r} object"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "andersCH-desktop/0.1"

    # --- plumbing ---------------------------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # No caching: the page is edited during development and a stale copy is a confusing bug.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        # One quiet line per request. The default logs to stderr with a timestamp per line, which buries the
        # only thing worth seeing on this console: whether the engine ran.
        sys.stderr.write("  %s\n" % (fmt % args))

    # --- routes -----------------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            if not PAGE.exists():
                self._json(500, {"error": f"the onboarding page is missing at {PAGE}"})
                return
            # Served byte for byte. The page has no external references and needs no editing to work under a
            # server, which is a property worth preserving rather than a coincidence.
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/replays":
            # What can be replayed. Names only — the contents are personal answers and are not listed here.
            self._json(200, {"replays": sorted(p.name for p in REPLAYS.glob("*.json"))}
                       if REPLAYS.is_dir() else {"replays": []})
            return
        if path.startswith("/replay-data/"):
            self._serve_replay(path[len("/replay-data/"):])
            return
        if path == "/hub":
            # Rendered per request, not cached: it reads the disk and probes ports, which is the whole point.
            self._send(200, hub.render(self.server.server_address[1]), "text/html; charset=utf-8")
            return
        if path.startswith("/file/"):
            self._serve_known_file(path[len("/file/"):])
            return
        if path == "/favicon.ico":
            ico = Path(__file__).resolve().parent / "andersCH.ico"
            if ico.exists():
                self._send(200, ico.read_bytes(), "image/x-icon")
            else:
                self._json(404, {"error": "no icon"})
            return
        if path == "/questionnaire":
            self._serve_questionnaire()
            return
        if path == "/questionnaire-info":
            self._json(200, _questionnaire_info())
            return
        if path == "/health":
            # The coach's readiness is reported as two separate facts, because they fail independently and
            # need different remedies: an index that was never built is one command, a daemon that is not
            # running is another. Collapsing them into "coach: no" would send someone to the wrong fix.
            book = ROOT / "desktop" / "bookindex" / "meta.json"
            self._json(200, {"ok": True, "engine_present": ENGINE_PY.exists(),
                             "page_present": PAGE.exists(), "versions": list(KNOWN_VERSIONS),
                             "book_index_present": book.exists(),
                             "local_model_reachable": _ollama_up(),
                             # The report path has its own prerequisites and they fail independently of the
                             # engine's: the Optimiser lives in a third interpreter, and a missing one costs
                             # exactly one section rather than the whole report.
                             "optimiser_present": (ROOT / "engines" / "PCP" / ".venv" / "Scripts"
                                                   / "python.exe").exists(),
                             "questionnaire": _questionnaire_info()})
            return
        if path == "/dashboard":
            # 501 rather than 404, deliberately: the membership handover is a real seam that is not built, and a
            # 404 would say it does not exist. Task P4.
            self._json(501, {"error": "the client dashboard is not built yet (task P4). "
                                      "Becoming a member is the point at which a client record first exists, "
                                      "which is a decision that needs its own record."})
            return
        self._json(404, {"error": f"no route {path!r}"})

    #: Directories the hub may link into. **An allow-list of DIRECTORIES, and the filename is then matched against
    #: what is actually in them** — not joined onto a path. `../` traversal, absolute paths and symlinks are all
    #: ruled out by construction rather than by sanitising the input, which is the only way to get this right:
    #: every path-sanitising bug in history was a sanitiser someone thought was complete.
    #: Imported from `hub` rather than restated, because a hub that links into a folder the server will not
    #: serve produces a 404 that looks like a missing file, and the two lists drifting apart is the failure
    #: mode. One definition, in the module that decides what to link.
    _LINKABLE = hub.LINKABLE

    def _serve_replay(self, name: str) -> None:
        """A saved submission, so a case can be re-run without re-interviewing.

        **Why the page fetches this rather than the server rendering a report.** The renderer lives in the page
        (`renderFacts`), and a second implementation in Python would be a second thing to keep true — this repo has
        already paid for two copies of one idea more than once (the debt gate, the pension gate). So replay feeds
        the SAME code path a live interview does: fetch the submission, POST it to `/befund`, render.

        Matched against the directory listing rather than joined onto a path, for the reason `_serve_known_file`
        gives. These files are personal financial answers and are gitignored.
        """
        if not REPLAYS.is_dir():
            self._json(404, {"error": f"no replay folder at {REPLAYS}"})
            return
        for p in REPLAYS.glob("*.json"):
            if p.name == name:
                self._send(200, p.read_bytes(), "application/json; charset=utf-8")
                return
        self._json(404, {"error": f"no saved submission named {name!r}"})

    def _serve_known_file(self, ref: str) -> None:
        """Serve `folder/name` from the allow-list. Both halves are matched, never joined.

        **`ref` carries its folder since 9 August 2026, and that is a correctness fix.** It used to be a bare
        filename resolved by walking the allow-list in order, and two of those folders contain an
        `index.html` — so the hub's *Blueprint · Architecture* card served the 239 KB
        `andersCH-prototype/index.html` instead. The link returned 200 with the wrong document, which no test
        and no eye catches. Requiring the folder makes the collision impossible rather than improbable.

        A bare filename is still accepted, because saved links and the replay flow use them, but it is
        resolved only when exactly ONE folder has it. An ambiguous bare name is refused with both candidates
        named, rather than silently resolved to whichever comes first.
        """
        folder, _, name = ref.rpartition("/")
        if folder and folder not in self._LINKABLE:
            self._json(404, {"error": f"{folder!r} is not a folder this program serves"})
            return

        matches = []
        for f in ([folder] if folder else self._LINKABLE):
            d = ROOT / f
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.name == name and p.is_file() and p.suffix in hub.SERVABLE:
                    matches.append(p)

        if not matches:
            self._json(404, {"error": f"{ref!r} is not a page this program serves"})
            return
        if len(matches) > 1:
            self._json(409, {"error": f"{name!r} exists in more than one folder; name it explicitly",
                             "candidates": [m.relative_to(ROOT).as_posix() for m in matches]})
            return
        p = matches[0]
        self._send(200, p.read_bytes(), hub.SERVABLE[p.suffix])

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path == "/prose":
            self._do_prose()
            return
        if path == "/ask":
            self._do_ask()
            return
        if path == "/gameplan":
            self._do_gameplan()
            return
        if path == "/readiness":
            self._do_readiness()
            return
        if path != "/befund":
            self._json(404, {"error": f"no route {path!r}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        raw = self.rfile.read(length).decode("utf-8-sig", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not valid JSON: {exc}"})
            return

        complaint = structural_complaint(payload)
        if complaint:
            self._json(400, {"error": complaint})
            return

        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        preview = "preview=1" in query
        # **The risk assessment is opt-IN on this route.** `risk=1` asks for the CVaR-constrained solve at the
        # household's own confidence -- the expensive, refusable one. Without it the goal must hold in
        # expectation and the confidence comes back measured instead of required. Measured on one household:
        # 2.3 s against 436 s. Defaulting to the cheap answer is the whole point; a client should not wait
        # half an hour to be told something the arithmetic already said.
        risk = "risk=1" in query
        try:
            facts = run_engine(payload, preview=preview, risk=risk)
        except EngineUnavailable as exc:
            # 503, not 500: the engine is a separate process that may simply not be installed, and the page
            # should say so rather than fall back to its own arithmetic.
            self._json(503, {"error": str(exc)})
            return
        if "error" in facts:
            # The engine refused. Forward its reason unchanged and use 422: the request was well-formed and the
            # content was not acceptable.
            self._json(422, facts)
            return
        self._json(200, facts)

    def _serve_questionnaire(self) -> None:
        """The interview itself, as a download. **One source of truth for a file that gets handed around.**

        The onboarding has been completed away from this machine more than once -- on a client's laptop, in a
        meeting -- and each time by someone sending a copy of `onboarding-chat.html`. A copy is a fork the
        moment the original changes, and the schema version is inside the page: a stale copy produces a
        submission this program will refuse, and the person holding it has no way to know why. Served from the
        running program, the file handed out is by construction the one this program will accept.

        `Content-Disposition: attachment` rather than a link, so the browser saves it instead of running it --
        a page that opens itself in a tab is one the reader will fill in and then wonder where the answers
        went, because the served copy has no server behind it.
        """
        if not PAGE.exists():
            self._json(404, {"error": f"the onboarding page is missing at {PAGE}"})
            return
        body = PAGE.read_bytes()
        info = _questionnaire_info()
        name = f"onboarding-chat_{info.get('schema_version') or 'unknown'}.html"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Schema-Version", info.get("schema_version") or "unknown")
        self.send_header("X-Content-SHA256", info.get("sha256") or "")
        self.end_headers()
        self.wfile.write(body)

    def _do_readiness(self) -> None:
        """Phase 2, and phase 3 on request. What can be computed, what blocks it, what to ask next.

        **Structurally different from `/befund` and `/gameplan`, and cheap for a reason.** Those two answer a
        household's question; this one answers whether the question can be answered yet. A surface may call it
        after every answer, so it reads fields and does no optimisation. `?rank=1` adds the measured
        sensitivity ranking, which recomputes the closed-form report once per candidate gap.

        No structural complaint is raised on the body. This route exists precisely for submissions that are not
        yet complete, so refusing an incomplete one would refuse its whole purpose.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not valid JSON: {exc}"})
            return
        submission = body.get("submission") if isinstance(body, dict) and "submission" in body else body
        if not isinstance(submission, dict):
            self._json(400, {"error": "the body must be a submission, or {submission: ...}"})
            return
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            import gameplan  # local import: it reaches the engine interpreter
            self._json(200, gameplan.readiness(submission, rank="rank=1" in query))
        except gameplan.GameplanUnavailable as exc:
            self._json(503, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - the reason beats a stack trace here
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _do_gameplan(self) -> None:
        """The report. A submission in, a finished dossier out.

        **Two shapes of body are accepted, and the difference matters.** `{"submission": ..., "facts": ...}`
        carries a solve that has already run, so the plan section is filled in. A bare submission runs the
        deterministic path alone -- which is not a fallback but the normal case, because the solve takes tens
        of minutes and the other thirteen sections take a second. A report that says which single question is
        unanswered is worth more than no report, and until this route existed the choice was between waiting an
        hour and getting nothing.

        Returns HTML, not JSON. The page opens it in a new tab and the reader saves or prints it from there;
        nothing is written to disk on this side, which keeps the rule this program states in its docstring.
        `?json=1` returns the computed quantities instead, for checking a figure against the rule that made it.
        `?prose=1` asks the local model for a connective paragraph per section -- off by default, because
        measured drafts invented a property and a conclusion while passing every numeric check, so what it
        produces is a marked draft for an editor rather than part of the report.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        raw = self.rfile.read(length).decode("utf-8-sig", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not valid JSON: {exc}"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "the body must be a submission, or {submission, facts}"})
            return

        submission = body.get("submission") if "submission" in body else body
        facts = body.get("facts") if isinstance(body.get("facts"), dict) else None
        # Whether a solve is on its way. Only meaningful when `facts` is absent, and it changes one box from
        # "this was not computed" to "this is being computed and will appear here".
        pending = bool(body.get("solve_pending")) and facts is None
        if not isinstance(submission, dict):
            self._json(400, {"error": "no submission in the body"})
            return
        complaint = structural_complaint(submission)
        if complaint:
            self._json(400, {"error": complaint})
            return

        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            import dossier  # for the fragment branch below; pure stdlib, no engine needed
            import gameplan  # local import: it reaches two other interpreters
            # **`force=1` is the client saying "rechnen Sie trotzdem".** Without it a household whose answers
            # contradict each other receives the open-items page rather than the report, because every figure
            # in the report is computed from those answers. With it the report renders with what stayed open
            # listed above it. The flag is on the request rather than in the submission: it is a decision
            # about this viewing, not a fact about the household.
            q, page = gameplan.build(submission, facts,
                                     with_allocation="no_allocation=1" not in query,
                                     with_prose="prose=1" in query,
                                     solve_pending=pending,
                                     force="force=1" in query)
        except gameplan.GameplanUnavailable as exc:
            # 503: a missing interpreter is an installation state, not a bad request.
            self._json(503, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - the reason is more useful than a stack trace here
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        if "json=1" in query:
            self._json(200, q)
            return

        # **`fragment=<name>` is what makes the report arrive in two parts.** The reader gets the whole
        # deterministic dossier in about a second and starts reading; the solve keeps running; when it lands,
        # the page asks for just the plan section and splices it in where the reader already is. Returning the
        # whole document instead would work and would also scroll them back to the top of a page they are four
        # paragraphs into, which is the kind of thing that makes people stop trusting a tool.
        #
        # An empty body with 204 when the section does not exist for this household. A bridge section for
        # someone with no early stop is not a thing to invent because a caller asked.
        frag = ""
        for part in query.split("&"):
            if part.startswith("fragment="):
                frag = part[len("fragment="):]
        if frag:
            html = dossier.render_fragment(q, frag)
            if not html:
                self._send(204, b"", "text/html; charset=utf-8")
                return
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _do_ask(self) -> None:
        """The book coach. A question in, an answer from *Capital Saturation* out.

        **A SEPARATE ROUTE FROM `/prose`, and separate for a reason that is not tidiness.** `/prose` takes a
        household's computed facts and writes about them; it is K2 by construction and inherits every
        restriction that follows. This takes a question and returns an explanation of the book, and its
        request body has **no field through which a household could arrive**. That is what makes it K0: not a
        promise that no personal data is sent, but a shape in which none can be.

        The consequence is that this needs no gate. The data-class rule holds a model reading K1 or above
        inside the core perimeter; K0 content has no such condition, and this runs locally regardless.

        Errors are distinguished rather than collapsed. 503 when the local daemon is unreachable or the index
        has never been built — both are "not installed yet" rather than "your question was bad" — and 200 with
        a `refused` field when the book simply does not cover it, because that is an answer.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not valid JSON: {exc}"})
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("question"), str):
            self._json(400, {"error": "the body must be {\"question\": \"...\"}"})
            return

        try:
            import coach  # local import: it loads a megabyte of index on first use
        except Exception as exc:  # noqa: BLE001 - report the cause, do not crash the server
            self._json(503, {"error": f"the book coach is unavailable: {exc}"})
            return

        result = coach.answer(payload["question"])
        out = result.to_dict()
        # An index that was never built and a daemon that is not running are both installation states, and a
        # 503 tells the page to say so instead of showing the refusal as if the book had been consulted.
        if result.refused and ("Buchindex" in result.refused or "nicht erreichbar" in result.refused):
            self._json(503, out)
            return
        self._json(200, out)

    def _do_prose(self) -> None:
        """Task P5: the local model describes the facts. A SEPARATE route from `/befund` on purpose.

        The solve and the generation are two different waits — tens of seconds and tens of seconds — and putting
        them in one request means the client sees nothing until both finish. Split, the page can show the figures
        as soon as they exist and fill the prose in after.

        Prose is also strictly optional: if Ollama is not running the figures still stand, so a failure here
        returns 200 with a `refused` reason rather than an error status. Nothing about the report depends on it.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        try:
            facts = json.loads(self.rfile.read(length).decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not valid JSON: {exc}"})
            return
        if not isinstance(facts, dict):
            self._json(400, {"error": "the body must be the facts object returned by /befund"})
            return
        try:
            import prose  # local import: the module reaches the network, and /befund must not depend on it
            r = prose.write_prose(facts)
        except Exception as exc:  # a local model is optional; its failure must not take the report with it
            self._json(200, {"text": "", "refused": f"the prose layer failed: {exc}"})
            return
        self._json(200, {"text": r.text, "model": r.model, "refused": r.refused,
                         "unverified_numbers": r.unverified_numbers, "ok": r.ok})


def serve(*, port: int = PORT, open_browser: bool = True, landing: str = "/") -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}{landing}"
    print(f"andersCH desktop · {url}")
    print(f"  engine  {'found' if ENGINE_PY.exists() else 'MISSING at ' + str(ENGINE_PY)}")
    print(f"  page    {'found' if PAGE.exists() else 'MISSING at ' + str(PAGE)}")
    print("  nothing is written to disk; close this window to stop the program")
    if open_browser:
        # After the socket is listening, so the browser never races the server to an empty page.
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    return httpd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="andersCH desktop program (task P1)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    ap.add_argument("--landing", choices=("chat", "hub"), default="chat",
                    help="which page the browser opens: the client interview, or the overview of everything built")
    args = ap.parse_args(argv)
    httpd = serve(port=args.port, open_browser=not args.no_browser,
                  landing="/hub" if args.landing == "hub" else "/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
