"""The control plane: the compliance pre-check, and trace and replay.

Phase 5's gate is "every engine call is wrapped by the pre-check and emits a replayable trace". A gate phrased
that way is only worth anything if an unwrapped call is **impossible** rather than merely discouraged, so this
module enforces it structurally.

**How the enforcement works.** `mediate()` opens a call context held in a `ContextVar`. Every engine adapter
builds its result through `EngineAdapter.result()`, which is the one chokepoint every engine must pass through,
and that method asks this module whether a context is open. Without one it raises `UnmediatedCall`. The guard
sits at the chokepoint rather than on each adapter, so a new engine inherits it without having to remember.

**The escape hatch is deliberate and noisy.** `allow_unmediated()` exists because tools, smoke tests and
exploratory work legitimately call engines outside a client request. It *records* every bypass, and the count is
readable, so "we bypassed it for testing" cannot quietly become "we bypass it in production".

**Why there is no wall-clock timestamp.** A trace records the `as_of` of its inputs and a monotonic sequence
number per store. Recording the wall clock would make every replay a different artefact and the determinism
guarantee untestable, which is the same reason the contracts take `as_of` as data.

**What the pre-check is and is not.** It checks what can be checked mechanically before a call: that the caller
is permitted, that the inputs' provenance is fit for the purpose, that regime vintages agree, and that a
regulated output is not already claiming release. It is not a substitute for the Curator: it is the gate the
Curator's queue sits behind, and it says so.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from contracts.base import Provenance, RegulatedStatus, Reliability, canonical_json, content_id

#: Where traces are appended. One JSONL file, because a trace log is append-only by nature and a line-per-trace
#: file is the least that can go wrong.
DEFAULT_TRACE_PATH = Path(
    os.environ.get(
        "ANDERSCH_TRACE_PATH",
        Path(__file__).resolve().parents[1] / "orchestration" / "traces.jsonl",
    )
)

#: Whether the process-wide store writes to disk. Only when the path was configured explicitly. A test run that
#: silently appended to the real trace log would grow the evidence file with calls nobody made on behalf of a
#: client, which is a worse failure than a test leaving no trace at all.
PERSIST_TRACES = "ANDERSCH_TRACE_PATH" in os.environ

#: Reliability floor. Anything below this may not inform a call whose output is regulated.
MIN_RELIABILITY = os.environ.get("ANDERSCH_MIN_RELIABILITY", "derived")

_RELIABILITY_ORDER: dict[str, int] = {
    Reliability.PUBLISHED.value: 3,
    Reliability.DERIVED.value: 2,
    Reliability.INTERPOLATED.value: 1,
    Reliability.SYNTHETIC.value: 0,
}


class UnmediatedCall(RuntimeError):
    """Raised when an engine is called outside a mediated context.

    Structural, not advisory. Phase 5's gate says every engine call is wrapped; this is what makes that true
    rather than aspirational.
    """


class PreCheckFailed(RuntimeError):
    """Raised when the compliance pre-check refuses a call. Lists every finding, not only the first."""


class Escalation(RuntimeError):
    """Raised when a nested mediated context tries to acquire a permission its parent does not hold.

    Without this, the engine-room boundary has a hole in it: the Knowledge Agent may not call engines, but if its
    work reached any function that opens an Investment context, it would get there anyway. Contexts may narrow
    what is permitted; they may never widen it.
    """


class Severity(str, Enum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class Finding:
    """One thing the pre-check noticed."""

    rule: str
    severity: Severity
    passed: bool
    detail: str

    def line(self) -> str:
        mark = "pass" if self.passed else ("REFUSED" if self.severity is Severity.BLOCKING else "note")
        return f"[{mark}] {self.rule}: {self.detail}"


@dataclass(frozen=True)
class PreCheckResult:
    """The pre-check's verdict on one intended call."""

    engine: str
    agent: str
    purpose: str
    regulated: bool
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        return not self.refusals()

    def refusals(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.BLOCKING and not f.passed)

    def advisories(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ADVISORY and not f.passed)


