"""Engine manifests and the `call_engine` façade (§7). R-300 to R-305, C-03.

**The manifests live here, not in the estate.** §9 says "wrap behind `call_engine`, do not refactor
internals", and the estate's engines are not laid out one-directory-per-engine — `market_signal` is a flat
module whose home is `Macro_Model`. Writing `manifest.json` into each engine's project would be a refactor
of code this build is told not to touch. prototype2 owns the manifests; the engines stay as they are.

**R-300 is enforced by `load_manifest` raising.** An engine without a manifest is not callable, which is
only true if something refuses. `ip_owner` is non-nullable and was blank until it was declared — see A10.

**R-301 is enforced by `call_engine` refusing.** Every engine in the estate has a timeout above two
seconds, the fastest being 30. So there is no fast path to write, and a call from a request thread is
always a mistake: it raises rather than blocking a member's screen for up to half an hour.

**How the wiring works, and why it is another subprocess.** The estate's `engines` package runs under the
estate's own interpreter (`eigentliCH/.venv`), because it imports `contracts` and `orchestration` and, for
four of the seven, spawns a further subprocess under a per-engine venv whose pinned dependencies are
mutually incompatible — Macro_Model wants pandas 3, Fund_Map is pinned below it. prototype2's backend venv
is a third environment again. So `call_engine` does not import the estate: it runs `_BRIDGE` under the
estate interpreter and reads one JSON document back. That is §7's stated pattern ("one subprocess per
engine, its own venv, JSON over stdio") applied one level out, and it is what makes §9's "do not refactor
internals" cheap to keep — nothing in this module knows what an engine does.

**R-302 lives in `attempt`.** `call_engine` raises `EngineNotAvailable` when an engine will not run, and
`attempt` turns that into a payload whose only truthful field is that nothing is available. Neither ever
returns a number, because the failure R-302 names is a zero that reads like a measurement.

**R-303 lives in `_log_call`.** Inputs and outputs are logged with the member reference stripped first.

**R-304 / C-03.** Nothing here is reachable from an HTTP route: the façade is import-only and the API layer
does not import it. `tests/test_constraints.py::test_no_engine_artefact_served_over_http` is the check.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFESTS = Path(__file__).resolve().parent / "manifests"

#: The estate this prototype wraps. `parents[4]` is `eigentliCH/`, which holds `engines/`, `contracts/` and
#: `orchestration/`. Overridable, because the estate moved directories once already in July 2026 and
#: PHASE-0-SURVEY.md found stale absolute paths left behind by that move.
ESTATE_ROOT = Path(os.environ.get("ANDERSCH_ESTATE_ROOT", Path(__file__).resolve().parents[4]))

#: R-301. Above this, an engine may not be called on a request thread.
REQUEST_THREAD_BUDGET_S = 2

#: How long to allow the estate bridge itself, on top of the engine's own declared timeout. The bridge
#: imports pydantic, the contracts and seven adapter modules before the engine starts, and a cold import on
#: a laptop is slow enough that an engine running to its own limit would otherwise be killed by ours.
BRIDGE_OVERHEAD_S = 120

#: Where the JSON reply starts in the bridge's stdout. The estate prints — deprecation warnings, an
#: engine's own progress lines — and a parser that assumed stdout was JSON would fail on the day one of
#: those appeared rather than on the day something was actually wrong. ASCII record separator: it cannot
#: occur inside a JSON document.
_SENTINEL = "\x1e"

#: R-303. Names that carry the member reference into an engine. Stripped before anything is logged.
#: `regime_id` and `return_set_id` are deliberately absent: they identify a vintage of the world rather
#: than a person, and they are the part of the record that makes a run reproducible.
MEMBER_REFERENCE_KEYS = frozenset(
    {
        "member_id",
        "household_id",
        "goal_id",
        "position_id",
        "snapshot_id",
        "base_snapshot_id",
        "member",
        "household",
    }
)

MEMBER_REFERENCE_REDACTION = "[member reference removed]"

# ---------------------------------------------------------------------------
# Tuning constants
#
# These live in the engine layer rather than inline in a service because C-02's
# `test_no_literal_rate_in_application_code` forbids float literals in the model and service layers, and it
# was right to: a number sitting inline in a service is a knob nobody can find. The precedent is the note
# on `GROUNDED_ANSWER_TEMPERATURE` in `eigentlich/llm/__init__.py`.
#
# None of these is a rate. A rate belongs in a published AssumptionSet and nowhere else (C-02).
# ---------------------------------------------------------------------------

#: The market scope the world engines are asked for. `Global` is the blend Macro_Model publishes over seven
#: economies; the alternatives are `Europe` and the single-country scopes.
DEFAULT_MARKET_SCOPE = os.environ.get("ANDERSCH_MARKET_SCOPE", "Global")

#: The horizon a ReturnSet is estimated at, in years. ReturnSets are keyed on (scope, horizon) because a
#: ten-year per-state return is not a one-year return compounded. A property of the request, not of anyone.
DEFAULT_RETURNSET_HORIZON_YEARS = float(os.environ.get("ANDERSCH_RETURNSET_HORIZON", "1"))

#: Days per year, for turning a member's own target date into an engine's `horizon_years`. A calendar fact
#: rather than an assumption: 400 Gregorian years hold 97 leap days.
DAYS_PER_YEAR = 365.2425

#: PCP's optimiser settings. Which solver runs is an engine-tuning question, not a policy one.
OPTIMISER_SPEED = os.environ.get("ANDERSCH_OPTIMISER_SPEED", "exact")
OPTIMISER_ALGORITHM = os.environ.get("ANDERSCH_OPTIMISER", "curve")

#: Which control-plane agent prototype2 calls as. The estate permits only the Investment Agent to reach
#: engines at all — see `orchestration.control_plane`.
CALLING_AGENT = "investment"

#: Set on whichever thread is serving an HTTP request. `call_engine` reads it to decide whether it is
#: allowed to block. A flag rather than an inspection of the call stack, because the stack is not a reliable
#: place to learn this and a wrong answer here is a hung screen.
_serving = threading.local()

logger = logging.getLogger("eigentlich.engines")


class ManifestMissing(Exception):
    """R-300. An engine without a manifest is not callable."""


class ManifestInvalid(Exception):
    """A manifest that does not declare what R-300 requires is not a manifest."""


class EngineOnRequestThread(Exception):
    """R-301. Queue and poll instead."""


class UndeclaredInput(Exception):
    """A payload key the manifest does not declare.

    Refused rather than forwarded. R-300 makes the manifest the statement of what an engine takes, and an
    input travelling past it is an input nobody declared — A39's failure mode arriving from the other side.
    """


class EngineNotAvailable(Exception):
    """R-302. The engine did not run, or ran and produced nothing usable.

    Carries the reason and, where there is one, the command to replay by hand. Callers degrade the screen:
    "not available" is the only honest rendering, and a zero is the specific thing R-302 forbids.
    """

    def __init__(self, engine: str, reason: str, *, detail: str = "", replay: str = "") -> None:
        super().__init__(f"{engine}: {reason}")
        self.engine = engine
        self.reason = reason
        self.detail = detail
        self.replay = replay


REQUIRED_KEYS = ("name", "home", "runtime", "model_version", "inputs", "outputs", "timeout_s", "ip_owner")


@dataclass(frozen=True)
class Manifest:
    name: str
    home: str
    runtime: str
    model_version: str
    inputs: dict
    outputs: dict
    timeout_s: int
    ip_owner: str
    notes: str = ""

    @property
    def callable_on_request_thread(self) -> bool:
        return self.timeout_s <= REQUEST_THREAD_BUDGET_S


@lru_cache(maxsize=None)
def load_manifest(name: str) -> Manifest:
    path = MANIFESTS / f"{name}.json"
    if not path.exists():
        raise ManifestMissing(
            f"R-300: engine {name!r} has no manifest at {path}. An engine without a manifest is not "
            f"callable — declare its inputs, outputs, timeout and IP owner first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in data or data[key] in (None, "")]
    if missing:
        raise ManifestInvalid(f"R-300: manifest for {name!r} is missing or empty: {', '.join(missing)}")
    return Manifest(
        name=data["name"],
        home=data["home"],
        runtime=data["runtime"],
        model_version=data["model_version"],
        inputs=data["inputs"],
        outputs=data["outputs"],
        timeout_s=int(data["timeout_s"]),
        ip_owner=data["ip_owner"],
        notes=data.get("notes", ""),
    )


def known_engines() -> list[str]:
    return sorted(p.stem for p in MANIFESTS.glob("*.json"))


def mark_request_thread(value: bool = True) -> None:
    _serving.active = value


def on_request_thread() -> bool:
    return bool(getattr(_serving, "active", False))


# ---------------------------------------------------------------------------
# The estate bridge
# ---------------------------------------------------------------------------


def estate_python() -> Path:
    """The estate's own interpreter. Never this process's.

    prototype2's backend venv cannot import the estate: `contracts` is pydantic over the estate's pins, and
    the four wrapped engines each need a further venv again. Running the estate under its own interpreter is
    the same reasoning `engines/base.py` gives for running each engine under its own, one level out.
    """
    for candidate in (
        ESTATE_ROOT / ".venv" / "Scripts" / "python.exe",
        ESTATE_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    raise EngineNotAvailable(
        "estate",
        f"no estate interpreter under {ESTATE_ROOT / '.venv'}",
        detail=(
            f"the estate at {ESTATE_ROOT} has no virtual environment. Create it with\n"
            f"  cd {ESTATE_ROOT} && python -m venv .venv && "
            f".venv/Scripts/python.exe -m pip install -r requirements.txt\n"
            f"or point ANDERSCH_ESTATE_ROOT at a checkout that has one."
        ),
    )


def estate_available() -> bool:
    """Whether the estate can be reached at all. For a health board, and to skip a smoke test honestly."""
    if not (ESTATE_ROOT / "engines").is_dir():
        return False
    try:
        estate_python()
    except EngineNotAvailable:
        return False
    return True


#: Runs under the estate interpreter, reads one JSON request on stdin, writes one JSON reply on stdout.
#:
#: Kept as a string rather than as a file, so nothing executable is added to the estate: §9 says wrap, and a
#: script dropped into `eigentliCH/` would be prototype2 editing the estate. It opens a control-plane context
#: because the estate refuses an unmediated engine call, and it never swallows a failure — every exception
#: comes back as a reply this side turns into `EngineNotAvailable`.
_BRIDGE = r'''
import json, sys

request = json.loads(sys.stdin.read())
sys.path.insert(0, request["estate_root"])


def _dump(value):
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else value


try:
    import engines
    from orchestration.control_plane import mediate

    name = request["engine"]
    payload = dict(request["payload"])

    # One typed input crosses the JSON boundary: `score_engine` takes a RegimeRef object and reads
    # `.crisis_tail` off it, so a bare id would break inside the engine. Rehydrated here from the contract
    # the caller was handed by `market_signal`, using the producer's own class rather than a copy of it.
    if isinstance(payload.get("regime"), dict):
        from contracts.references import RegimeRef

        payload["regime"] = RegimeRef(**payload["regime"])

    with mediate(agent=request["agent"], purpose=request["purpose"]):
        result = engines.get(name).run(**payload)

    reply = {
        "ok": True,
        "engine": result.engine,
        "contract_type": type(result.contract).__name__,
        "contract": _dump(result.contract),
        "model_version": result.provenance.model_version,
        "as_of": result.provenance.as_of,
        "source": result.provenance.source,
        "notes": list(result.notes),
        "raw": dict(result.raw),
        "idempotency_key": result.idempotency_key,
        "trace_id": result.trace_id,
        "replay": result.call.replay(),
    }

    if request.get("artefact"):
        # The published contract behind the reference, read through the estate's own public resolver rather
        # than off disk. It is K0 and impersonal; R-304 keeps it off every HTTP route regardless.
        from contracts.references import load_regime, load_returnset

        if name == "market_signal":
            reply["artefact"] = load_regime(payload["scope"])
        elif name == "return_estimation":
            reply["artefact"] = load_returnset(payload["scope"], payload["horizon_years"])
        else:
            raise ValueError(
                "only market_signal and return_estimation publish a standing artefact; %s does not" % name
            )
except BaseException as error:  # noqa: BLE001 - reported, never swallowed
    detail = getattr(error, "detail", None)
    reply = {
        "ok": False,
        "error_type": type(error).__name__,
        "error": str(error),
        "detail": detail() if callable(detail) else None,
    }

sys.stdout.write("\x1e" + json.dumps(reply, default=str))
'''


def _redact(value: Any) -> Any:
    """R-303. Strip the member reference from anything about to be logged.

    Recursive, because engine payloads nest — `control` for the Life Balance Sheet, `components` on a
    Score. A shallow pass would log the member reference the moment an engine grew a nested input.
    """
    if isinstance(value, dict):
        return {
            key: (MEMBER_REFERENCE_REDACTION if key in MEMBER_REFERENCE_KEYS else _redact(inner))
            for key, inner in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(inner) for inner in value]
    return value


def redacted(payload: Any) -> Any:
    """`_redact`, exported so a caller can log an engine payload exactly the way this module does."""
    return _redact(payload)


def _log_call(stage: str, engine: str, body: Any) -> None:
    """R-303: engine inputs and outputs are logged, with the member reference removed.

    The body is redacted as one structure and then rendered, rather than interpolated field by field into a
    sentence, so there is no format string for a future input name to slip past. Reproducibility comes from
    `trace_id` and `replay` on the reply, neither of which names a person.
    """
    logger.info("engine %s %s: %s", engine, stage, json.dumps(_redact(body), default=str, sort_keys=True))


def _check_declared(manifest: Manifest, payload: dict) -> None:
    undeclared = sorted(set(payload) - set(manifest.inputs))
    if undeclared:
        raise UndeclaredInput(
            f"R-300: {manifest.name!r} does not declare {', '.join(undeclared)}. Declared inputs are "
            f"{', '.join(sorted(manifest.inputs))}. Add it to the manifest before passing it."
        )


def call_engine(
    name: str,
    payload: dict,
    *,
    timeout_s: int | None = None,
    purpose: str = "eigentliCH prototype2",
    include_artefact: bool = False,
) -> dict:
    """The single call site §7 asks for. R-300, R-301, R-302, R-303.

    Returns the engine's typed contract as JSON, with its provenance and the command that would replay the
    run by hand. Raises `EngineNotAvailable` if the engine did not produce one — never a partial result and
    never a zero.

    `include_artefact` additionally returns the standing published contract behind a world engine's
    reference: the Regime timeline for `market_signal`, the ReturnSet for `return_estimation`. That is what
    A35 seeds the first AssumptionSet from, and it is the only reason the parameter exists. The artefact is
    K0, and R-304 keeps it off every HTTP route whatever its class.
    """
    manifest = load_manifest(name)
    budget = timeout_s if timeout_s is not None else manifest.timeout_s

    if on_request_thread() and budget > REQUEST_THREAD_BUDGET_S:
        raise EngineOnRequestThread(
            f"R-301: {name!r} declares a {budget}s timeout and may not be called on a request thread "
            f"(budget {REQUEST_THREAD_BUDGET_S}s). Queue it and poll."
        )

    _check_declared(manifest, payload)
    _log_call("input", name, {"payload": payload, "model_version": manifest.model_version, "timeout_s": budget})

    interpreter = estate_python()
    request = json.dumps(
        {
            "estate_root": str(ESTATE_ROOT),
            "engine": name,
            "payload": payload,
            "agent": CALLING_AGENT,
            "purpose": purpose,
            "artefact": bool(include_artefact),
        }
    )
    command = [str(interpreter), "-c", _BRIDGE]

    try:
        completed = subprocess.run(
            command,
            input=request,
            cwd=str(ESTATE_ROOT),
            capture_output=True,
            text=True,
            timeout=budget + BRIDGE_OVERHEAD_S,
            check=False,
            # Deterministic hashing inside the engines, so a run is reproducible rather than dependent on
            # the interpreter's per-process salt. `engines/base.py` does the same for its own subprocesses.
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
    except FileNotFoundError as error:
        raise EngineNotAvailable(
            name, "the estate interpreter could not be launched", detail=str(error)
        ) from error
    except subprocess.TimeoutExpired as error:
        raise EngineNotAvailable(
            name, f"did not finish within {budget + BRIDGE_OVERHEAD_S}s", detail=str(error)
        ) from error

    if _SENTINEL not in completed.stdout:
        raise EngineNotAvailable(
            name,
            f"the estate bridge exited {completed.returncode} without a reply",
            detail=f"stdout: {completed.stdout[-800:]}\nstderr: {completed.stderr[-800:]}",
        )

    reply = json.loads(completed.stdout.rsplit(_SENTINEL, 1)[1])
    if not reply.get("ok"):
        raise EngineNotAvailable(
            name,
            f"{reply.get('error_type', 'failure')}: {reply.get('error') or 'no reason given'}",
            detail=reply.get("detail") or completed.stderr[-800:],
        )

    reply["engine"] = name
    _log_call(
        "output",
        name,
        {
            "contract_type": reply.get("contract_type"),
            "contract": reply.get("contract"),
            "trace_id": reply.get("trace_id"),
            "notes": reply.get("notes"),
            "raw": reply.get("raw"),
        },
    )
    return reply


def attempt(name: str, payload: dict, **kwargs: Any) -> dict:
    """R-302: engine failure degrades the screen, never the session.

    Returns `{"available": True, "result": {...}}` or `{"available": False, "reason": "..."}`. There is no
    third shape, and the failure branch carries no numeric field at all — the thing R-302 forbids is a
    failed engine rendering as a zero, and a screen reading a `0` cannot tell it from a measurement.

    `EngineOnRequestThread` and `UndeclaredInput` are deliberately NOT caught. They are defects in this
    codebase rather than an engine being unavailable, and degrading them would hide R-301 being broken
    behind a polite message.
    """
    try:
        return {"available": True, "result": call_engine(name, payload, **kwargs)}
    except EngineNotAvailable as error:
        logger.warning("engine %s not available: %s", name, error.reason)
        return {"available": False, "reason": error.reason, "engine": name}


__all__ = [
    "CALLING_AGENT",
    "DAYS_PER_YEAR",
    "DEFAULT_MARKET_SCOPE",
    "DEFAULT_RETURNSET_HORIZON_YEARS",
    "ESTATE_ROOT",
    "EngineNotAvailable",
    "EngineOnRequestThread",
    "MEMBER_REFERENCE_KEYS",
    "MEMBER_REFERENCE_REDACTION",
    "Manifest",
    "ManifestInvalid",
    "ManifestMissing",
    "OPTIMISER_ALGORITHM",
    "OPTIMISER_SPEED",
    "REQUEST_THREAD_BUDGET_S",
    "UndeclaredInput",
    "attempt",
    "call_engine",
    "estate_available",
    "estate_python",
    "known_engines",
    "load_manifest",
    "mark_request_thread",
    "on_request_thread",
    "redacted",
]
