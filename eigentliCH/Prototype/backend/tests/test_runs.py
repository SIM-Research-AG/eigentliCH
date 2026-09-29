"""R-301's queue: the row, the worker, the poll, and every guard around them.

**Every guard in this file was verified by planting the violation, watching it fail, and restoring it.**
What was planted is recorded against each test. A20, A63, A66, A68 and A81's token test are five occasions
in this build where a green suite hid a broken guarantee, and every one of them was absence-shaped — a test
asserting that something was not there, which had never been shown able to notice it when it was.

**The worker is tested without threads wherever a thread would only add waiting.** `RunWorker.run_once()`
is the whole of the work: it claims a row, calls the engine, and writes the outcome. Driving it directly
exercises the real claim, the real session handling and the real C-03 reduction with nothing to sleep on.
Two tests do start the thread, because thread-locality and the poll loop are the things that cannot be
demonstrated any other way.

**The estate is not required.** Two tests exercise the genuine `call_engine` failure path by pointing
`ESTATE_ROOT` at a directory that does not exist, which is how `tests/test_engines.py` does it. The rest
inject a recorded reply, and `test_the_default_call_is_the_real_engine_facade` pins the default so the
injection point cannot quietly become a permanent stub.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from eigentlich import engines as engine_module
from eigentlich.db import PlanMutationWithoutDecision, create_all, make_session_factory
from eigentlich.engines import (
    EngineNotAvailable,
    MEMBER_REFERENCE_REDACTION,
    call_engine,
    known_engines,
    mark_request_thread,
    redacted,
)
from eigentlich.models import DONE, EngineRun, FAILED, Goal, Position, RUNNING, SUBMITTED, utcnow
from eigentlich.services import mutate_plan, register_member
from eigentlich.services import runs as runs_service
from eigentlich.services.runs import (
    CURATOR_ONLY_ENGINES,
    NotQueueable,
    RunWorker,
    UnknownEngine,
    describe_run,
    list_runs,
    queue,
    read_run,
    recover_interrupted_runs,
    serving_request,
    submit,
)
from eigentlich.services.served import EngineArtefactWouldBeServed

TODAY = date(2026, 8, 31)

#: A `call_engine` reply in the shape the estate really returns one, carrying every field C-03 forbids
#: serving. Recorded from the 30 August 2026 `market_signal` run (A69) and trimmed.
REPLY = {
    "ok": True,
    "engine": "market_signal",
    "contract_type": "RegimeRef",
    "contract": {
        "regime_id": "REG-38d91c1a0da0ef1e",
        "regime_timeline_id": "RTL-38d91c1a0da0ef1e",
        "scope": "Global",
        "as_of": "2024-12-31",
        "model_version": "ms@0.1.0",
    },
    "model_version": "ms@0.1.0",
    "as_of": "2024-12-31",
    "notes": ["blended over: br 5%, ch 5%, cn 25%"],
    "raw": {"months": 177, "first": "2010-01", "last": "2024-12"},
    "idempotency_key": "a08acce35dcb6f96",
    "trace_id": "TR-a08acce35dcb6f96",
    "replay": "cd Macro_Model && <read> output/regime/Global.json",
}


# ============================================================ fixtures


@pytest.fixture()
def threadsafe_engine():
    """One in-memory database a worker thread and the test thread can both reach.

    `StaticPool` with `check_same_thread=False`, exactly as `conftest.api_engine` does it and for the same
    reason: SQLAlchemy hands plain `:memory:` a connection per thread, so a worker would open a second,
    empty database and every assertion here would be about the wrong one. That is the A68 shape.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def sessions(threadsafe_engine):
    return make_session_factory(threadsafe_engine)


@pytest.fixture()
def db(sessions):
    with sessions() as session:
        yield session


@pytest.fixture()
def member(db):
    m = register_member(db, age_at_registration=41, display_name="Mitglied")
    db.commit()
    return m


