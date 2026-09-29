"""The report, end to end: submission in, dossier out. The seam the desktop program calls.

**Three interpreters, one report.** The deterministic quantities and the findings live in
`personal_alm.app.gameplan`, because that is where `Params` and `dynamics` live and constants are imported
rather than restated. The allocation lives in `desktop/allocation.py`, because the mandate derivation needs
pydantic and the Optimiser needs its own environment. The renderer lives in `desktop/dossier.py` and needs
neither, so it runs here on the standard library. This module is the only place that knows all three exist.

**What the optimiser is for, and what it is not for.** `POST /befund` runs the household NLP and answers one
question: does the stated goal hold at the stated confidence, and what is this period's action. It takes tens of
minutes. **Everything else in the dossier is arithmetic on the intake and takes about a second.** So the report
is built from the quantities alone by default, and the plan section is filled in when a `ReportFacts` is
supplied. A household whose solve times out gets a complete report with one section that says which question is
unanswered -- which is a far better outcome than the report not existing, and until now it did not exist.

**Nothing is written to disk on this path.** `desktop/server.py` keeps that rule and so does this: the report is
returned as a string. The one exception is the derived mandate, which the Optimiser reads from a path because
that is its interface; `desktop/allocation.py` says so where it writes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import allocation  # noqa: E402
import dossier  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "engines" / "Life_Balance_Sheet"
ENGINE_PY = ENGINE_DIR / ".venv" / "Scripts" / "python.exe"

#: Seconds. The quantities are closed-form: measured under a second on every worked case. A minute is a
#: generous ceiling that still fails fast if the import graph breaks.
QUANTITIES_TIMEOUT_S = 60

#: The child processes are told to speak UTF-8 explicitly. **Without this the server dies on a traceback
#: rather than reporting it.** Windows gives a subprocess the console codepage, so a Python traceback
#: containing an umlaut -- which every message in this codebase does -- arrives as cp1252 bytes, and
#: `subprocess.run(encoding="utf-8")` raises UnicodeDecodeError while trying to read the error. The failure
#: then has nothing to do with the actual fault and hides it completely, which is how it was found.
_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


class GameplanUnavailable(RuntimeError):
    """The report could not be produced. Carries a reason a reader can act on."""


def quantities(submission: dict, facts: dict | None = None) -> dict:
    """The deterministic quantities and findings, computed in the engine's interpreter."""
    if not ENGINE_PY.exists():
        raise GameplanUnavailable(
            f"the engine interpreter is missing at {ENGINE_PY}. The quantities need "
            f"engines/Life_Balance_Sheet/.venv, because the model's constants live there and this "
            f"report imports them rather than restating them."
        )
    payload = json.dumps({"submission": submission, "facts": facts}, ensure_ascii=False)
    driver = (
        "import json,sys\n"
        "from personal_alm.app.gameplan import assemble\n"
        "d=json.loads(sys.stdin.read())\n"
        "sys.stdout.write(json.dumps(assemble(d['submission'], d['facts']), ensure_ascii=False, "
        "allow_nan=False))\n"
    )
    proc = subprocess.run([str(ENGINE_PY), "-c", driver], input=payload, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_CHILD_ENV, timeout=QUANTITIES_TIMEOUT_S,
                          cwd=str(ENGINE_DIR))
    if proc.returncode != 0:
        raise GameplanUnavailable(_reason(proc.stderr or proc.stdout))
    start = proc.stdout.find("{")
    if start < 0:
        raise GameplanUnavailable("the quantities step produced no JSON payload")
    return json.loads(proc.stdout[start:])


