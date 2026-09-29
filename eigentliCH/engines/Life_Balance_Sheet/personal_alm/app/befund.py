"""Task P3: submission JSON in, report JSON out. The seam the desktop program must call across.

    python -m personal_alm.app.befund  <  submission.json  >  facts.json

**Why a CLI and not an import.** The desktop server (P1) cannot `import personal_alm`. Two reasons, both already
learned by trying: `optim.problem` and `optim.symbolic` import **casadi**, which is not in the root `.venv`; and
the package is only importable from inside `engines/Life_Balance_Sheet`. So the call goes across the same
subprocess seam `engines/lbs/adapter.py` and `tools/schulung/data.py` already use — a child process under this
engine's own interpreter, JSON in and JSON out. This module is that child.

**It refuses rather than degrades.** An unreadable payload, an unsupported schema version, or a submission with no
runnable goal exits non-zero with a reason on stderr and `{"error": ...}` on stdout. A server that gets an error
object must show it, not fall back to the browser's arithmetic — the whole point of P3 is that the figures stop
being approximations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from ..cases import run_case
from ..optim.achievable import largest_fundable
from .onboarding import SubmissionError, case_from_submission
from .report import report_facts

#: Probes the achievable-goal search may spend when the stated goal is out of reach. Each is a full solve plus a
#: 400-scenario evaluation, so this is a cost decision and not a quality dial: at four probes the bracket closes
#: to a few per cent of the stated amount on a well-behaved case, because the first probe is seeded from the
#: shortfall rather than from the midpoint. Set to 0 to skip the search entirely.
DEFAULT_ACHIEVABLE_PROBES: int = 4

#: Solve settings for an interactive request. `M_opt=32` is the flagship's calibrated scenario count and the level
#: at which M70 found the CVaR constraint actually binds; anything less has been measured to let a violated
#: constraint report success. `n_starts=3` is the documented multistart. These are the settings that make a figure
#: worth showing, and they are why a request can take tens of seconds and needs a progress state on the page.
DEFAULT_SETTINGS: dict[str, Any] = {"M_opt": 32, "M_eval": 400, "seed": 0, "n_starts": 3}

#: Cheap settings for a preview or a smoke test. Explicitly NOT the default: at `M_opt=8` the tail constraint does
#: not bind reliably and the worked lives have been measured not to converge at all.
PREVIEW_SETTINGS: dict[str, Any] = {"M_opt": 8, "M_eval": 120, "seed": 0, "n_starts": 1}


#: Settings for a run WITHOUT the risk assessment. **This is a different question, not a cheaper answer to the
#: same one.**
#:
#: With the risk assessment the engine is told a confidence and asked whether the goal holds at it: a CVaR
#: chance constraint over the worst `epsilon` fraction of `M_opt` scenarios, which is what makes the NLP hard
#: and what M70 calibrated `M_opt=32` for. The household has to name a confidence up front -- 70, 80, 90, 95 --
#: which is among the hardest questions in the interview to answer meaningfully, and it decides how long the
#: computation takes before anyone has seen a single figure.
#:
#: Without it, the goal is required to hold on the EXPECTED path rather than in the tail, and the confidence is
#: then MEASURED by evaluating the resulting plan over `M_eval` scenarios. The client is told how certain the
#: answer turns out to be instead of being asked how certain to make it. Nothing is promised, so nothing can be
#: refused: `required_confidence` is None and M79 does not apply, because M79 is about a promise that could not
#: be kept.
#:
#: `epsilon` near 1 is how the tail constraint is relaxed without touching `optim/problem.py`. At epsilon = 1
#: the CVaR over the worst 100 % of scenarios IS the mean, so the constraint becomes "the goal holds in
#: expectation" -- a real constraint, just not a tail one. That keeps the two-phase machinery, the parity tests
#: and the dual extraction exactly as they are, which a new objective mode in the most delicate file in the
#: engine would not.
#: `M_opt=1` is measured rather than chosen. The ladder on a real household:
#:
#:     M_opt=1    1.7 s   outcome "plan"
#:     M_opt=4   86.7 s   outcome "undetermined"   (did not converge)
#:     M_opt=8  102.4 s   outcome "undetermined"   (did not converge)
#:     M_opt=32 436.1 s   outcome "plan"
#:
#: So the middle of the range is the worst of both: slow AND unreliable, exactly as M70 found. One
#: scenario is the expected path, which is what this mode asks for, and it converges. The confidence is
#: then measured over `M_eval=400` fresh scenarios, which is a simulation and costs almost nothing.
PLAN_ONLY_SETTINGS: dict[str, Any] = {"M_opt": 1, "M_eval": 400, "seed": 0, "n_starts": 1}

#: The epsilon that makes the chance constraint a mean constraint. Not 1.0 exactly: `_smooth_min` and the CVaR
#: transcription divide by epsilon, and the arithmetic is happier a hair below the boundary than on it.
PLAN_ONLY_EPSILON: float = 0.99


def befund(payload: dict, *, settings: dict[str, Any] | None = None,
           achievable_probes: int | None = None, risk_assessment: bool = True,
           progress: "Callable[[dict], None] | None" = None) -> dict:
    """Convert, solve, and assemble the facts. Returns a JSON-ready dict.

    `risk_assessment=False` runs the cheap path: the goal must hold in expectation, the confidence is measured
    rather than required, and no achievable-goal search runs because nothing was refused. See
    `PLAN_ONLY_SETTINGS` for why that is a different question rather than a worse answer to the same one.

    `progress(snapshot)` is called at every state this run reaches that is worth having on its own: once the
    main solve is done and its facts assembled, and again after each probe of the achievable search. **A run
    of this shape outlives timeouts** -- one household's took three hours, of which the search was the last
    two -- and without a snapshot a kill discards the finished main solve along with the unfinished search.
    Every snapshot but the last carries `partial: True`.
    """
    s = dict(settings or (DEFAULT_SETTINGS if risk_assessment else PLAN_ONLY_SETTINGS))

    # **The search is skipped below the calibrated scenario count, and that is a correctness rule rather than a
    # speed one.** `M_opt=32` is the level at which M70 found the CVaR constraint actually binds; below it a
    # violated constraint has been measured to report success. A bisection is only as good as its fundability
    # test, so searching for the largest fundable amount on a test known to certify unfundable plans would
    # return a number that looks like an answer and is an artefact of the resolution. It also keeps the
    # preview path a smoke test: four extra solves on figures that may not be quoted is cost with no return.
    if achievable_probes is None:
        # Nothing was required, so nothing was refused, so there is nothing to search for a smaller version
        # of. The probes exist to answer "then what IS in reach", which is a question only a refusal raises.
        achievable_probes = (DEFAULT_ACHIEVABLE_PROBES
                             if risk_assessment and s.get("M_opt", 0) >= DEFAULT_SETTINGS["M_opt"] else 0)
    conv = case_from_submission(payload)
    if not risk_assessment:
        # The goal keeps its amount and its date; only the tail requirement is relaxed, and the reported
        # requirement is removed altogether so nothing downstream can read a target that was never set.
        from dataclasses import replace as _replace  # noqa: PLC0415
        goal = _replace(conv.case.goal, epsilon=PLAN_ONLY_EPSILON)
        conv = _replace(conv, case=_replace(conv.case, goal=goal, confidence=None))
        conv.assumed.append(
            ("Sicherheitsanforderung", None,
             "keine verlangt: das Ziel muss im Erwartungswert halten, und die erreichte Sicherheit wird "
             "anschliessend gemessen statt vorgegeben"))
    result = run_case(conv.case, **s)

    # **When the goal is out of reach, ask what IS in reach — and only then.** The search costs one full solve
    # per probe, so it is not run for a household whose plan already holds; there is nothing to reduce and the
    # probe would only confirm it. `run_case` has already told us which case this is.
    #
    # A failure here must not sink the report. The facts from the solve are the deliverable, and an unanswered
    # "what would work?" is a missing second half rather than a broken first one — so the exception is recorded
    # as a note and the report goes out without the number.
    def _assemble(reach_now, *, partial: bool, probes_done: int = 0) -> dict:
        """The facts as they stand. Cheap: `report_facts` is assembly, not solving."""
        f = report_facts(
            conv.case, result,
            deferred=conv.deferred, assumed=conv.assumed,
            engine_settings=s,
            schema_version=payload.get("schema_version", ""),
            collected=(payload.get("meta") or {}).get("collected", ""),
            achievable=reach_now,
        )
        snap = f.to_dict()
        snap["publishable"] = f.publishable
        if partial:
            snap["partial"] = True
            snap["probes_done"] = probes_done
        return snap

    def _emit(reach_now, *, probes_done: int = 0) -> None:
        if progress is None:
            return
        try:
            progress(_assemble(reach_now, partial=True, probes_done=probes_done))
        except Exception as exc:  # noqa: BLE001 - a snapshot that fails must not take the run down
            print(f"befund: writing a progress snapshot failed: {exc}", file=sys.stderr)

    # **The main solve is done and its facts are worth keeping even if nothing else finishes.** Emitted here,
    # before the search, because the search is the optional second half and costs a full solve per probe.
    _emit(None)

    reach = None
    if (achievable_probes > 0 and conv.case.confidence is not None
            and result.p_goal < conv.case.confidence):
        try:
            # The bracket after each probe, so a kill during the search keeps what the search had found.
            def _after_probe(used: int, amount: float, funded: bool, p_goal: float) -> None:
                _emit(None, probes_done=used)

            reach = largest_fundable(conv.case, probes=achievable_probes,
                                     M_opt=s["M_opt"], M_eval=s["M_eval"], seed=s["seed"],
                                     n_starts=s["n_starts"], on_probe=_after_probe)
        except Exception as exc:  # noqa: BLE001 - any solver failure, reported rather than raised
            print(f"befund: the achievable-goal search failed: {exc}", file=sys.stderr)

    # A single explicit flag, so a caller cannot mistake "rendered" for "publishable" by forgetting to walk
    # the warning list. The engine states whether it stands behind these numbers. `_assemble` carries it.
    return _assemble(reach, partial=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview", action="store_true",
                    help="cheap settings for a smoke test; NOT sound enough to show a client")
    ap.add_argument("--no-risk", action="store_true",
                    help="skip the risk assessment: the goal must hold in expectation and the confidence "
                         "is MEASURED rather than required. Measured at 2.3 s against 436 s on the same "
                         "household. Not a cheaper answer to the same question -- see PLAN_ONLY_SETTINGS")
    ap.add_argument("--in", dest="infile", default="-", help="submission JSON path, or - for stdin")
    ap.add_argument("--progress", help=(
        "write a snapshot of the facts to this path at every state the run reaches: once the main solve is "
        "assembled, and again after each probe of the achievable search. A caller that is killed on a timeout "
        "reads the last snapshot instead of losing the whole run -- one household's took three hours, of "
        "which the search was the last two"))
    args = ap.parse_args(argv)

    try:
        # `utf-8-sig` decodes BOTH a BOM-prefixed and a plain UTF-8 file, and on this platform a BOM is the norm
        # rather than the exception: PowerShell's `>` redirection and `Get-Content | ...` both add one, so the
        # first real invocation of this CLI was refused for a reason that had nothing to do with the submission.
        # Tolerating it costs nothing; being strict costs someone an afternoon.
        raw = sys.stdin.read() if args.infile == "-" else open(args.infile, encoding="utf-8-sig").read()
        payload = json.loads(raw.lstrip("﻿"))
    except (OSError, json.JSONDecodeError) as exc:
        json.dump({"error": f"unreadable submission: {exc}"}, sys.stdout)
        print(f"befund: unreadable submission: {exc}", file=sys.stderr)
        return 2

    def write_snapshot(snap: dict) -> None:
        """Atomically, because a reader on a timeout may arrive mid-write and half a JSON object is worse
        than none: written to a neighbouring temporary file and moved over the target, which is atomic on
        both platforms this runs on."""
        target = Path(args.progress)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)

    on_progress = write_snapshot if args.progress else None

    try:
        if args.no_risk:
            out = befund(payload, risk_assessment=False, progress=on_progress)
        else:
            out = befund(payload, settings=PREVIEW_SETTINGS if args.preview else DEFAULT_SETTINGS,
                         progress=on_progress)
    except SubmissionError as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        print(f"befund: refused: {exc}", file=sys.stderr)
        return 3

    json.dump(out, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