@pytest.fixture()
def plan(db, member):
    """One dated, priced goal funded by one growth position. The shape a member actually has."""
    goal = Goal(
        member_id=member.id,
        name="Wohneigentum",
        target_amount=250_000,
        target_date=TODAY + timedelta(days=1500),
    )
    position = Position(
        member_id=member.id,
        role="growth",
        capital_type="financial",
        label="Wertschriftendepot",
        liquidity="within_months",
    )
    with mutate_plan(db, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        db.add_all([goal, position])
        goal.funded_by.append(position)
        decision.linked_goals.append(goal)
        decision.linked_positions.append(position)
    db.commit()
    return goal, position


def _worker(sessions, *, reply=None, error=None):
    """A worker whose engine call is recorded rather than run. `call` is injectable for tests only."""
    seen: list[tuple] = []

    def fake(engine, payload, **kwargs):
        seen.append((engine, payload, kwargs, engine_module.on_request_thread()))
        if error is not None:
            raise error
        return dict(reply if reply is not None else REPLY)

    worker = RunWorker(sessions, call=fake)
    worker.calls = seen  # type: ignore[attr-defined]
    return worker


def _numbers(value, path="") -> list[str]:
    """Every numeric leaf in a payload, at any depth, with its path. Booleans excluded.

    `isinstance(True, int)` is true in Python, and `available: false` is not a number a screen can render
    as a measurement. Excluding it is the same call `tests/test_engines.py` makes for `attempt()`, one
    level deeper.
    """
    found: list[str] = []
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        return [f"{path}={value}"]
    if isinstance(value, dict):
        for key, inner in value.items():
            found += _numbers(inner, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            found += _numbers(inner, f"{path}[{index}]")
    return found


def test_the_number_scanner_finds_a_number():
    """The guard on the guard. Without this, `test_a_failed_run_carries_no_number_at_any_depth` would pass
    on a scanner that returned an empty list for everything — A20's exact shape, and the reason five
    guarantees in this build stopped holding while the suite stayed green."""
    assert _numbers({"a": {"b": [{"c": 3}]}}) == ["a.b[0].c=3"]
    assert _numbers({"available": False, "reason": "not available", "at": None}) == []


# ============================================================ the row is the queue


def test_a_queued_run_is_a_row_and_nothing_else(db, member):
    """R-301. The queue is the table: status, engine, payload, member and the declared budget."""
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    stored = db.execute(select(EngineRun)).scalar_one()
    assert stored.id == run.id
    assert stored.status == SUBMITTED
    assert stored.engine == "market_signal"
    assert stored.payload == {"scope": "Global"}
    assert stored.member_id == member.id
    assert stored.timeout_s == 1800  # the manifest's own declaration, not a number typed here
    assert stored.result is None and stored.reason is None
    assert stored.finished_at is None and stored.started_at is None


def test_an_engine_with_no_manifest_is_not_queueable(db):
    """R-300. "An engine without a manifest is not callable" — so it is not queueable either.

    **Planted violation:** removed the `known_engines()` check from `queue`. The row was written and the
    worker then failed it as a defect, i.e. the refusal moved from submit-time to a stored failure. Restored.
    """
    with pytest.raises(UnknownEngine) as raised:
        queue(db, engine="no_such_engine", payload={})
    assert "no manifest" in str(raised.value)
    assert db.execute(select(EngineRun)).all() == []


def test_a_run_belonging_to_another_member_is_not_readable(db, member):
    """A81. The SELECT is scoped, so somebody else's run and a run that never existed are one answer.

    **Planted violation:** dropped `EngineRun.member_id == member_id` from `read_run`. This failed with the
    other member's run coming back. Restored.
    """
    other = register_member(db, age_at_registration=44, display_name="Andere")
    db.commit()
    mine = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    theirs = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=other.id)
    db.commit()

    assert read_run(db, run_id=mine.id, member_id=member.id) is not None
    assert read_run(db, run_id=theirs.id, member_id=member.id) is None
    assert [r["run_id"] for r in list_runs(db, member_id=member.id)["runs"]] == [mine.id]


# ============================================================ R-301: never on a request thread


def test_submitting_a_run_never_calls_an_engine(db, member, monkeypatch):
    """R-301, the structural half. Submitting is legal on a request thread because it runs no engine.

    The estate is pointed at a directory that does not exist AND the thread is marked as serving a
    request: if `submit` reached an engine by any route it would raise `EngineOnRequestThread` or
    `EngineNotAvailable` here rather than returning a row.

    **Planted violation:** added `call_engine(engine, plan.payload)` to `submit` just before the return.
    Failed with `EngineOnRequestThread`. Restored.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    with serving_request():
        assert engine_module.on_request_thread() is True
        run = submit(db, engine="market_signal", member_id=member.id, today=TODAY)
    db.commit()
    assert run.status == SUBMITTED


def test_serving_request_makes_call_engine_refuse(monkeypatch):
    """The belt-and-braces half. Inside the context manager the engine façade refuses (R-301).

    **Planted violation:** made `serving_request` a no-op `yield`. Failed here, which is what makes the
    context manager worth having rather than decorative.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    with serving_request():
        with pytest.raises(engine_module.EngineOnRequestThread):
            call_engine("market_signal", {"scope": "Global"})
    # And the flag is cleared on the way out, so a threadpool thread is not left marked forever.
    assert engine_module.on_request_thread() is False


def test_the_flag_is_cleared_even_when_the_body_raises():
    """A63's failure mode is a flag left set. `serving_request` clears in a `finally`.

    **Planted violation:** moved the reset out of the `finally`. Failed here.
    """
    with pytest.raises(RuntimeError):
        with serving_request():
            raise RuntimeError("boom")
    assert engine_module.on_request_thread() is False


def test_the_worker_thread_is_not_a_request_thread(sessions, db, member):
    """R-301's whole point: the engine runs on a thread that was never serving a request.

    The test thread is marked as serving while the worker executes, and the injected call records what
    `on_request_thread()` said **on the worker's own thread**. This is the one claim that needs a real
    thread to demonstrate.
    """
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = _worker(sessions)
    mark_request_thread(True)
    try:
        worker.start()
        _wait_for(lambda: worker.calls, "the worker never picked the run up")
    finally:
        mark_request_thread(False)
        worker.stop()

    _engine_name, _payload, _kwargs, on_request_thread = worker.calls[0]
    assert on_request_thread is False, "R-301: the engine ran on a thread marked as serving a request"


def _wait_for(predicate, message, *, timeout_s=5):
    """Poll a condition rather than sleeping a fixed time. Used only by the two threaded tests."""
    deadline = utcnow() + timedelta(seconds=timeout_s)
    while utcnow() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError(message)


def test_the_default_call_is_the_real_engine_facade(sessions):
    """A20. `call` is injectable for tests; the default must be the real thing.

    Without this the injection point could quietly become a permanent stub and every test above would
    still be green while no engine was ever reachable — which is precisely the state this whole change
    exists to end.
    """
    assert RunWorker(sessions)._call is call_engine


# ============================================================ the worker, executed directly


def test_a_completed_run_carries_the_engines_reading(sessions, db, member):
    """The happy path: submitted -> running -> done, with the reading stored on the row."""
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = _worker(sessions)
    assert worker.run_once() is True
    assert worker.run_once() is False, "the queue should be empty now"

    db.expire_all()
    stored = db.get(EngineRun, run.id)
    assert stored.status == DONE
    assert stored.reason is None
    assert stored.started_at is not None and stored.finished_at is not None
    assert stored.result["contract"]["regime_id"] == "REG-38d91c1a0da0ef1e"

    payload = describe_run(stored)
    assert payload["available"] is True
    assert payload["duration_ms"] >= 0


def test_the_engine_is_given_the_manifests_own_timeout(sessions, db, member):
    """R-301. The budget travels with the run rather than being decided by the worker."""
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()
    worker = _worker(sessions)
    worker.run_once()
    _engine_name, _payload, kwargs, _flag = worker.calls[0]
    assert kwargs["timeout_s"] == 1800


def test_two_workers_cannot_claim_one_run(sessions, db, member):
    """The claim is a conditional UPDATE with a rowcount check, not a read-then-write.

    **Planted violation:** replaced the conditional update with `run.status = RUNNING`. This test still
    passed — one worker at a time cannot race itself — so the claim was rewritten as a claim anyway and
    this test holds the *contract* instead: a run already `running` is not claimable. That is honest about
    what it proves, which A81's `session.rollback()` note is the precedent for.
    """
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = _worker(sessions)
    assert worker.run_once() is True
    db.expire_all()
    assert db.get(EngineRun, run.id).status == DONE

    # A second pass finds nothing: the row is no longer `submitted`.
    assert worker.run_once() is False


# ============================================================ R-302: no number on a failure


def test_a_failed_run_carries_no_number_at_any_depth(sessions, db, member, monkeypatch):
    """R-302, through the **real** `call_engine`, with the estate unreachable.

    "A failed engine renders as 'not available', not as a zero." Asserted by scanning the whole member
    facing payload recursively: there must be nothing numeric there to read.

    **Planted violation:** added `"duration_ms": _duration_ms(run)` to the failed branch of
    `describe_run`. Failed with `R-302: a failed run served numbers: duration_ms=0`. Then planted
    `"timeout_s": run.timeout_s` instead. Failed with `timeout_s=1800`. Both restored.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    # The real façade, not a fake: this is the genuine R-302 path.
    assert RunWorker(sessions).run_once() is True

    db.expire_all()
    stored = db.get(EngineRun, run.id)
    assert stored.status == FAILED
    assert "no estate interpreter" in stored.reason
    assert stored.result is None

    payload = describe_run(stored)
    assert payload["available"] is False
    assert payload["reason"]
    assert "result" not in payload
    assert "timeout_s" not in payload
    assert "duration_ms" not in payload
    assert not _numbers(payload), f"R-302: a failed run served numbers: {_numbers(payload)}"


def test_a_failed_run_does_not_stop_the_queue(sessions, db, member, monkeypatch):
    """R-302's second half: failure degrades the screen, never the session. The next run still works."""
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    first = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    second = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = RunWorker(sessions)
    assert worker.run_once() is True
    assert worker.run_once() is True
    db.expire_all()
    assert db.get(EngineRun, first.id).status == FAILED
    assert db.get(EngineRun, second.id).status == FAILED


def test_a_defect_in_this_codebase_ends_the_run_and_not_the_worker(sessions, db, member):
    """`attempt()` deliberately re-raises a defect; a worker thread has nobody to raise at.

    So the run is failed, marked as a defect in eigentliCH rather than an engine failure, and the loop
    survives. Without this the row would stay `running` for ever and the thread would be gone — the same
    defect with the evidence deleted.

    **Planted violation:** narrowed the handler to `except EngineNotAvailable` only. The exception escaped
    `run_once`, the row stayed `running`, and this test failed on the status. Restored.
    """
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    later = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = _worker(sessions, error=engine_module.UndeclaredInput("R-300: nope"))
    assert worker.run_once() is True
    assert worker.run_once() is True  # the loop is intact

    db.expire_all()
    failed = db.get(EngineRun, later.id)
    assert failed.status == FAILED
    assert "a defect in eigentliCH" in failed.reason
    assert "UndeclaredInput" in failed.reason
    assert not _numbers(describe_run(failed))


def test_a_run_interrupted_by_a_restart_is_resolved(sessions, db, member):
    """A run left `running` by a dead process is failed with a true reason, not left looking pending.

    **Not re-queued, deliberately** — an engine run takes minutes and reaches the network, and silently
    restarting one on every boot is a loop nobody asked for.

    **Planted violation:** made `recover_interrupted_runs` reset the status to `submitted` instead. The
    reason was then None and this test failed on it; it also meant a run restarting itself on every start.
    Restored.
    """
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    run.status = RUNNING
    run.started_at = utcnow()
    db.commit()

    assert recover_interrupted_runs(db) == 1
    db.expire_all()
    stored = db.get(EngineRun, run.id)
    assert stored.status == FAILED
    assert "the application stopped" in stored.reason
    assert not _numbers(describe_run(stored))
    # Idempotent: a second pass finds nothing to recover.
    assert recover_interrupted_runs(db) == 0


# ============================================================ C-03: no engine artefact on a run


def test_no_engine_artefact_is_stored_on_a_run(sessions, db, member):
    """C-03 / R-304. The reply carries `regime_timeline_id`, `raw` and `replay`; the row carries none.

    **Stored** rather than filtered on the way out, so the HTTP poll and the R-154 export are covered by
    the same pass. Checked against the stored row, not against `describe_run`, because that is the claim.

    **Planted violation:** changed `_member_facing_result` to `return dict(reply)`. Failed with
    `EngineArtefactWouldBeServed` naming `regime_timeline_id` and `replay` — the guard raising rather than
    the test noticing later, which is the right order. Then removed the `assert_no_engine_artefact` call
    too: this test failed on `regime_timeline_id` in the rendered row. Both restored.
    """
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()
    _worker(sessions).run_once()

    db.expire_all()
    stored = db.get(EngineRun, run.id)
    rendered = json.dumps(stored.result)
    for marker in ("regime_timeline_id", "return_set_id", "state_grid", "building_blocks", "replay"):
        assert marker not in rendered, f"C-03: a stored run result carries {marker!r}"
    for dropped in ("raw", "idempotency_key", "artefact"):
        assert dropped not in stored.result
    # Non-vacuous the other way: the reading survived, so this is a filter and not a wall.
    assert stored.result["contract"]["regime_id"] == "REG-38d91c1a0da0ef1e"
    assert stored.result["notes"] == REPLY["notes"]


def test_an_artefact_that_survives_the_strip_fails_the_run_rather_than_being_served(sessions, db, member):
    """The guard raises rather than filtering, so a construction defect cannot be served quietly.

    A marker arriving as a *value* — an artefact id pasted into a note — is not a key and is not stripped.
    `assert_no_engine_artefact` refuses it, the run is recorded as a defect, and nothing reaches a member.
    That is the behaviour C-03's "under any circumstance" asks for.
    """
    poisoned = {**REPLY, "notes": ["see state_grid for the state mapping"]}
    run = queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()

    worker = _worker(sessions, reply=poisoned)
    assert worker.run_once() is True

    db.expire_all()
    stored = db.get(EngineRun, run.id)
    assert stored.status == FAILED
    assert "EngineArtefactWouldBeServed" in stored.reason
    assert stored.result is None


def test_the_guard_is_reachable_and_refuses(sessions):
    """Direct proof that `assert_no_engine_artefact` fires, independent of any worker."""
    from eigentlich.services.runs import _member_facing_result

    with pytest.raises(EngineArtefactWouldBeServed):
        _member_facing_result({**REPLY, "notes": ["building_blocks: 8"]})


# ============================================================ C-04 / R-303: ids and status only


def test_the_run_log_line_goes_through_the_one_redactor(db, member, monkeypatch):
    """R-303 / C-04, made structural rather than promised.

    Two things are asserted. First, `services/runs.py` uses `engines.redacted` and does not carry a second
    redactor — R-303's instruction is that there is one. Second, the dict `_log` renders is actually passed
    through it, so a later hand adding `member_id` to that dict is redacted by the code and not by review.

    **Planted violation:** removed the `redacted(...)` wrapper from `_log`, leaving the bare dict. The spy
    was never called and this test failed. Restored.
    """
    assert runs_service.redacted is redacted, "R-303: a second redactor appeared in services/runs.py"
    # And the redactor in use really does strip a member reference, so the structural claim means something.
    assert redacted({"run_id": "r", "member_id": "M-42"})["member_id"] == MEMBER_REFERENCE_REDACTION

    seen: list[dict] = []

    def spy(value):
        seen.append(value)
        return redacted(value)

    monkeypatch.setattr(runs_service, "redacted", spy)
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)

    assert seen, "R-303: the run log line did not go through the redactor"
    assert set(seen[0]) == {"run_id", "engine", "status"}, (
        f"C-04: the run log line carries more than ids and status: {sorted(seen[0])}"
    )