@dataclass(frozen=True)
class Trace:
    """One mediated engine call, recorded so it can be replayed.

    `sequence` orders traces within a store. There is no wall-clock field: see the module docstring.
    """

    trace_id: str
    sequence: int
    engine: str
    agent: str
    purpose: str
    household_id: str | None
    #: The root call this trace belongs to. Nested contexts inherit it, so "everything behind this client's
    #: advice" is answerable even for the stages whose artefacts are not per-user. Without it, the shared Regime
    #: and ReturnSet a household was advised under would be missing from that household's audit trail, because
    #: they carry no household_id — correctly, since they are shared.
    correlation_id: str
    as_of: str
    #: Hash of the adapter's inputs, so a replay can prove it used the same ones without storing user data.
    inputs_digest: str
    #: The contract the call produced, by name and identity.
    produced: str | None
    produced_id: str | None
    idempotency_key: str | None
    regulated: bool
    pre_check_passed: bool
    findings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "engine": self.engine,
            "agent": self.agent,
            "purpose": self.purpose,
            "household_id": self.household_id,
            "correlation_id": self.correlation_id,
            "as_of": self.as_of,
            "inputs_digest": self.inputs_digest,
            "produced": self.produced,
            "produced_id": self.produced_id,
            "idempotency_key": self.idempotency_key,
            "regulated": self.regulated,
            "pre_check_passed": self.pre_check_passed,
            "findings": list(self.findings),
            "notes": list(self.notes),
        }


class TraceStore:
    """Append-only trace log.

    Append-only because a trace that can be edited is not evidence. A correction is a new trace referencing the
    old one, exactly as an FDT correction supersedes rather than edits.
    """

    def __init__(self, path: Path | str | None = None, persist: bool | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_TRACE_PATH
        #: A store given an explicit path persists; the default store persists only when one was configured.
        self.persist = (path is not None) if persist is None else persist
        self._traces: list[Trace] = []

    @classmethod
    def from_path(cls, path: Path | str) -> "TraceStore":
        """Rehydrate a store from its own log, so a later process can look a trace up and replay it.

        Found by the Phase 10 journey (DECISIONS.md M38). The store could *write* a log and `load_traces()` could
        read it back as dictionaries, but nothing turned those dictionaries back into `Trace` objects — so
        `get()` and `replay()` were unreachable to an auditor, who is by definition a different process on a
        different day. The audit trail was writable and unreadable, which is the least useful combination.

        Loaded stores do not persist: appending to a rehydrated store would duplicate lines already on disk.
        """
        store = cls(path=path, persist=False)
        target = Path(path)
        if not target.exists():
            return store
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            store._traces.append(
                Trace(
                    trace_id=str(payload["trace_id"]),
                    sequence=int(payload["sequence"]),
                    engine=str(payload["engine"]),
                    agent=str(payload["agent"]),
                    purpose=str(payload["purpose"]),
                    household_id=payload.get("household_id"),
                    correlation_id=str(payload.get("correlation_id", "")),
                    as_of=str(payload["as_of"]),
                    inputs_digest=str(payload["inputs_digest"]),
                    produced=payload.get("produced"),
                    produced_id=payload.get("produced_id"),
                    idempotency_key=payload.get("idempotency_key"),
                    regulated=bool(payload.get("regulated", False)),
                    pre_check_passed=bool(payload.get("pre_check_passed", False)),
                    findings=tuple(payload.get("findings", ())),
                    notes=tuple(payload.get("notes", ())),
                )
            )
        return store

    def next_sequence(self) -> int:
        return len(self._traces)

    def append(self, trace: Trace, persist: bool | None = None) -> Trace:
        self._traces.append(trace)
        if self.persist if persist is None else persist:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(trace.to_dict(), round_floats=False) + "\n")
        return trace

    def all(self) -> tuple[Trace, ...]:
        return tuple(self._traces)

    def get(self, trace_id: str) -> Trace:
        for trace in self._traces:
            if trace.trace_id == trace_id:
                return trace
        raise KeyError(f"no trace {trace_id!r} in this store")

    def for_household(self, household_id: str) -> tuple[Trace, ...]:
        """Traces whose own artefact is about this household."""
        return tuple(t for t in self._traces if t.household_id == household_id)

    def for_correlation(self, correlation_id: str) -> tuple[Trace, ...]:
        return tuple(t for t in self._traces if t.correlation_id == correlation_id)

    def behind_household(self, household_id: str) -> tuple[Trace, ...]:
        """Every trace that informed this household's advice, including the shared stages.

        This is the audit answer, and it is deliberately wider than `for_household`. The Regime and the ReturnSet
        carry no household_id — they are shared artefacts, and stamping a household on them would misrepresent
        what they are — but they are exactly what a regulator asking "on what basis" wants to see.
        """
        correlations = {t.correlation_id for t in self.for_household(household_id)}
        return tuple(t for t in self._traces if t.correlation_id in correlations)

    def unmediated_count(self) -> int:
        """How many times the bypass hatch was opened this process. Readable on purpose."""
        return _BYPASS_COUNT["count"]

    def replay_count(self) -> int:
        """How many replays ran. Counted apart from bypasses: a replay is the control plane checking its own
        evidence, not someone stepping around it, and conflating the two would make the bypass count useless as a
        governance signal."""
        return _BYPASS_COUNT["replays"]


