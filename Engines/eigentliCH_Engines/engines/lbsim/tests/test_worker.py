"""The worker harness (spec section 5) and the handshake with agent C.

In process: a plan run succeeds and writes its artefact; cancel and supersede stop a running solve at its next
checkpoint; the wall-clock budget times it out with no artefact; curator runs go first; stale runs are requeued at
most ``max_attempts`` times. Out of process: a real ``python -m lbsim worker`` is killed in the middle of a solve
and its run is requeued and finished by the next worker. The import boundary (LBSIM-03) in a fresh interpreter.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

import standin
from stub import Stub, bundle, stated

from lbsim import plan as P
from lbsim import store as st
from lbsim.calibration import ACTIVE_SEED
from lbsim.clients import Upstream
from lbsim.contracts import LifeBalancePlan, LifeBalanceSimRequest, OptimiseRequest, RequestedBy
from lbsim.paths.build import build_paths
from lbsim.service import Service
from lbsim.settings import ROOT, load
from lbsim.store import Store
from lbsim.worker import Worker

CASE = "lbsim-sample"
TESTS = Path(__file__).resolve().parent


def fast_settings(**optimiser):
    s = load()
    o = replace(s.optimiser, heartbeat_s=0.2, stale_after_s=1.0, poll_s=0.1, **optimiser)
    return replace(s, database=replace(s.database, schema=f"t_{uuid.uuid4().hex[:12]}"), optimiser=o)


@pytest.fixture()
def world():
    settings = fast_settings()
    stub = Stub((CASE,))
    service = Service(settings, Store(settings.database), Upstream.from_config(settings.upstream,
                                                                               transport=stub.transport()))
    service.startup()
    yield service, stub
    assert settings.database.schema.startswith("t_")
    Store(settings.database).drop_schema()


def outlook(service, stub, **over):
    sid = stub.sheet_id(CASE)
    body = {"client_ref": stub.sheets[sid]["client_ref"], "life_balance_sheet_id": sid,
            "allocation_id": stub.allocation_id, "n_paths": 300, **over}
    return service.run(LifeBalanceSimRequest(**body))


def status(service, run_id):
    return service.run_status(run_id)


def run_in_thread(worker):
    t = threading.Thread(target=worker.run_one, daemon=True)
    t.start()
    return t


def wait_for(fn, timeout=20.0, every=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(every)
    return False


# --- in process ----------------------------------------------------------------------------------------------

def test_a_plan_run_succeeds_and_writes_the_plan(world):
    service, stub = world
    acc = outlook(service, stub)
    worker = Worker(service, solver=standin.quick)
    assert worker.run_one() == acc.plan_run_id
    s = status(service, acc.plan_run_id)
    assert s.status == "succeeded" and s.failure_kind is None and s.artefact_ids[0].startswith("LSO-")
    plan = service.plan(s.artefact_ids[0])
    assert isinstance(plan, LifeBalancePlan) and plan.paths_artefact_id == acc.paths_artefact_id
    assert plan.goal.goal_id == "g-home" and plan.extra_goals == ("g-ret",) and plan.goal.confidence == 0.9
    assert 0.0 <= plan.chance.out_of_sample <= 1.0 and plan.chance.seed_out == 20260929 + 500_000
    assert plan.chance.n_out_of_sample == 300 and plan.framing.en.startswith("What the calculation assumes")
    assert plan.provenance.idempotency_key == s.idempotency_key
    o = service.outlook(plan.client_ref)
    assert o.plan.state == "ready" and o.plan.artefact.artefact_id == plan.artefact_id
    again = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id,
                                             requested_by=RequestedBy(kind="curator", ref="c1")))
    assert again.cached is True and again.run_id == acc.plan_run_id
    assert worker.run_one() is None


def test_cancel_stops_a_running_solve_at_its_next_checkpoint(world):
    service, stub = world
    acc = outlook(service, stub)
    t = run_in_thread(Worker(service, solver=standin.sleepy))
    assert wait_for(lambda: status(service, acc.plan_run_id).status == "running")
    assert wait_for(lambda: status(service, acc.plan_run_id).progress is not None)
    service.cancel(acc.plan_run_id)
    t.join(20)
    s = status(service, acc.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "cancelled" and s.artefact_ids == ()
    assert s.progress.phase == "best_life"


def test_a_newer_outlook_supersedes_a_running_plan(world):
    service, stub = world
    first = outlook(service, stub)
    t = run_in_thread(Worker(service, solver=standin.sleepy))
    assert wait_for(lambda: status(service, first.plan_run_id).status == "running")
    newer = outlook(service, stub, seed=4242)
    t.join(20)
    s = status(service, first.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "superseded" and s.artefact_ids == ()
    assert status(service, newer.plan_run_id).status == "queued"


def test_the_budget_times_a_solve_out_with_no_figures(world):
    service, stub = world
    acc = outlook(service, stub)
    with service.store.session() as conn:
        conn.execute("UPDATE run SET budget_s = 0.5 WHERE run_id = %s", (acc.plan_run_id,))
    t0 = time.monotonic()
    Worker(service, solver=standin.sleepy).run_one()
    assert time.monotonic() - t0 < 10
    s = status(service, acc.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "timed_out" and s.artefact_ids == ()


def test_a_solver_that_raises_fails_the_run(world):
    service, stub = world
    acc = outlook(service, stub)
    Worker(service, solver=standin.raises).run_one()
    s = status(service, acc.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "solver" and "broke" in s.error


def test_moved_upstream_fails_the_run_as_upstream(world):
    service, stub = world
    acc = outlook(service, stub)
    stub.edit("allocation", lambda a: {**a, "mandate_name": "moved"})
    Worker(service, solver=standin.quick).run_one()
    s = status(service, acc.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "upstream" and "changed" in s.error


def test_curator_runs_go_first(world):
    service, stub = world
    acc = outlook(service, stub, optimise="no")
    system = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id, seed=1,
                                              requested_by=RequestedBy(kind="system", ref="backfill")))
    client = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id, seed=2,
                                              requested_by=RequestedBy(kind="client", ref="app")))
    curator = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id, seed=3,
                                               requested_by=RequestedBy(kind="curator", ref="cur-1")))
    order = []
    with service.store.session() as conn:
        for _ in range(3):
            order.append(st.claim_next(conn, "w")["run_id"])
    assert order == [curator.run_id, client.run_id, system.run_id]


def test_stale_runs_are_requeued_at_most_twice(world):
    service, stub = world
    acc = outlook(service, stub)
    for attempt in (1, 2):
        with service.store.session() as conn:
            row = st.claim_next(conn, "ghost")
            assert row["run_id"] == acc.plan_run_id and row["attempts"] == attempt
            conn.execute("UPDATE run SET heartbeat_at = %s WHERE run_id = %s", (st.utc_now(-60), acc.plan_run_id))
        out = service.requeue_stale()
        assert out == [(acc.plan_run_id, "queued" if attempt == 1 else "failed")]
    s = status(service, acc.plan_run_id)
    assert s.status == "failed" and s.failure_kind == "solver" and "2 times" in s.error
    with service.store.session() as conn:
        events = [e["event"] for e in st.events_for(conn, acc.plan_run_id)]
    assert events == ["queued", "running", "requeued", "running", "failed:solver"]


def test_the_store_refuses_changes_to_what_is_append_only(world):
    service, stub = world
    acc = outlook(service, stub)
    import psycopg  # noqa: PLC0415
    for sql in ("UPDATE artefact SET client_ref = 'x'", "DELETE FROM calibration", "UPDATE run_event SET event = 'x'"):
        with pytest.raises(psycopg.errors.RaiseException):
            with service.store.session() as conn:
                conn.execute(sql)
    with service.store.session() as conn:
        cols = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                            "WHERE table_schema = %s", (service.settings.database.schema,)).fetchall()
        comments = conn.execute("SELECT c.relname, obj_description(c.oid) AS d FROM pg_class c JOIN pg_namespace n "
                                "ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind = 'r'",
                                (service.settings.database.schema,)).fetchall()
    assert not [c for c in cols if c["data_type"] == "real"]
    assert {c["relname"] for c in comments} == {"calibration", "artefact", "run", "run_event"}
    assert all(c["d"] and c["d"].startswith("lbsim: ") for c in comments)
    assert acc.run_id


# --- the handshake with agent C -------------------------------------------------------------------------------

def test_the_plan_problem_is_built_on_cs_types():
    from lbsim.optim import types as T  # noqa: PLC0415

    stub = Stub((CASE,))
    sheet, request, records, findings, plan = stated(CASE)
    b = bundle(stub, sheet)
    paths = build_paths(findings, plan, b, ACTIVE_SEED, n_paths=300, seed=11)
    problem = P.plan_problem(paths=paths, plan=plan, bundle=b, calibration=ACTIVE_SEED, designated="g-ret", seed=11,
                             max_solve_horizon_years=20.0)
    assert isinstance(problem, T.PlanProblem) and problem.goal.goal_id == "g-ret"
    assert [g.goal_id for g in problem.extra_goals] == ["g-home"]
    assert problem.market.kind == "allocation" and len(problem.market.state_distribution) == plan.horizon_years
    assert problem.market.state_distribution[0] == pytest.approx(
        [x / sum(b.allocation.curves.regime) for x in b.allocation.curves.regime])
    g = problem.goal
    assert g.measure == "retirement_capital" and g.amount_basis == "today" and g.horizon_years == 27.0
    assert g.planned_saving_chf_per_year > 0 and problem.n_out_of_sample == 300
    path = standin._path(problem, standin.constant_controls(problem))
    one = P.simulate(problem, path, 400, 99)
    assert one == P.simulate(problem, path, 400, 99)
    assert set(one) >= {"chance", "n_reached", "shortfall_cvar_chf"} and 0.0 <= one["chance"] <= 1.0
    assert one["judged_at_year"] == 20 and one["requirement_chf"] < g.target_real_chf  # beyond the cap
    home = replace(problem, goal=problem.extra_goals[0], extra_goals=())
    near = P.simulate(home, path, 400, 99)
    assert near["judged_at_year"] == 3 and near["requirement_chf"] == pytest.approx(home.goal.target_real_chf)


def test_the_plan_key_moves_with_the_seed_and_not_with_who_asks(world):
    service, stub = world
    acc = outlook(service, stub, optimise="no")
    a = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id,
                                         requested_by=RequestedBy(kind="client", ref="app")))
    b = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id,
                                         requested_by=RequestedBy(kind="curator", ref="c")))
    c = service.optimise(OptimiseRequest(paths_artefact_id=acc.paths_artefact_id, seed=3,
                                         requested_by=RequestedBy(kind="curator", ref="c")))
    assert a.idempotency_key == b.idempotency_key != c.idempotency_key and a.run_id == b.run_id


# --- the import boundary (LBSIM-03) ---------------------------------------------------------------------------

def test_the_api_process_never_imports_casadi_or_the_optimiser():
    code = f"""
