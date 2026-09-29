"""R-301's queue: a stored run, a worker thread, and a poll. C-03, C-04, C-09, R-302, R-303.

**The problem this closes, in one sentence.** All seven engines were wired in A69 and `call_engine` had
exactly one caller — `tools/publish_assumption_set.py`, at a terminal — because R-301 forbids an engine on a
request thread (the fastest declares 30 s, the slowest 1800; the HTTP budget is two) and the queue R-301
tells you to build instead was never built. So the engines were reachable from a keyboard and from nothing
a member touches.

===========================================================================================================
THE DESIGN, AND WHY IT IS THIS SMALL
===========================================================================================================

**A table and a thread. No broker, no dependency, no second process.** The choice is not about taste, it is
about what has to survive. eigentliCH prototype2 is a local single-user application: one process, one SQLite
file, one person at a keyboard, started by a desktop icon (A47) on a naked laptop. Weighed and rejected:

  * **Celery / RQ / arq.** Each adds a broker to install and keep running, a second answer to "what is the
    status of this run", and a deployment story the distribution ZIP has no way to carry. A47's whole point
    is that a friend unzips a folder and it works.
  * **`BackgroundTasks`.** FastAPI's own answer, and wrong here twice: the task dies with the process
    holding no record, and it runs *after the response on the same worker* — a 1800-second engine would
    occupy an HTTP worker for half an hour, which is R-301's problem wearing a different hat.
  * **A `queue.Queue` beside the table.** The nearest miss, and rejected on this estate's own history: it
    would put a run's state in two places, and two stores of one fact drift. A63's triggers and A40's
    `curator_id` were both exactly that. The table is the queue; the in-memory part is a `threading.Event`
    that carries no state and only saves a poll interval of latency.

So: **the row is the queue and the row is the status.** `SELECT ... WHERE status = 'submitted'` is the
pending list, the HTTP poll reads the same row the worker writes, and there is nothing in memory a restart
could lose without leaving a trace. A run interrupted by a restart is a `running` row with no `finished_at`;
`recover_interrupted_runs` resolves it on the next start rather than letting it look pending forever.

===========================================================================================================
THE CONSTRAINTS, AND WHERE EACH ONE IS ACTUALLY HELD
===========================================================================================================

**R-301 — never on a request thread.** Held *structurally*, not by a check: there is no code path from a
route to a synchronous engine call. `submit` and `queue` write a row and return; the only `call_engine` in
this module is inside `RunWorker.run_once`, which only the worker thread reaches. `serving_request()` re-exports the
engine layer's thread flag as belt and braces for the route that is *about* engines, and
`tests/test_runs.py::test_submitting_a_run_never_calls_an_engine` holds the structural half by making
`call_engine` explode and submitting anyway.

**R-302 — a failed run carries no number.** `describe_run` builds the failed payload from a separate,
shorter allowlist that contains no numeric field at all: not the timeout it was given, not a duration, not
a zero. The reason R-302 exists is that a screen reading a `0` out of an engine response cannot tell it
from a measurement, and the only way to keep that true is for there to be nothing there to read.
`test_a_failed_run_carries_no_number_at_any_depth` scans recursively rather than at the top level.

**R-303 / C-04 — nothing about a run is logged beyond ids and status.** `_log` builds a dict of exactly
`run_id`, `engine` and `status` and passes it through `engines.redacted()` before formatting. Passing three
non-sensitive fields through a redactor looks redundant and is the point: the discipline becomes structural
rather than a comment, so a later hand adding `member_id` to that dict is redacted by the code instead of
being caught in review. `test_the_run_log_line_goes_through_the_one_redactor` plants exactly that.

  *The payload is never logged here, and neither is the reason.* An engine's failure detail carries the
  estate's stderr and can quote the payload it was handed straight back; `reason` is stored on the row (K2,
  in the database) and `detail` is discarded entirely. **A traceback is not logged either**, which is a real
  cost stated rather than hidden: when a run fails because of a defect in *this* codebase, the exception
  type is on the row and the stack is not anywhere. That is the trade C-04 asks for, and the row is where
  to look.

  **One residual, recorded rather than papered over.** `engines._log_call` logs the engine payload at INFO
  with the member *reference* stripped — that is R-303 as the specification writes it. The member's own
  *values* (a goal's target amount, a horizon read off their date) are not references and are not stripped,
  so they appear in that line. The queue adds no log line of its own beyond ids and status; changing what
  R-303 means is a specification question and is not taken here. See A85 in DECISIONS.md.

**C-03 / R-304 — no engine artefact reachable from the browser.** The reply is reduced to
`MEMBER_FACING_RESULT_KEYS` and then run through `services/served.py` twice: `strip_artefacts` removes the
published-artefact keys, `assert_no_engine_artefact` refuses the write if one survived. Done **on the way
in**, so the stored row, the HTTP poll and the R-154 export are covered by one pass rather than by three
call sites remembering.

**C-09 — a run never writes to the plan.** Nothing in this module touches `positions` or `goals`, and the
guard in `db.py` covers the other direction for free: the worker thread has never been through
`before_flush`, so `_refuse_unvetted_plan_dml` refuses a raw plan write from it — correctly, and
`test_a_worker_thread_cannot_write_to_the_plan` proves it fires. If a run's result ever *should* enter the
plan, it goes through `services.plan.mutate_plan`, which writes the Decision C-09 requires in the same
transaction.

**`portfolio_optimiser` was not member-requestable until 20 September 2026, and now is (A166).** It
produces a Recommendation: ranked instruments. It was refused outright under C-01, closed in the
restrictive direction on A81's reasoning — a permission added on purpose is reviewable, one left behind
is not.

C-01 is withdrawn (A164) and the authorisation that refusal was holding the engine for is no longer being
sought. T2.4 of the cull task proposed removing the condition and putting a curator's release record in
its place; **the owner refused the release gate (T2.1), so the condition was removed and nothing was put
in its place.** A member can now queue an allocation and read the result. Whether a curator saw it first
is not a fact this system records, and after this change nothing makes it one.

It is still refused when the plan cannot answer it — its `mandate` gap is real — but that is a shortfall
of inputs, not a control, and A81's own warning applies: a guard that depends on an unrelated gap is not
a guard. If the `mandate` gap is ever filled, nothing else stands here.

===========================================================================================================
WHAT A MEMBER CAN ACTUALLY GET OUT OF THIS TODAY, STATED PLAINLY
===========================================================================================================

`services/engine_inputs.py` is the map, and read honestly it says: **of the seven engines, one is genuinely
runnable from a member's plan.** `market_signal` reads no member data and its plan is complete.
`return_estimation` is complete except for a `regime_id` the caller must carry over from a `market_signal`
run. The four member engines each want something the plan does not hold — a wealth stock in francs, a
mandate, an event stream, months of observed conduct — and A69 recorded those as absent rather than
defaulted. Nothing here defaults one.

So `submit` refuses four of the seven with the gap list attached, and that refusal is the honest answer
rather than a shortfall in this module: the queue's job is to make what *can* run reachable and to say
precisely why the rest cannot. Running `market_signal` is not a consolation prize — it is what republishes
the Regime the AssumptionSet is read from, which is what every goal illustration is stamped with (C-02).
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Callable, Iterator

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ..engines import (
    EngineNotAvailable,
    call_engine,
    known_engines,
    load_manifest,
    mark_request_thread,
    redacted,
)
from ..models import DONE, EngineRun, FAILED, Goal, Position, RUNNING, SUBMITTED, utcnow
from .engine_inputs import AbsentInput, plan_for
from .served import assert_no_engine_artefact, strip_artefacts

logger = logging.getLogger("eigentlich.runs")

# ---------------------------------------------------------------------------
# Tuning. Milliseconds as integers, not seconds as floats.
#
# C-02's `test_no_literal_rate_in_application_code` forbids a float literal anywhere in the service layer,
# and it is right to: a bare number inline in a service is a knob nobody can find. `0.25` would break it.
# Expressing the interval in whole milliseconds keeps every literal here an integer and keeps the unit in
# the name, which is the more readable half of the trade.
# ---------------------------------------------------------------------------

#: How long the worker waits for a wake-up before looking at the table anyway. The `Event` makes a run
#: start within microseconds of being committed; this is the fallback for a row that appeared by some other
#: route — a second process, a tool, a row left `submitted` by a restart.
POLL_INTERVAL_MS = 2000

#: How long `stop()` waits for a worker to notice. It does not interrupt a running engine: an engine
#: subprocess is killed by its own timeout and nothing here is entitled to leave a half-finished run
#: unrecorded, so shutdown waits for the *loop* to exit and lets the current run finish or be recovered.
STOP_TIMEOUT_MS = 5000

MILLISECONDS_PER_SECOND = 1000

#: R-304 / C-03. The only keys of an engine reply that may be stored on a run and served to a member.
#:
#: **An allowlist, because a denylist passes whatever an engine version adds next.** Absent by name and by
#: intent: `raw` (the engine's internals), `replay` (the command that runs it by hand), `artefact` (the
#: published contract itself), and `idempotency_key`. `contract` is kept and then stripped of the
#: artefact-naming keys inside it — `regime_timeline_id`, `return_set_id` — which is the one place C-03
#: costs something real: the member-facing record of a `return_estimation` run does not name the ReturnSet
#: it produced. The full provenance is in the AssumptionSet, which is K0 and served to nobody.
MEMBER_FACING_RESULT_KEYS = ("engine", "contract_type", "contract", "model_version", "as_of", "notes", "trace_id")

#: **Empty since 20 September 2026 (A166).** It held `portfolio_optimiser`, refused to members under C-01
#: because its output ranks instruments. C-01 is withdrawn (A164) and the FINMA authorisation the refusal
#: was waiting on is no longer being sought, so the condition is gone and **nothing replaced it**: the
#: owner refused the release gate that T2.1 proposed, so there is no release record between the
#: computation and the member. A member can request an allocation and read what comes back.
#:
#: The tuple is kept rather than deleted because `submit` reads it and because an engine may yet need to
#: be curator-only for a reason that is not regulatory. Empty, it says that today none is.
CURATOR_ONLY_ENGINES: tuple[str, ...] = ()

#: The refusal reasons `submit` can give, named once so the API, the client and the tests cannot drift.
#: Every one is derived from `EnginePlan`, never from a list of special cases.
REFUSAL_REASONS = (
    "unknown_engine",
    "requires_a_curator",
    "the_plan_does_not_answer_this_engine",
    "requires_an_input_the_member_did_not_supply",
)


class UnknownEngine(Exception):
    """R-300. An engine with no manifest is not callable, and not queueable either."""


class NotQueueable(Exception):
    """The run was refused before anything was queued, and why — with the gaps attached.

    R-302's shape one step earlier: a refusal to *start* carries a reason and no number, for the same
    reason a failed run does. The gaps come from `services/engine_inputs.py` verbatim, so a screen can
    show the member which of their own inputs is missing rather than a sentence about engines.
    """

    def __init__(self, engine: str, reason: str, *, gaps: tuple[AbsentInput, ...] = ()) -> None:
        super().__init__(f"{engine}: {reason}")
        self.engine = engine
        self.reason = reason
        self.gaps = gaps

    def as_dict(self) -> dict:
        return {
            "queued": False,
            "engine": self.engine,
            "reason": self.reason,
            "absent": [gap.as_dict() for gap in self.gaps],
        }


# ===========================================================================================
# R-301, restated as a context manager so the API layer can reach it without importing engines
# ===========================================================================================


@contextmanager
def serving_request() -> Iterator[None]:
    """Mark this thread as serving an HTTP request, so `call_engine` refuses on it (R-301).

    **Why this lives here and not in `api/`.** `tests/test_constraints.py` forbids the API package from
    importing the engine façade at all — the strong form of C-03, because a module that can reach
    `call_engine` can also serialise its output. So the flag is re-exported through the service layer,
    which is the same route `services/engine_inputs.py` already takes.

    **What it is and is not.** It is belt and braces. The guarantee that no engine runs on a request
    thread is *structural* — no route can reach a synchronous engine call, because `submit` writes a row
    and returns — and this is the second net under it, for the day somebody adds a call to a route by
    hand. It is used by `api/runs.py`, which is the surface that is about engines; it is not applied to
    every route in the application, and pretending otherwise would be the kind of claim A71 was about.
    """
    mark_request_thread(True)
    try:
        yield
    finally:
        mark_request_thread(False)


# ===========================================================================================
# Submitting
# ===========================================================================================


def _log(stage: str, run_id: str, engine: str, status: str) -> None:
    """C-04 / R-303: ids and status, and nothing else, ever.

    The dict goes through `engines.redacted()` — the one redactor in this codebase, per R-303 — before it
    is rendered. Three fields that carry no member reference do not need redacting today; running them
    through it anyway is what makes the promise structural, so a later hand adding `member_id` or `goal_id`
    to this dict is caught by the code rather than by whoever reviews it.
    """
    logger.info(
        "engine run %s: %s",
        stage,
        redacted({"run_id": run_id, "engine": engine, "status": status}),
    )


def queue(
    session: Session,
    *,
    engine: str,
    payload: dict,
    member_id: str | None = None,
) -> EngineRun:
    """Write one `submitted` run. The low-level door — no plan, no policy, no engine call.

    Used by `submit` and by `tools/`. It does not commit: the caller owns the transaction, because a run
    queued in a transaction that later rolls back must not exist.

    Raises:
        UnknownEngine: R-300 — an engine without a manifest is not callable, so it is not queueable.
    """
    if engine not in known_engines():
        raise UnknownEngine(
            f"R-300: {engine!r} has no manifest, so it is not callable and not queueable. Known engines: "
            f"{', '.join(known_engines())}."
        )
    run = EngineRun(
        member_id=member_id,
        engine=engine,
        status=SUBMITTED,
        payload=dict(payload),
        timeout_s=load_manifest(engine).timeout_s,
    )
    session.add(run)
    session.flush()
    _log("submitted", run.id, run.engine, run.status)
    return run


def submit(
    session: Session,
    *,
    engine: str,
    member_id: str,
    goal_id: str | None = None,
    today: date | None = None,
) -> EngineRun:
    """Queue a run for one member, with the payload built from their own plan. A39, R-301, C-01.

    **The member never supplies an engine payload.** They name an engine and, optionally, a goal; the
    payload is built by `services/engine_inputs.py` from the rows the plan already holds. A route that
    accepted engine inputs from a caller would be handing the estate arbitrary keys through a manifest
    check, which is A39's failure mode arriving from the other side — and `call_engine` refuses an
    undeclared key precisely so that this layer never has to be trusted about it.

    Raises:
        UnknownEngine: R-300.
        NotQueueable: C-01 for a ranking engine, or the plan does not answer what the engine needs. The
            gaps are attached and none of them is defaulted (A69, §12).
    """
    if engine not in known_engines():
        raise NotQueueable(engine, "unknown_engine")

    if engine in CURATOR_ONLY_ENGINES:
        # Empty since A166 — see the constant. The check is kept because the reason an engine might be
        # curator-only is not necessarily regulatory, and because it must still run BEFORE the plan is
        # read: a refusal that depends on an unrelated input gap continuing to exist is not a refusal
        # (A81). What is gone is the one entry that was there for C-01.
        raise NotQueueable(engine, "requires_a_curator")

    goal = None
    if goal_id is not None:
        goal = session.execute(
            select(Goal).where(Goal.id == goal_id, Goal.member_id == member_id)
        ).scalar_one_or_none()
        if goal is None:
            # 404-shaped, on A81's reasoning: a goal that is not this member's and a goal that does not
            # exist are the same answer, or the route becomes an oracle for other people's goal ids.
            raise NotQueueable(engine, "the_plan_does_not_answer_this_engine")

    positions = session.execute(
        select(Position).where(Position.member_id == member_id)
    ).scalars().all()

    plan = plan_for(engine, member_id=member_id, goal=goal, positions=positions, today=today)

    blocking = tuple(gap for gap in plan.absent if gap.blocks_the_plan)
    if blocking:
        raise NotQueueable(engine, "the_plan_does_not_answer_this_engine", gaps=blocking)

    from_caller = tuple(gap for gap in plan.absent if gap.kind == "supplied_by_the_caller")
    if from_caller:
        # Not a gap in the plan and not defaulted either. `return_estimation` wants the `regime_id` from
        # the `market_signal` run in the same sequence; `scenario_generator` wants the change the member
        # is asking about. Both are real parameters of a request, and inventing one here would be this
        # layer deciding what the member wanted to try (C-01).
        raise NotQueueable(engine, "requires_an_input_the_member_did_not_supply", gaps=from_caller)

    return queue(session, engine=engine, payload=plan.payload, member_id=member_id)


# ===========================================================================================
# Reading — the poll side
# ===========================================================================================


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _duration_ms(run: EngineRun) -> int | None:
    if run.started_at is None or run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * MILLISECONDS_PER_SECOND)


def describe_run(run: EngineRun) -> dict:
    """One run as a member-facing payload. R-302, C-03.

    **Two shapes, and the failed one is shorter on purpose.** A successful or pending run carries its
    timings and its declared budget; a failed run carries **no numeric field at all, at any depth** — not
    the timeout, not a duration, not a zero. R-302 says a failed engine renders as "not available", and a
    screen that can read a number out of a failure cannot tell it from a measurement.

    `available` mirrors `engines.attempt()`'s shape deliberately: the same two-branch contract, so a client
    written against one reads the other. There is no third branch and no `result` key on a failure.
    """
    common = {
        "run_id": run.id,
        "engine": run.engine,
        "status": run.status,
        "submitted_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }

    if run.status == FAILED:
        # Every value here is a string or None. Deliberately no `timeout_s` and no `duration_ms`.
        return assert_no_engine_artefact(
            {**common, "available": False, "reason": run.reason},
            where=f"failed run {run.id}",
        )

    payload: dict[str, Any] = {**common, "timeout_s": run.timeout_s}
    if run.status == DONE:
        payload["available"] = True
        payload["duration_ms"] = _duration_ms(run)
        payload["result"] = run.result
    return assert_no_engine_artefact(payload, where=f"run {run.id}")


def read_run(session: Session, *, run_id: str, member_id: str) -> EngineRun | None:
    """One of this member's runs, or None.

    Scoped by `member_id` in the query rather than checked after loading — A81's rule: a filter that is
    part of the SELECT cannot be forgotten by the next route, and the caller turns None into a 404 so that
    a run belonging to somebody else and a run that does not exist are indistinguishable.
    """
    return session.execute(
        select(EngineRun).where(EngineRun.id == run_id, EngineRun.member_id == member_id)
    ).scalar_one_or_none()


def list_runs(session: Session, *, member_id: str, limit: int = 50) -> dict:
    rows = session.execute(
        select(EngineRun)
        .where(EngineRun.member_id == member_id)
        .order_by(EngineRun.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return {"runs": [describe_run(run) for run in rows]}


# ===========================================================================================
# The worker
# ===========================================================================================


def _member_facing_result(reply: dict) -> dict:
    """An engine reply reduced to what may be stored and served. C-03 / R-304.

    Allowlist, then `strip_artefacts`, then refuse if a marker survived. Three passes rather than one
    because they fail differently: the allowlist drops whole fields nobody meant to serve, the strip
    handles a marker nested inside the contract, and the assertion is what turns a construction mistake
    into an exception instead of a disclosure.
    """
    kept = {key: reply[key] for key in MEMBER_FACING_RESULT_KEYS if key in reply}
    return assert_no_engine_artefact(strip_artefacts(kept), where="engine run result")


def recover_interrupted_runs(session: Session) -> int:
    """Resolve rows left `running` by a restart. Returns how many.

    **Failed, not re-queued.** An engine run takes minutes and reaches the network; silently starting one
    again on every application start is not a recovery, it is a loop nobody asked for. So the run is
    closed with a true reason and the member can ask again — which is the same shape R-302 gives every
    other failure, and it carries no number.

    Safe to run only at worker start, and only because there is exactly one worker per process: every
    `running` row at that moment belongs to a process that is gone.
    """
    rows = session.execute(select(EngineRun).where(EngineRun.status == RUNNING)).scalars().all()
    for run in rows:
        run.status = FAILED
        run.reason = "the application stopped while this run was in progress; it was not completed"
        run.finished_at = utcnow()
        _log("recovered", run.id, run.engine, run.status)
    if rows:
        session.commit()
    return len(rows)


class RunWorker:
    """One thread, executing queued runs off every request thread. R-301.

    **`run_once` is the whole engine of this class and takes no thread.** The loop is four lines around it.
    That split is deliberate: a test drives `run_once` directly and exercises the real claim, the real
    session handling and the real C-03 reduction with no thread, no sleep and no flake. Everything that
    could only be tested by waiting is therefore only the waiting.

    `call` is injectable for the same reason and no other. `test_the_default_call_is_the_real_engine_facade`
    pins the default to `call_engine`, so the injection point cannot quietly become a permanent stub — A20's
    hazard, which is the one this estate keeps paying for.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        call: Callable[..., dict] = call_engine,
        poll_interval_ms: int = POLL_INTERVAL_MS,
    ) -> None:
        self._sessions = session_factory
        self._call = call
        self._poll_interval_ms = poll_interval_ms
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------------------------

    def start(self) -> None:
        """Idempotent. Recovers interrupted runs first, then starts the thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        with self._sessions() as session:
            recover_interrupted_runs(session)
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="eigentlich-runs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the loop to exit and wait for it. Does not interrupt a run that is already executing."""
        self._stopping.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=STOP_TIMEOUT_MS / MILLISECONDS_PER_SECOND)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wake(self) -> None:
        """Tell the worker there is something to do. Call it **after** the commit.

        Waking before the commit is not a bug — the worker would see nothing and the poll interval would
        pick the row up — but it turns an instant start into a two-second one for no reason.
        """
        self._wake.set()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait(timeout=self._poll_interval_ms / MILLISECONDS_PER_SECOND)
            self._wake.clear()
            while not self._stopping.is_set() and self.run_once():
                pass

    # -- the work -------------------------------------------------------------------------

    def _claim(self) -> tuple[str, str, dict, int | None] | None:
        """Take the oldest submitted run and mark it `running`, in its own short transaction.

        **A conditional UPDATE, not a read-then-write.** `WHERE id = ... AND status = 'submitted'` with a
        `rowcount` check means two workers cannot both claim one run. There is only ever one worker per
        process today; writing the claim as a claim rather than as an assignment is what keeps that a
        property of the code instead of a property of nobody having added a second one yet.

        **The transaction ends before the engine starts.** An engine may take half an hour, and holding a
        SQLite write transaction open across it would block every other write in the application. So the
        run's fields are copied out and the session is closed.
        """
        with self._sessions() as session:
            run = session.execute(
                select(EngineRun)
                .where(EngineRun.status == SUBMITTED)
                .order_by(EngineRun.created_at)
                .limit(1)
            ).scalar_one_or_none()
            if run is None:
                return None

            claimed = session.execute(
                update(EngineRun)
                .where(EngineRun.id == run.id, EngineRun.status == SUBMITTED)
                .values(status=RUNNING, started_at=utcnow())
            )
            if claimed.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            _log("running", run.id, run.engine, RUNNING)
            return run.id, run.engine, dict(run.payload), run.timeout_s

    def _finish(self, run_id: str, *, status: str, result: dict | None, reason: str | None) -> None:
        with self._sessions() as session:
            run = session.get(EngineRun, run_id)
            if run is None:  # pragma: no cover - the row is this worker's own claim
                return
            run.status = status
            run.result = result
            run.reason = reason
            run.finished_at = utcnow()
            session.commit()
            _log("finished", run.id, run.engine, run.status)

    def run_once(self) -> bool:
        """Execute one queued run if there is one. Returns whether it did.

        **Every exception ends the run and none ends the worker.** `engines.attempt()` deliberately does
        NOT catch `EngineOnRequestThread` or `UndeclaredInput`, because degrading them would hide a broken
        constraint behind a polite message — and that is right for a synchronous caller who can see the
        traceback. A worker thread has nobody to raise at: letting one through would kill the loop and
        leave the row `running` forever, which is the same defect with the evidence deleted. So a defect is
        recorded on the row, marked as a defect in eigentliCH rather than an engine failure, and the loop
        continues.

        The reason for a defect is the exception **type** and not its message. `UndeclaredInput` names
        manifest keys and would be safe; the rule is not per-exception, because the next exception type is
        written by somebody who has not read this docstring.
        """
        claim = self._claim()
        if claim is None:
            return False
        run_id, engine, payload, timeout_s = claim

        try:
            reply = self._call(engine, payload, timeout_s=timeout_s, purpose=f"queued run {run_id}")
            # **Inside the `try` deliberately.** The C-03 reduction can raise — `assert_no_engine_artefact`
            # refuses rather than filtering — and it was outside this block until a test planted an
            # artefact id inside an engine note and the exception escaped `run_once`, killing the loop and
            # leaving the row `running`. A guard that raises has to be somewhere the raise is handled.
            result = _member_facing_result(reply)
        except EngineNotAvailable as error:
            # R-302's own case: the engine did not run, or ran and produced nothing usable. `error.detail`
            # is deliberately dropped — it carries the estate's stderr, which can quote the payload.
            self._finish(run_id, status=FAILED, result=None, reason=error.reason)
        except Exception as defect:  # noqa: BLE001 - recorded on the row, never swallowed silently
            self._finish(
                run_id,
                status=FAILED,
                result=None,
                reason=f"a defect in eigentliCH rather than an engine failure: {type(defect).__name__}",
            )
        else:
            self._finish(run_id, status=DONE, result=result, reason=None)
        return True