#: The process-wide store. A single log, because interleaved calls from several agents are exactly what a trace
#: log is for. It keeps every trace in memory always, and writes them only where configured to.
STORE = TraceStore(persist=PERSIST_TRACES)


def configure_traces(path: Path | str | None = None, persist: bool = True) -> TraceStore:
    """Turn on trace persistence at runtime, and say where.

    **Why this exists.** `PERSIST_TRACES` is read from the environment at *import* time, so whether the audit
    trail is written depended on import order relative to that variable being set. Anything that imported the
    control plane first — a conftest, a sibling module, a test runner — froze persistence off, and the traces then
    vanished silently. The failure surfaces only when an auditor needs a trace and finds an empty log, which is
    the worst moment and the worst possible symptom.

    Found by running the Phase 10 journey under pytest, where it passed standalone and failed in the suite for
    exactly this reason. Recorded as DECISIONS.md M40.

    The environment variable still works for deployment convenience. This is the explicit route, and an
    application that cares about its audit trail should call it rather than trust an import order it does not
    control.
    """
    if path is not None:
        STORE.path = Path(path)
        STORE.path.parent.mkdir(parents=True, exist_ok=True)
    STORE.persist = persist
    return STORE


# ---------------------------------------------------------------------------
# The mediated call context
# ---------------------------------------------------------------------------


@dataclass
class CallContext:
    """The open mediation. Held in a ContextVar so the guard can find it without being passed around."""

    agent: str
    purpose: str
    household_id: str | None
    may_call_engines: bool
    regulated: bool
    store: TraceStore
    #: Names the root call. Set on the outermost context and inherited by every nested one.
    correlation_id: str = ""
    pre_check: PreCheckResult | None = None
    recorded: list[Trace] = field(default_factory=list)


_CONTEXT: ContextVar[CallContext | None] = ContextVar("andersch_call_context", default=None)
_BYPASS_COUNT: dict[str, int] = {"count": 0, "replays": 0}
_BYPASS_REASONS: list[str] = []


def active_context() -> CallContext | None:
    return _CONTEXT.get()


def require_mediation(engine: str) -> CallContext:
    """The guard. Called from `EngineAdapter.result()`, the chokepoint every engine passes through.

    Raises:
        UnmediatedCall: When no mediation is open, and no explicit bypass is active.
    """
    context = _CONTEXT.get()
    if context is None:
        raise UnmediatedCall(
            f"engine {engine!r} was called outside a mediated context. Every engine call must pass the "
            f"control-plane pre-check and emit a trace (Phase 5 gate). Wrap it:\n"
            f"  with mediate(agent='investment', purpose='...') as call:\n"
            f"      engines.get({engine!r}).run(...)\n"
            f"For a tool or a test that legitimately bypasses this, use allow_unmediated('why'), which records "
            f"the bypass rather than hiding it."
        )
    if not context.may_call_engines:
        raise UnmediatedCall(
            f"the {context.agent!r} agent may not call engines. Only the Investment Agent calls engines, per "
            f"the architecture's engine-room boundary. Route the request through it."
        )
    return context


@contextmanager
def allow_unmediated(reason: str) -> Iterator[None]:
    """Permit unmediated engine calls inside this block, and record that it happened.

    For tools, smoke tests and exploratory work. Deliberately noisy: the count and the reasons are readable, so
    a testing convenience cannot quietly become production practice.
    """
    if not reason.strip():
        raise ValueError("a bypass must state its reason, so it can be reviewed later")
    _BYPASS_COUNT["count"] += 1
    _BYPASS_REASONS.append(reason.strip())
    with _unattributed_context("bypass", reason.strip()):
        yield