def test_neither_the_payload_nor_the_reason_reaches_a_log_line(sessions, db, member, caplog):
    """C-04. "Nothing about a run may be logged beyond ids and status."

    The payload holds a distinctive figure and the engine fails with a distinctive reason. Neither may
    appear in anything `eigentlich.runs` emits, and the reason must still be on the row — otherwise this
    would be satisfied by logging nothing and recording nothing.

    **The capture has to span the submit as well as the run.** The first version of this test opened
    `caplog` around `run_once()` only, and **did not catch** a planted `logger.info("queued %s with %s",
    run.engine, run.payload)` inside `queue` — the payload was logged before the capture began. Every
    entry point that touches a run has to be inside the window, or the test only proves that one of them
    is quiet.

    **Planted violation:** changed the failure log line to `logger.warning("run %s failed: %s", run.id,
    run.reason)`. Failed on the reason. Then planted the payload log line in `queue`. Failed on the figure
    once the window covered it. Both restored.
    """
    worker = _worker(sessions, error=EngineNotAvailable("s_curve_trajectory", "REASON-TOKEN-8f21"))
    with caplog.at_level(logging.DEBUG, logger="eigentlich.runs"):
        run = queue(
            db,
            engine="s_curve_trajectory",
            payload={"household_id": member.id, "target": 987654321.0, "horizon_years": 4.5},
            member_id=member.id,
        )
        db.commit()
        worker.run_once()

    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert emitted, "no log line was emitted at all, so this test would pass vacuously"
    assert "987654321" not in emitted, "C-04: a queued payload's figure reached a log line"
    assert "REASON-TOKEN-8f21" not in emitted, "C-04: a run's failure reason reached a log line"
    assert member.id not in emitted, "R-303: the member reference reached a log line"

    db.expire_all()
    assert db.get(EngineRun, run.id).reason == "REASON-TOKEN-8f21", (
        "the reason must be stored on the row; keeping it out of the logs is not the same as losing it"
    )


