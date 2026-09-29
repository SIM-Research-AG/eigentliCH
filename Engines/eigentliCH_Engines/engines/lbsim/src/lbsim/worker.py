"""The plan workers (spec section 5): one process per core, sharing the queue in the store.

A worker loops: it claims the next plan run (``SELECT ... FOR UPDATE SKIP LOCKED``, curator ahead of client ahead
of system, then the oldest), rebuilds the plan's inputs from the paths artefact and the upstream engines, and calls
``lbsim.optim.solve`` with lbsim's Monte Carlo as ``simulate``. While it solves, a heartbeat thread writes
``heartbeat_at`` every ``optimiser.heartbeat_s`` and reads back whether the run was cancelled, superseded or taken
away; ``should_cancel`` tells the optimiser at its next checkpoint (between IPOPT solves). The hard wall clock is
``optimiser.budget_minutes``: ``deadline`` is passed to the solver (which enforces it per IPOPT call) and checked
again after it; past it the run is ``failed`` / ``timed_out`` with no figures. A run whose worker dies stops
beating; at the next start-up of ``serve`` or ``worker`` it goes back to the queue, at most ``max_attempts`` times.

``lbsim.optim`` (and with it casadi) is imported here only, inside :func:`default_solver`, on the first plan.
``LBSIM_TEST_SOLVER=module:function`` replaces the solver in a worker process (the harness tests only).
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Optional

from . import plan as P
from . import store as st
from .contracts import LifeBalanceFindings, LifeBalancePaths, LifeBalanceSimRequest
from .errors import LbsimError
from .service import Service

Solver = Callable[..., Any]


def default_solver() -> Solver:
    hook = os.environ.get("LBSIM_TEST_SOLVER")
    if hook:
        module, _, name = hook.partition(":")
        return getattr(importlib.import_module(module), name)
    from .optim import solve  # noqa: PLC0415 - the only place lbsim.optim is imported

    return solve


class Stop:
    """What the heartbeat learnt: why the run must stop, if it must."""

    def __init__(self) -> None:
        self.reason: Optional[str] = None
        self.lock = threading.Lock()

    def set(self, reason: str) -> None:
        with self.lock:
            if self.reason is None:
                self.reason = reason


class Worker:
    def __init__(self, service: Service, *, solver: Optional[Solver] = None, name: Optional[str] = None):
        self.service = service
        self.store = service.store
        self.cfg = service.settings.optimiser
        self._solver = solver
        self.name = name or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"

    @property
    def solver(self) -> Solver:
        if self._solver is None:
            self._solver = default_solver()
        return self._solver

    # -- the loop -----------------------------------------------------------------------------------------------

    def run_forever(self, stop: Optional[threading.Event] = None, *, idle_exit_s: Optional[float] = None) -> int:
        """Claim and process plan runs until ``stop`` is set (or, with ``idle_exit_s``, the queue stays empty that
        long). Returns the number of runs processed."""
        self.service.requeue_stale()
        done = 0
        idle_since = time.monotonic()
        while stop is None or not stop.is_set():
            if self.run_one() is not None:
                done += 1
                idle_since = time.monotonic()
                continue
            if idle_exit_s is not None and time.monotonic() - idle_since > idle_exit_s:
                break
            if stop is not None:
                stop.wait(self.cfg.poll_s)
            else:
                time.sleep(self.cfg.poll_s)
        return done

    def run_one(self) -> Optional[str]:
        with self.store.session() as conn:
            row = st.claim_next(conn, self.name)
        if row is None:
            return None
        self.process(row)
        return row["run_id"]

    # -- one run -----------------------------------------------------------------------------------------------

    def process(self, row: dict[str, Any]) -> None:
        run_id = row["run_id"]
        t0 = time.monotonic()
        budget = float(row["budget_s"] or self.cfg.budget_s)
        deadline = t0 + budget
        stop = Stop()
        beating = threading.Event()

        def beat() -> None:
            while not beating.wait(self.cfg.heartbeat_s):
                try:
                    with self.store.session() as conn:
                        seen = st.heartbeat(conn, run_id, self.name)
                except Exception:  # noqa: BLE001 - a missed beat is retried; the run is judged by the store
                    continue
                if seen is None or seen["status"] != "running" or seen["worker"] != self.name:
                    stop.set("superseded")
                elif seen["cancel_requested"]:
                    stop.set(seen["cancel_requested"])
                if time.monotonic() > deadline:
                    stop.set("timed_out")

        def should_cancel() -> bool:
            if time.monotonic() > deadline:
                stop.set("timed_out")
            if stop.reason is None:
                with self.store.session() as conn:
                    seen = st.heartbeat(conn, run_id, self.name)
                if seen is None or seen["worker"] != self.name or seen["status"] != "running":
                    stop.set("superseded")
                elif seen["cancel_requested"]:
                    stop.set(seen["cancel_requested"])
            return stop.reason is not None

        last_progress = [0.0]

        def progress(p: dict[str, Any]) -> None:
            now = time.monotonic()
            if now - last_progress[0] < 1.0 and p.get("phase") == "best_life":
                return
            last_progress[0] = now
            try:
                with self.store.session() as conn:
                    st.set_progress(conn, run_id, {**p, "elapsed_s": round(now - t0, 3)})
            except Exception:  # noqa: BLE001 - progress is informative only
                pass

        thread = threading.Thread(target=beat, name=f"heartbeat-{run_id}", daemon=True)
        thread.start()
        try:
            self._solve(row, deadline=deadline, stop=stop, should_cancel=should_cancel, progress=progress, t0=t0)
        finally:
            beating.set()
            thread.join(timeout=5)

    def _finish(self, run_id: str, t0: float, **kw: Any) -> None:
        with self.store.session() as conn:
            st.finish_run(conn, run_id=run_id, wall_clock_ms=(time.monotonic() - t0) * 1000.0,
                          only_if_status=("running",), **kw)

    def _solve(self, row: dict[str, Any], *, deadline: float, stop: Stop, should_cancel, progress, t0: float) -> None:
        run_id = row["run_id"]
        try:
            ctx = self.inputs(row)
        except LbsimError as exc:
            self._finish(run_id, t0, status="failed", failure_kind="upstream", error=exc.message)
            return
        except Exception as exc:  # noqa: BLE001 - a run that cannot be set up fails with its reason
            self._finish(run_id, t0, status="failed", failure_kind="solver",
                         error=f"The plan calculation could not be set up: {type(exc).__name__}: {exc}")
            return
        if should_cancel():
            self._finish(run_id, t0, status="failed", failure_kind=stop.reason,
                         error=_STOPPED.get(stop.reason, "stopped"))
            return
        try:
            outcome = self.solver(ctx["problem"], simulate=P.simulate, deadline=deadline,
                                  should_cancel=should_cancel, progress=progress)
        except Exception as exc:  # noqa: BLE001 - the solver promises not to raise; if it does, the run fails
            self._finish(run_id, t0, status="failed", failure_kind="solver",
                         error=f"The optimiser stopped with an error: {type(exc).__name__}: {exc}",)
            traceback.print_exc()
            return
        if stop.reason in ("cancelled", "superseded"):
            self._finish(run_id, t0, status="failed", failure_kind=stop.reason, error=_STOPPED[stop.reason])
            return
        if time.monotonic() > deadline or stop.reason == "timed_out" or \
                getattr(outcome, "failure_kind", None) == "timed_out":
            self._finish(run_id, t0, status="failed", failure_kind="timed_out", error=_STOPPED["timed_out"])
            return
        if outcome.status != "succeeded":
            self._finish(run_id, t0, status="failed", failure_kind=outcome.failure_kind or "solver",
                         error=outcome.error or _STOPPED.get(outcome.failure_kind, "The optimiser failed."))
            return
        art = P.plan_artefact(outcome, paths=ctx["paths"], calibration=ctx["calibration"],
                              key=row["idempotency_key"], findings=ctx["findings"])
        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=art.artefact_id, kind="plan", client_ref=art.client_ref,
                            life_balance_sheet_id=art.life_balance_sheet_id, idempotency_key=row["idempotency_key"],
                            contract_version=art.contract_version, payload_json=art.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", artefact_ids=(art.artefact_id,),
                          wall_clock_ms=(time.monotonic() - t0) * 1000.0, only_if_status=("running",))

    # -- the inputs of a plan run -------------------------------------------------------------------------------

    def inputs(self, row: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the plan's inputs from the paths artefact and the upstream engines, and check that the upstream
        figures the paths rest on have not moved (the paths key's inputs)."""
        req = json.loads(row["request_json"])
        svc = self.service
        paths: LifeBalancePaths = svc.paths(req["paths_artefact_id"])
        findings: LifeBalanceFindings = svc.findings(paths.findings_artefact_id)
        cal = svc.calibration(paths.calibration_version)
        scenarios = tuple(r.key for r in paths.regimes if r.key != "base")
        sim_req = LifeBalanceSimRequest(client_ref=paths.client_ref, life_balance_sheet_id=paths.life_balance_sheet_id,
                                        allocation_id=paths.allocation_id, scenarios=scenarios or None,
                                        horizon_years=float(paths.horizon_years), income_path=paths.income_path,
                                        n_paths=paths.n_paths, seed=paths.seed, optimise="no",
                                        calibration_version=cal.version)
        inp = svc.read_findings(paths.life_balance_sheet_id, paths.client_ref, cal)
        if inp.findings.artefact_id != findings.artefact_id:
            raise LbsimError("The Life Balance Sheet or its records have changed since these paths were computed.")
        inp.bundle = svc.read_market(inp, paths.allocation_id, scenarios or None)
        fmre = paths.provenance.upstream.get("fmre") or {}
        if (inp.bundle.upstream["pcp"]["sha256"] != (paths.provenance.upstream.get("pcp") or {}).get("sha256")
                or inp.bundle.key_parts["return_set_ids"] != fmre.get("return_set_ids")
                or inp.bundle.key_parts["inflation_sha256"] != fmre.get("inflation_sha256")):
            raise LbsimError("The allocation or fmre's figures have changed since these paths were computed; run the "
                             "outlook again.")
        plan = svc.resolve_plan(inp, sim_req)
        designated = inp.request.mandate.goal_id if inp.request.mandate else None
        problem = P.plan_problem(paths=paths, plan=plan, bundle=inp.bundle, calibration=cal, designated=designated,
                                 seed=int(req.get("seed", paths.seed)),
                                 max_solve_horizon_years=self.cfg.max_solve_horizon_years)
        return {"problem": problem, "paths": paths, "findings": findings, "calibration": cal}


_STOPPED = {
    "cancelled": "Cancelled while calculating; no figures are reported.",
    "superseded": "A newer calculation for this household replaced this one while it ran; no figures are reported.",
    "timed_out": "The plan calculation ran past its time budget; no figures are reported.",
    "solver": "The optimiser found no reliable result; no figures are reported.",
}