@contextmanager
def _unattributed_context(agent: str, purpose: str) -> Iterator[None]:
    """A context that permits engine calls without attributing them to a client request.

    Shared by the bypass hatch and by replay. Deliberately not public: the two callers count differently, and a
    third caller would need to say which it is.
    """
    token = _CONTEXT.set(
        CallContext(
            agent=agent,
            purpose=purpose,
            household_id=None,
            may_call_engines=True,
            regulated=False,
            store=STORE,
            correlation_id=content_id("CO", {"agent": agent, "purpose": purpose}),
        )
    )
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def bypasses() -> tuple[str, ...]:
    """Every reason an unmediated call was permitted this process. Readable on purpose."""
    return tuple(_BYPASS_REASONS)


@contextmanager
def mediate(
    agent: str,
    purpose: str,
    household_id: str | None = None,
    regulated: bool = False,
    may_call_engines: bool = True,
    store: TraceStore | None = None,
    inputs: Any = None,
    strict: bool = True,
) -> Iterator[CallContext]:
    """Open a mediated context: run the pre-check, then permit engine calls, then keep the traces.

    Args:
        agent: Which agent is calling. Only `investment` may call engines in normal operation.
        purpose: Why. Recorded on every trace, so a log is readable a year later.
        household_id: Whose data, when per-user.
        regulated: Whether the intended output crosses the wall. Tightens the pre-check.
        may_call_engines: Overridden to False for agents that are not the Investment Agent.
        inputs: What the pre-check should examine: provenance, references, contracts.
        strict: Raise on a refusal. False returns a context whose `pre_check` records the refusal, for a caller
            that wants to report rather than raise.

    Nesting is allowed and useful — the per-user path opens one context and the shared path it calls opens
    another — but a nested context may only *narrow* what its parent permits. See `Escalation`.

    Raises:
        PreCheckFailed: When the pre-check refuses and `strict` is set.
        Escalation: When this context would grant a permission the enclosing one lacks.
    """
    parent = _CONTEXT.get()
    if parent is not None:
        if may_call_engines and not parent.may_call_engines:
            raise Escalation(
                f"the {agent!r} context would gain engine access inside the {parent.agent!r} context, which does "
                f"not have it. A nested context may narrow permissions, never widen them: otherwise any agent "
                f"could reach the engine room by calling code that opens an Investment context."
            )
        if regulated and not parent.regulated and parent.agent != "bypass":
            raise Escalation(
                f"the {agent!r} context would produce regulated output inside the {parent.agent!r} context, "
                f"which was opened as unregulated. Declare the outer call regulated instead, so the pre-check "
                f"that guards the wall runs on the whole call and not just its inner part."
            )
        if (
            household_id is not None
            and parent.household_id is not None
            and household_id != parent.household_id
        ):
            raise Escalation(
                f"this context is about household {household_id!r} inside a context about "
                f"{parent.household_id!r}. One call serves one household; crossing them is how one client's "
                f"data reaches another's advice."
            )

    result = pre_check(
        engine="(context)",
        agent=agent,
        purpose=purpose,
        regulated=regulated,
        inputs=inputs,
    )
    if strict and not result.passed:
        raise PreCheckFailed(
            f"the control-plane pre-check refused this call ({len(result.refusals())} finding(s)):\n  "
            + "\n  ".join(f.line() for f in result.refusals())
        )

    context = CallContext(
        agent=agent,
        purpose=purpose,
        household_id=household_id,
        may_call_engines=may_call_engines,
        regulated=regulated,
        store=store or STORE,
        # A nested context inherits the root's correlation, so the whole call is one auditable unit however many
        # sub-paths it opens.
        correlation_id=(
            parent.correlation_id
            if parent is not None and parent.correlation_id
            else content_id(
                "CO", {"agent": agent, "purpose": purpose, "household_id": household_id}
            )
        ),
        pre_check=result,
    )
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