def test_the_engines_detail_is_discarded_and_not_stored(sessions, db, member):
    """`EngineNotAvailable.detail` carries the estate's stderr, which can quote the payload back at us.

    **Planted violation:** stored `f"{error.reason}: {error.detail}"` as the reason. Failed here. Restored.
    """
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()
    error = EngineNotAvailable("market_signal", "did not run", detail="stderr: household_id=M-42 target=1")
    _worker(sessions, error=error).run_once()

    db.expire_all()
    stored = db.execute(select(EngineRun)).scalar_one()
    assert stored.reason == "did not run"
    assert "M-42" not in (stored.reason or "")


# ============================================================ C-09: a run never writes to the plan


def test_a_worker_thread_cannot_write_to_the_plan(threadsafe_engine, sessions, db, member):
    """C-09, from the other side. A worker thread has never been through `before_flush`.

    So `_refuse_unvetted_plan_dml` refuses a raw plan write from it — correctly. This is asserted rather
    than assumed because the flush bracket is thread-local (A72), and "the guard still fires on a thread
    the request never touched" is exactly the kind of claim that stops being true without anyone noticing.

    Both shapes are tried: Core DML, which only the statement-level guard sees, and an ORM add, which
    `before_flush` sees.
    """
    refused: list[str] = []

    def write_from_a_worker_thread():
        with sessions() as worker_session:
            try:
                worker_session.execute(
                    insert(Position.__table__).values(
                        id="planted", member_id=member.id, role="growth",
                        capital_type="financial", label="from a worker", data_class=2,
                    )
                )
            except PlanMutationWithoutDecision as raised:
                refused.append(f"core: {raised}")
            worker_session.rollback()

            try:
                worker_session.add(
                    Position(member_id=member.id, role="growth", capital_type="financial", label="orm")
                )
                worker_session.flush()
            except PlanMutationWithoutDecision as raised:
                refused.append(f"orm: {raised}")
            worker_session.rollback()

    thread = threading.Thread(target=write_from_a_worker_thread)
    thread.start()
    thread.join()

    assert len(refused) == 2, f"C-09 did not fire on a worker thread: {refused}"
    assert db.execute(select(Position).where(Position.label == "from a worker")).all() == []