# ===========================================================================================
# The one worker this process has
# ===========================================================================================

_worker: RunWorker | None = None
_worker_lock = threading.Lock()


def start_worker(session_factory: sessionmaker[Session], **kwargs: Any) -> RunWorker:
    """Start the process's worker on an explicit session factory. Idempotent.

    A module-level singleton rather than something on `app.state`, because `tools/` and a REPL need the
    same one and neither has a FastAPI app.
    """
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = RunWorker(session_factory, **kwargs)
        _worker.start()
        return _worker


def ensure_worker_for(session: Session) -> RunWorker:
    """Start the worker **on the database this request came in on**, if it is not running. Idempotent.

    **Why the worker is bound here and not at boot, which is a decision and not laziness.** The obvious
    place to start a worker is the application's lifespan hook, and that was written first and removed.
    `api/main.py` holds a module-level session factory pointed at `backend/eigentlich.db`; a test overrides
    the *dependency* and not that global, so a worker started at boot would poll the developer's real
    database from inside the test suite — and would execute a run found there, which is a subprocess that
    can take half an hour. A68 records what "every test run touched the real database" already cost this
    build once, and the fix is not to remember: it is for the worker to use the bind the caller is already
    using, so there is one database in play and no second answer to which one it is.

    **What that costs, stated.** A run left `submitted` by a previous process is picked up on the next
    submit or the next listing rather than at boot, because until one of those happens nothing has told
    this module which database to look in. Both entry points call this, so any client that polls closes the
    gap on its own; a queue left pending with nobody ever returning stays pending, which is visible in the
    table rather than silent.
    """
    return start_worker(sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True))


def stop_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def worker() -> RunWorker | None:
    """The process's worker, or None if none was started. For a health board and for a REPL.

    There is deliberately no `wake_worker()` beside this. One existed and was removed the moment
    `ensure_worker_for` replaced it at both call sites: a module-level nudge that silently did nothing when
    no worker had been started is the shape of a function that looks like it guarantees something. A caller
    that wants a run to start now asks for a worker and wakes it, which cannot no-op.
    """
    return _worker


__all__ = [
    "CURATOR_ONLY_ENGINES",
    "MEMBER_FACING_RESULT_KEYS",
    "NotQueueable",
    "POLL_INTERVAL_MS",
    "REFUSAL_REASONS",
    "RunWorker",
    "UnknownEngine",
    "describe_run",
    "ensure_worker_for",
    "list_runs",
    "queue",
    "read_run",
    "recover_interrupted_runs",
    "serving_request",
    "start_worker",
    "stop_worker",
    "submit",
    "worker",
]