def record(
    engine: str,
    inputs: Any,
    produced: Any,
    idempotency_key: str | None,
    as_of: str,
    notes: Sequence[str] = (),
) -> Trace | None:
    """Append a trace for a completed engine call. Called from `EngineAdapter.result()`.

    Returns None when there is no open context, which only happens under `allow_unmediated`.
    """
    context = _CONTEXT.get()
    if context is None:
        return None

    produced_name = type(produced).__name__ if produced is not None else None
    produced_id = None
    for attribute in (
        "snapshot_id", "recommendation_id", "record_id", "trajectory_id", "scenario_id",
        "score_id", "event_id",
    ):
        candidate = getattr(produced, attribute, None)
        if callable(candidate):
            produced_id = candidate()
            break
    if produced_id is None:
        for attribute in ("regime_id", "return_set_id"):
            value = getattr(produced, attribute, None)
            if isinstance(value, str):
                produced_id = value
                break

    regulated = getattr(type(produced), "REGULATED", None)
    is_regulated = regulated is RegulatedStatus.REGULATED if regulated else context.regulated

    digest = content_id("IN", inputs if inputs is not None else {})
    trace_id = content_id(
        "TR",
        {
            "engine": engine,
            "agent": context.agent,
            "purpose": context.purpose,
            "inputs": digest,
            "produced": produced_id,
        },
    )
    trace = Trace(
        trace_id=trace_id,
        sequence=context.store.next_sequence(),
        engine=engine,
        agent=context.agent,
        purpose=context.purpose,
        household_id=context.household_id,
        correlation_id=context.correlation_id,
        as_of=as_of,
        inputs_digest=digest,
        produced=produced_name,
        produced_id=produced_id,
        idempotency_key=idempotency_key,
        regulated=is_regulated,
        pre_check_passed=bool(context.pre_check.passed) if context.pre_check else False,
        findings=tuple(
            f.line() for f in (context.pre_check.findings if context.pre_check else ())
        ),
        notes=tuple(notes),
    )
    context.store.append(trace)
    context.recorded.append(trace)
    return trace


# ---------------------------------------------------------------------------
# The compliance pre-check
# ---------------------------------------------------------------------------


def pre_check(
    engine: str,
    agent: str,
    purpose: str,
    regulated: bool = False,
    inputs: Any = None,
) -> PreCheckResult:
    """What can be checked mechanically before a call.

    It is not a substitute for the Curator. It is the gate the Curator's queue sits behind: it establishes that
    a Recommendation is *fit to be reviewed*, not that it is fit to be acted on.
    """
    findings: list[Finding] = [
        _caller_is_stated(agent),
        _purpose_is_stated(purpose),
    ]
    findings.extend(_provenance_is_fit(inputs, regulated))
    findings.append(_regime_vintages_agree(inputs))
    findings.append(_nothing_claims_release(inputs))
    if regulated:
        findings.append(
            Finding(
                "regulated output needs a Curator",
                Severity.ADVISORY,
                False,
                "this call produces a regulated output, so it is analysis until a Curator confirms it and a "
                "Decision Record is written. The pre-check does not authorise delivery.",
            )
        )
    return PreCheckResult(
        engine=engine,
        agent=agent,
        purpose=purpose,
        regulated=regulated,
        findings=tuple(findings),
    )


def _caller_is_stated(agent: str) -> Finding:
    ok = bool(agent and agent.strip())
    return Finding(
        "caller is stated",
        Severity.BLOCKING,
        ok,
        f"agent {agent!r}" if ok else "no calling agent was named, so the trace would be unattributable",
    )


def _purpose_is_stated(purpose: str) -> Finding:
    ok = bool(purpose and purpose.strip())
    return Finding(
        "purpose is stated",
        Severity.BLOCKING,
        ok,
        purpose if ok else "no purpose was given, and a trace log without purposes is unreadable later",
    )


def _provenance_is_fit(inputs: Any, regulated: bool) -> list[Finding]:
    """Refuse synthetic provenance behind a regulated output, and report the floor otherwise."""
    found = list(_walk_provenance(inputs))
    if not found:
        return [
            Finding(
                "provenance is fit",
                Severity.ADVISORY,
                False,
                "no provenance was found on the inputs, so reliability could not be established",
            )
        ]

    floor = _RELIABILITY_ORDER.get(MIN_RELIABILITY, 2)
    worst = min(found, key=lambda p: _RELIABILITY_ORDER.get(p.reliability.value, 0))
    worst_rank = _RELIABILITY_ORDER.get(worst.reliability.value, 0)

    synthetic = [p for p in found if p.reliability is Reliability.SYNTHETIC]
    out: list[Finding] = []
    if synthetic and regulated:
        out.append(
            Finding(
                "no synthetic data behind advice",
                Severity.BLOCKING,
                False,
                f"{len(synthetic)} input(s) declare synthetic provenance and this call produces a regulated "
                f"output. Synthetic values must never reach advice.",
            )
        )
    else:
        out.append(
            Finding(
                "no synthetic data behind advice",
                Severity.BLOCKING,
                True,
                "no synthetic provenance reaches a regulated output",
            )
        )

    out.append(
        Finding(
            "reliability floor",
            Severity.ADVISORY,
            worst_rank >= floor,
            f"the weakest input is {worst.reliability.value!r} from {worst.source!r}; the configured floor is "
            f"{MIN_RELIABILITY!r}",
        )
    )
    return out