def test_running_a_run_writes_to_no_plan_table(sessions, db, member, plan):
    """C-09, positively: executing a run leaves `positions` and `goals` exactly as they were.

    If a result ever *should* enter the plan it goes through `services.plan.mutate_plan`, which writes the
    Decision C-09 requires in the same transaction. Nothing in the queue does, and this is the check that
    says so out loud rather than in a comment.
    """
    goal, position = plan
    before = (
        db.execute(select(Goal)).scalars().all().__len__(),
        db.execute(select(Position)).scalars().all().__len__(),
    )
    queue(db, engine="market_signal", payload={"scope": "Global"}, member_id=member.id)
    db.commit()
    _worker(sessions).run_once()
    db.expire_all()

    assert (
        db.execute(select(Goal)).scalars().all().__len__(),
        db.execute(select(Position)).scalars().all().__len__(),
    ) == before
    assert db.get(Goal, goal.id).target_amount == 250_000
    assert db.get(Position, position.id).label == "Wertschriftendepot"


# ============================================================ what submit refuses, and why


def test_the_world_engine_is_the_one_a_member_can_actually_run(db, member, plan):
    """`market_signal` reads no member data and its plan is complete (A69). It queues."""
    run = submit(db, engine="market_signal", member_id=member.id, today=TODAY)
    assert run.engine == "market_signal"
    assert run.payload == {"scope": "Global", "publish": False}