def _reason(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


#: The phase-2 and phase-3 driver. Separate from `quantities` because it must stay cheap: a surface may call
#: this after every answer, and the whole point of the phase is that it costs nothing to ask.
_READINESS_DRIVER = (
    "import json,sys\n"
    "from personal_alm.app import workflow as W\n"
    "from personal_alm.app.gameplan import assemble, _params_from\n"
    "d=json.loads(sys.stdin.read())\n"
    "sub=d['submission']\n"
    "out=W.readiness(sub)\n"
    "if d.get('rank'):\n"
    "    out['follow_ups']=W.follow_ups(sub, _params_from(sub), assemble)\n"
    "sys.stdout.write(json.dumps(out, ensure_ascii=False, allow_nan=False))\n"
)


def readiness(submission: dict, *, rank: bool = False) -> dict:
    """What can be computed from this submission, and what to ask next. Phases 2 and 3."""
    if not ENGINE_PY.exists():
        raise GameplanUnavailable(
            f"the engine interpreter is missing at {ENGINE_PY}. The readiness check needs "
            f"engines/Life_Balance_Sheet/.venv, because it reads the same fields the engine does."
        )
    payload = json.dumps({"submission": submission, "rank": bool(rank)}, ensure_ascii=False)
    proc = subprocess.run([str(ENGINE_PY), "-c", _READINESS_DRIVER], input=payload,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=_CHILD_ENV, timeout=QUANTITIES_TIMEOUT_S, cwd=str(ENGINE_DIR))
    if proc.returncode != 0:
        raise GameplanUnavailable(_reason(proc.stderr or proc.stdout))
    start = proc.stdout.find("{")
    if start < 0:
        raise GameplanUnavailable("the readiness check produced no JSON payload")
    return json.loads(proc.stdout[start:])


def household_id(submission: dict) -> str:
    """A stable name for this household's derived mandate.

    **The `onb-` prefix is load-bearing and not cosmetic.** It marks real-person data throughout this repo, and
    `.gitignore` excludes `onb-*` from `engines/PCP/mandates` and `output` on the strength of it. A mandate
    named anything else would be committed.
    """
    raw = submission.get("raw") or {}
    year = raw.get("birth_year")
    canton = str(raw.get("canton") or "").lower().replace(" ", "-")[:12]
    collected = (submission.get("meta") or {}).get("collected") or ""
    parts = [p for p in ("onb", str(int(year)) if year else None, canton or None,
                         collected.replace("-", "")[:8] or None) if p]
    return "-".join(parts)


def build(submission: dict, facts: dict | None = None, *,
          with_allocation: bool = True, with_prose: bool = False,
          solve_pending: bool = False, force: bool = False) -> tuple[dict, str]:
    """The quantities and the rendered dossier. Returns both, because callers want both.

    The allocation is attempted and its failure is recorded in the report rather than raised: an allocation
    that could not be computed is one missing section, and refusing the whole report over it would trade
    thirteen sections for one.

    **`force` renders the report while items are still open.** Without it a household with a contradiction
    in its answers gets the open-items page instead, because every figure in the report is computed from
    those answers. With it the report renders with what stayed open listed above it -- an escape hatch that
    exists because a household whose figure genuinely is not known yet must not be locked out of its own
    Standortbestimmung, and because a gate with no override is a gate somebody routes around in the code.

    **`with_prose` is off by default, and that default is a measurement.** Three live drafts from
    `apertus:8b` on 20 August 2026: one clean, one rejected for inventing an income figure, and one that
    passed every check while inventing a Ferienwohnung the household does not own and a conclusion about
    accumulating capital that appears in no fact. The per-section number verifier caught the first kind and
    cannot see the second -- a category is not a number, and a wrong inference quotes only right figures. So
    the paragraphs are available on request, marked as unreviewed drafts, and never on by default.
    """
    q = quantities(submission, facts)
    q["solve_pending"] = bool(solve_pending) and facts is None
    if with_allocation:
        hh = household_id(submission)
        try:
            q["allocation"] = allocation.for_household(q, household_id=hh)
        except Exception as exc:  # noqa: BLE001 - the reason is reported, not swallowed
            q["allocation"] = {"state": "unavailable", "why": f"{type(exc).__name__}: {exc}"}
        q["household_id"] = hh
    if with_prose:
        try:
            import sectionprose  # local: it reaches the model daemon, and the report must not depend on it
            q["prose"] = {name: {"text": slot.text, "model": slot.model}
                          for name, slot in sectionprose.write_all(q).items()}
        except Exception as exc:  # noqa: BLE001 - a model failure is never a report failure
            q["prose_error"] = f"{type(exc).__name__}: {exc}"
    return q, dossier.render(q, force=force)


def main(argv: list[str] | None = None) -> int:
    """`python desktop/gameplan.py --in submission.json --out dossier.html [--facts facts.json]`."""
    import argparse
    ap = argparse.ArgumentParser(description="Build a gameplan dossier from an onboarding submission.")
    ap.add_argument("--in", dest="infile", required=True, help="onb@0.1.x submission JSON")
    ap.add_argument("--facts", help="a ReportFacts JSON from app/befund, optional")
    ap.add_argument("--out", dest="outfile", help="where to write the HTML; default stdout")
    ap.add_argument("--quantities", help="also write the computed quantities here, for checking")
    ap.add_argument("--force", action="store_true",
                    help="render the report even while items are open, with them listed above it. Without "
                         "this a household with a contradiction in its answers gets the open-items page, "
                         "because every figure in the report is computed from those answers")
    ap.add_argument("--no-allocation", action="store_true",
                    help="skip the Optimiser, for a faster check of the arithmetic")
    ap.add_argument("--prose", action="store_true",
                    help="ask the local model for a connective paragraph per section. Off by default: "
                         "measured drafts invented a property and a conclusion while passing every "
                         "numeric check, so what it produces is a marked draft for the editor")
    args = ap.parse_args(argv)

    submission = json.loads(Path(args.infile).read_text(encoding="utf-8-sig"))
    facts = None
    if args.facts:
        loaded = json.loads(Path(args.facts).read_text(encoding="utf-8-sig"))
        facts = loaded.get("facts", loaded) if isinstance(loaded, dict) else None

    q, page = build(submission, facts, with_allocation=not args.no_allocation,
                    with_prose=args.prose, force=args.force)
    if args.quantities:
        Path(args.quantities).write_text(json.dumps(q, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    if args.outfile:
        Path(args.outfile).write_text(page, encoding="utf-8")
        gate = q.get("gate") or {}
        sys.stderr.write(f"  {len(page):,} bytes, stage {gate.get('stage', '?')}"
                         + (f" ({gate['open_count']} offen)" if gate.get("open_count") else "")
                         + f", {len(q['findings'])} findings, "
                         f"{sum(len(g['items']) for g in q['schedule'])} scheduled actions\n")
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