def _walk_provenance(node: Any, depth: int = 0) -> Iterator[Provenance]:
    """Find every Provenance on the inputs, however nested."""
    if depth > 6 or node is None:
        return
    if isinstance(node, Provenance):
        yield node
        return
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _walk_provenance(value, depth + 1)
        return
    if isinstance(node, (list, tuple, set)):
        for value in node:
            yield from _walk_provenance(value, depth + 1)
        return
    provenance = getattr(node, "provenance", None)
    if isinstance(provenance, Provenance):
        yield provenance
    for attribute in ("diagnostics", "outcome", "evidence"):
        nested = getattr(node, attribute, None)
        if nested is not None:
            yield from _walk_provenance(nested, depth + 1)


def _regime_vintages_agree(inputs: Any) -> Finding:
    """No mixing of regime vintages, checked across whatever references the inputs carry."""
    ids: set[str] = set()
    for node in _walk_regime_ids(inputs):
        ids.add(node)
    if len(ids) <= 1:
        return Finding(
            "regime vintages agree",
            Severity.BLOCKING,
            True,
            f"one regime vintage: {next(iter(ids))}" if ids else "no regime reference on the inputs",
        )
    return Finding(
        "regime vintages agree",
        Severity.BLOCKING,
        False,
        f"the inputs carry {len(ids)} regime vintages ({sorted(ids)}). Mixing them means optimising a profile "
        f"estimated under one macro state against the weights of another.",
    )


def _walk_regime_ids(node: Any, depth: int = 0) -> Iterator[str]:
    if depth > 6 or node is None:
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "regime_id" and isinstance(value, str):
                yield value
            else:
                yield from _walk_regime_ids(value, depth + 1)
        return
    if isinstance(node, (list, tuple, set)):
        for value in node:
            yield from _walk_regime_ids(value, depth + 1)
        return
    value = getattr(node, "regime_id", None)
    if isinstance(value, str):
        yield value
    for attribute in ("regime", "returnset", "shared"):
        nested = getattr(node, attribute, None)
        if nested is not None and nested is not node:
            yield from _walk_regime_ids(nested, depth + 1)


def _nothing_claims_release(inputs: Any) -> Finding:
    """An input already claiming release has bypassed the wall somewhere upstream."""
    released = [
        node
        for node in _walk_released(inputs)
        if node
    ]
    if released:
        return Finding(
            "no input claims release",
            Severity.BLOCKING,
            False,
            f"{len(released)} input(s) arrive already released. A Recommendation is released only by a Decision "
            f"Record, so this indicates the wall was bypassed upstream.",
        )
    return Finding("no input claims release", Severity.BLOCKING, True, "nothing claims release")


def _walk_released(node: Any, depth: int = 0) -> Iterator[bool]:
    if depth > 5 or node is None:
        return
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _walk_released(value, depth + 1)
        return
    if isinstance(node, (list, tuple, set)):
        for value in node:
            yield from _walk_released(value, depth + 1)
        return
    value = getattr(node, "released", None)
    if isinstance(value, bool):
        yield value


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def replay(
    trace: Trace | str,
    rerun: Any,
    store: TraceStore | None = None,
) -> tuple[bool, str]:
    """Re-run a traced call and report whether it reproduced.

    Args:
        trace: The trace, or its id.
        rerun: A zero-argument callable that repeats the call and returns an `EngineResult`.
        store: Where to look the id up.

    Returns:
        `(reproduced, detail)`. Compares the `idempotency_key`, which is a pure function of the inputs and the
        model version, so a match means the same computation ran on the same inputs.
    """
    resolved = (store or STORE).get(trace) if isinstance(trace, str) else trace
    _BYPASS_COUNT["replays"] += 1
    with _unattributed_context("replay", f"replay of {resolved.trace_id}"):
        result = rerun()

    key = getattr(result, "idempotency_key", None)
    if resolved.idempotency_key is None:
        return False, "the original trace recorded no idempotency key, so it cannot be compared"
    if key == resolved.idempotency_key:
        return True, f"reproduced: idempotency key {key} matches"
    return False, (
        f"did not reproduce: the trace recorded {resolved.idempotency_key} but the replay produced {key}. "
        f"Either an input moved or a model version changed."
    )


def load_traces(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Read a trace log back. Every line is one trace."""
    target = Path(path) if path is not None else DEFAULT_TRACE_PATH
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out