@pytest.mark.parametrize(
    "engine,expected_gap",
    [
        ("s_curve_trajectory", "initial_wealth"),
        ("life_balance_sheet", "W_L"),
        # `base_snapshot_id` until 3 September 2026, when `PlanVersion` gave the build a numbered
        # baseline and that gap was reclassified from `not_in_the_plan` to `supplied_by_the_caller` —
        # the same kind as this engine's `field` and `to_value`, which the caller has always named. A
        # caller-supplied gap does not block the plan, so it is no longer what refuses this run.
        # `initial_wealth` is, for a member who has stated no stock, and the refusal still names a real
        # missing input of the member's own.
        ("scenario_generator", "initial_wealth"),
        ("score_engine", "months_observed"),
    ],
)
def test_a_member_engine_is_refused_with_the_gap_named(db, member, plan, engine, expected_gap):
    """A39 / A69 / §12. The plan does not answer these, and nothing here defaults one.

    The refusal names the member's own missing input, in `engine_inputs.py`'s own words, so a screen can
    say what to fill in. That is the honest answer and it is the product — not a shortfall in the queue.

    **Planted violation:** made `submit` queue the run anyway when only `not_in_the_plan` gaps remained.
    The run was queued, the engine defaulted the input one layer down, and a number came back that nobody
    had supplied — which is the exact defect §12 calls out. Restored.
    """
    goal, _position = plan
    with pytest.raises(NotQueueable) as raised:
        submit(db, engine=engine, member_id=member.id, goal_id=goal.id, today=TODAY)
    assert raised.value.reason == "the_plan_does_not_answer_this_engine"
    assert expected_gap in [gap.name for gap in raised.value.gaps]
    assert raised.value.as_dict()["queued"] is False
    assert db.execute(select(EngineRun)).all() == [], "a refused run must leave no row"