import sys, uuid
sys.path.insert(0, {str(TESTS)!r})
from dataclasses import replace
from fastapi.testclient import TestClient
from stub import Stub
from lbsim.api import create_app
from lbsim.clients import Upstream
from lbsim.settings import load
from lbsim.store import Store
import lbsim.paths.build, lbsim.paths.engine, lbsim.paths.reference, lbsim.upstream, lbsim.plan, lbsim.worker
s = load(); s = replace(s, database=replace(s.database, schema='t_' + uuid.uuid4().hex[:12]))
stub = Stub(('lbsim-sample',))
try:
    with TestClient(create_app(s, Upstream.from_config(s.upstream, transport=stub.transport()))) as c:
        sid = stub.sheet_id('lbsim-sample')
        r = c.post('/run', json={{'client_ref': stub.sheets[sid]['client_ref'], 'life_balance_sheet_id': sid,
                                  'allocation_id': stub.allocation_id, 'n_paths': 200}})
        assert r.status_code == 200 and r.json()['plan_run_id'], r.text
        c.post('/optimise', json={{'paths_artefact_id': r.json()['paths_artefact_id'],
                                   'requested_by': {{'kind': 'curator', 'ref': 'x'}}}})
finally:
    Store(s.database).drop_schema()
print('casadi' in sys.modules, any(m == 'lbsim.optim' or m.startswith('lbsim.optim.') for m in sys.modules))
"""
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.strip().splitlines()[-1] == "False False"


def test_only_the_worker_loads_the_optimiser():
    code = ("import sys; from lbsim.worker import default_solver; assert 'lbsim.optim' not in sys.modules; "
            "solve = default_solver(); print(solve.__module__, 'lbsim.optim' in sys.modules)")
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=300,
                         env={k: v for k, v in os.environ.items() if k != "LBSIM_TEST_SOLVER"})
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "lbsim.optim True"


# --- a real worker process, killed -----------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_killed_worker_is_requeued_and_finished_by_the_next(tmp_path):
    import uvicorn  # noqa: PLC0415

    stub = Stub((CASE,))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(stub.app(), host="127.0.0.1", port=port, log_level="warning"))
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    assert wait_for(lambda: server.started, 20)
    schema = f"t_{uuid.uuid4().hex[:12]}"
    tree = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    tree["database"]["schema"] = schema
    for name in ("lbs", "pcp", "aggregation", "fmre"):
        tree["upstream"][name]["url"] = f"http://127.0.0.1:{port}"
    tree["optimiser"].update({"heartbeat_s": 0.2, "stale_after_s": 1.5, "poll_s": 0.1})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(tree), encoding="utf-8")
    settings = load(cfg)
    service = Service(settings, Store(settings.database))
    env = {**os.environ, "LBSIM_CONFIG": str(cfg),
           "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    procs = []
    try:
        service.startup()
        acc = outlook(service, stub)
        first = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "lbsim", "worker"],
                                 env={**env, "LBSIM_TEST_SOLVER": "standin:sleepy"}, cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        procs.append(first)
        assert wait_for(lambda: status(service, acc.plan_run_id).status == "running", 60), \
            first.stdout.read().decode(errors="replace") if first.poll() is not None else "not claimed"
        assert wait_for(lambda: status(service, acc.plan_run_id).progress is not None, 30)
        first.kill()
        first.wait(10)
        assert status(service, acc.plan_run_id).status == "running"
        time.sleep(2.0)
        second = subprocess.run([sys.executable, "-X", "utf8", "-m", "lbsim", "worker", "--once"],
                                env={**env, "LBSIM_TEST_SOLVER": "standin:quick"}, cwd=str(ROOT),
                                capture_output=True, text=True, timeout=300)
        assert second.returncode == 0, second.stdout[-2000:] + second.stderr[-2000:]
        s = status(service, acc.plan_run_id)
        assert s.status == "succeeded" and s.artefact_ids[0].startswith("LSO-"), s
        with service.store.session() as conn:
            row = st.get_run(conn, acc.plan_run_id)
            events = [e["event"] for e in st.events_for(conn, acc.plan_run_id)]
        assert row["attempts"] == 2
        assert events == ["queued", "running", "requeued", "running", "succeeded"]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(10)
        server.should_exit = True
        serving.join(10)
        Store(settings.database).drop_schema()


@pytest.mark.slow
def test_cs_solver_end_to_end_on_a_short_budget(world):
    """C's real solve with lbsim's Monte Carlo (slow; ``-m slow``): the run finishes, succeeded or failed with a
    failure kind, never with figures from an unfinished solve."""
    service, stub = world
    acc = outlook(service, stub)
    with service.store.session() as conn:
        conn.execute("UPDATE run SET budget_s = 600 WHERE run_id = %s", (acc.plan_run_id,))
    Worker(service).run_one()
    s = status(service, acc.plan_run_id)
    assert s.status in ("succeeded", "failed")
    assert (s.status == "succeeded") == bool(s.artefact_ids)
    print(json.dumps(s.model_dump(mode="json"), indent=1)[:2000])