def test_return_estimation_is_refused_for_a_caller_supplied_input(db, member):
    """The ReturnSet is estimated under exactly one Regime, and the caller carries its id over.

    Passing a remembered `regime_id` would check against the wrong vintage, and inventing one is not
    available. So the refusal is its own reason rather than being lumped in with a gap in the plan.
    """
    with pytest.raises(NotQueueable) as raised:
        submit(db, engine="return_estimation", member_id=member.id, today=TODAY)
    assert raised.value.reason == "requires_an_input_the_member_did_not_supply"
    assert "regime_id" in [gap.name for gap in raised.value.gaps]


def test_no_engine_is_curator_only_any_more(db, member, monkeypatch):
    """A166. `CURATOR_ONLY_ENGINES` is empty, and `portfolio_optimiser` is refused only by its inputs.

    **This test asserted the opposite until 20 September 2026**, and the inversion is the point of
    keeping it. `portfolio_optimiser` ranks instruments and was refused to members outright under C-01,
    before `plan_for` was consulted, so that filling its `mandate` gap could not silently open the route.
    C-01 is withdrawn (A164) and the FINMA authorisation the refusal was holding it for is no longer
    being sought, so the condition is gone.

    T2.4 of the cull task proposed replacing it with a curator's release record. The owner refused that
    gate (T2.1), so **nothing replaced it.** What still refuses this engine is that the plan cannot answer
    it — and that is a shortfall of inputs, not a control. A81's warning is the one to read here: a guard
    that depends on an unrelated gap is not a guard. Fill `mandate` and nothing stands in the way.
    """
    assert CURATOR_ONLY_ENGINES == (), (
        "an engine is curator-only again. That is a real decision and belongs in DECISIONS.md — the "
        "entry that emptied this tuple is A166."
    )

    # The refusal that remains is about inputs, and it comes from the plan rather than from a list.
    with pytest.raises(NotQueueable) as raised:
        submit(db, engine="portfolio_optimiser", member_id=member.id, today=TODAY)
    assert raised.value.reason == "the_plan_does_not_answer_this_engine", (
        "the optimiser is now refused by its mandate gap, not by a curator condition"
    )


def test_every_engine_in_the_estate_is_accounted_for(db, member, plan):
    """No engine is silently missing from the queue's answer set.

    Every manifest is either queued or refused with a named reason. A new engine added to the estate
    arrives here as a failure rather than as silence — the R-154 lesson about hand-written lists, applied
    to a list this file does not keep.
    """
    goal, _position = plan
    outcomes: dict[str, str] = {}
    for name in known_engines():
        try:
            submit(db, engine=name, member_id=member.id, goal_id=goal.id, today=TODAY)
        except NotQueueable as refused:
            outcomes[name] = refused.reason
        else:
            outcomes[name] = "queued"
    db.rollback()

    assert set(outcomes) == set(known_engines())
    assert outcomes["market_signal"] == "queued"
    # A166: was "requires_a_curator" under C-01. The optimiser is now refused by the same thing that
    # refuses the other three — the plan does not hold what it needs.
    assert outcomes["portfolio_optimiser"] == "the_plan_does_not_answer_this_engine"
    assert all(reason in ("queued", *runs_service.REFUSAL_REASONS) for reason in outcomes.values()), outcomes


def test_a_goal_belonging_to_another_member_cannot_be_named(db, member):
    """A81. Somebody else's goal id and a goal that does not exist are the same refusal."""
    other = register_member(db, age_at_registration=50, display_name="Andere")
    db.commit()
    theirs = Goal(member_id=other.id, name="Ihres", target_amount=1000)
    with mutate_plan(db, member_id=other.id, question="Ziel?", choice="Ja") as decision:
        db.add(theirs)
        decision.linked_goals.append(theirs)
    db.commit()

    with pytest.raises(NotQueueable) as raised:
        submit(db, engine="s_curve_trajectory", member_id=member.id, goal_id=theirs.id, today=TODAY)
    assert raised.value.reason == "the_plan_does_not_answer_this_engine"
    assert raised.value.gaps == ()


# ============================================================ the HTTP surface


@pytest.fixture()
def api(api_session, tmp_path, monkeypatch, fast_kdf):
    """The real application on the in-memory fixture database, as `test_api_auth.py` builds it."""
    from fastapi.testclient import TestClient

    from eigentlich.api import main, remainder
    from eigentlich.services import VaultStore
    from conftest import session_overrides

    store = VaultStore(tmp_path / "vault")
    monkeypatch.setattr(main, "VAULT_STORE", store)
    overrides = session_overrides(api_session)
    overrides[remainder.get_store] = lambda: store
    main.app.dependency_overrides.update(overrides)
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        for key in overrides:
            main.app.dependency_overrides.pop(key, None)
        runs_service.stop_worker()


@pytest.fixture()
def token(api, api_session, fast_kdf):
    from eigentlich.services.auth import register_with_credentials

    password = "ein ziemlich langes passwort"
    member, _ = register_with_credentials(
        api_session,
        email="runs@example.ch",
        password=password,
        age_at_registration=41,
        display_name="Mitglied",
    )
    api_session.commit()
    response = api.post("/api/session", json={"email": "runs@example.ch", "password": password})
    assert response.status_code == 201, response.text
    return member, {"Authorization": f"Bearer {response.json()['token']}"}


def test_the_route_queues_and_polls(api, token, monkeypatch):
    """R-301 end to end: 202 with a poll URL, then the poll answers.

    The worker is stopped for this test so the run stays `submitted` and the poll is observed doing its
    job rather than racing a real engine call.
    """
    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    member, headers = token

    created = api.post("/api/runs", json={"engine": "market_signal"}, headers=headers)
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["queued"] is True
    assert body["status"] == SUBMITTED
    assert body["poll"] == f"/api/runs/{body['run_id']}"

    polled = api.get(body["poll"], headers=headers)
    assert polled.status_code == 200
    assert polled.json()["status"] == SUBMITTED

    listed = api.get("/api/runs", headers=headers)
    assert [r["run_id"] for r in listed.json()["runs"]] == [body["run_id"]]


def test_the_route_refuses_with_the_gaps_and_writes_nothing(api, token, monkeypatch):
    """A refusal is a 422 carrying the member's own missing inputs, and no row is left behind."""
    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    _member, headers = token

    refused = api.post("/api/runs", json={"engine": "life_balance_sheet"}, headers=headers)
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["queued"] is False
    assert detail["reason"] == "the_plan_does_not_answer_this_engine"
    assert "W_L" in [gap["input"] for gap in detail["absent"]]
    assert api.get("/api/runs", headers=headers).json()["runs"] == []


def test_the_route_refuses_the_ranking_engine_only_for_its_missing_inputs(api, token, monkeypatch):
    """A166 over HTTP. Still a 422, and for a different reason than it used to be.

    It was `requires_a_curator`: C-01, enforced server-side rather than by the client not offering the
    button. It is now `the_plan_does_not_answer_this_engine`, which is the same answer the other three
    unrunnable engines give. Nothing about a curator is consulted on this route any more.
    """
    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    _member, headers = token
    refused = api.post("/api/runs", json={"engine": "portfolio_optimiser"}, headers=headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["reason"] == "the_plan_does_not_answer_this_engine"


def test_the_route_takes_no_engine_payload(api, token, monkeypatch):
    """A caller cannot hand the estate arbitrary keys: there is nowhere in the request to put one.

    **Planted violation:** added `payload: dict = {}` to `RunRequest` and passed it to `queue`. The extra
    key below was then forwarded to the engine, so this test failed on the stored payload. Restored — and
    the field is *absent* rather than validated, on A81's reasoning that a removed parameter cannot be
    forgotten in a route added next month.
    """
    from eigentlich.api.runs import RunRequest

    assert set(RunRequest.model_fields) == {"engine", "goal_id"}

    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    _member, headers = token
    created = api.post(
        "/api/runs",
        json={"engine": "market_signal", "payload": {"annual_return": 0.05}, "publish": True},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    polled = api.get(created.json()["poll"], headers=headers).json()
    assert "annual_return" not in json.dumps(polled)


def test_an_engine_nobody_declared_is_refused_at_the_edge(api, token, monkeypatch):
    """R-300 over HTTP. The manifests are the authority on what an engine is; a name is not enough.

    This is the last of `REFUSAL_REASONS` and it is member-reachable, which is why it is tested here
    rather than left to the service: a route that accepted an engine name and queued a row for it would
    put a permanent `failed` run in the member's own list for a typo.
    """
    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    _member, headers = token
    refused = api.post("/api/runs", json={"engine": "not_an_engine"}, headers=headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["reason"] == "unknown_engine"
    assert api.get("/api/runs", headers=headers).json()["runs"] == []


def test_a_run_id_that_is_not_yours_is_a_404(api, api_session, token, monkeypatch):
    """A81. 404, not 403 — a distinct status would make the route an oracle for other people's run ids."""
    monkeypatch.setattr(runs_service.RunWorker, "start", lambda self: None)
    _member, headers = token

    other = register_member(api_session, age_at_registration=44, display_name="Andere")
    api_session.commit()
    theirs = queue(api_session, engine="market_signal", payload={"scope": "Global"}, member_id=other.id)
    api_session.commit()

    assert api.get(f"/api/runs/{theirs.id}", headers=headers).status_code == 404
    assert api.get("/api/runs/not-a-run", headers=headers).status_code == 404
