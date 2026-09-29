"""Life Balance Sheet: the household ALM engine. Reads the FDT and the Regime, writes Snapshot and Trajectory.

Wraps `personal_alm`, unchanged. The household is modelled as a controlled stochastic system: wealth split
liquid / illiquid / debt, plus per-person expertise, network and health, under time and money budgets, with
goals as liabilities that must be met on time at a required confidence.

**What this adapter can and cannot do today, stated rather than glossed.**

It produces a `Trajectory`, which is real: `personal_alm.sim.montecarlo` integrates the system forward and the
result is a genuine projected path.

It does **not** produce a `BalanceSheetSnapshot` with a derived mandate. That derivation is specified in
architecture/DESIGN_snapshot_to_mandate.md and belongs in this engine, but is not built. `snapshot()` raises
rather than returning a snapshot with an authored mandate, because a free parameter standing in for a derived
one is precisely the failure that note exists to prevent.

**The engine has no CLI**, only a web server (`personal_alm.app.server`). So the adapter runs a short inline
programme under the engine's own interpreter, which prints JSON. The programme is held here as a constant so
it is reviewable, and it imports the engine without modifying it.

**It does not read the Regime.** `personal_alm.model.params` carries an explicit seam, "SEAM 4:
regime-switching ... v1 is regime-invariant: `at()` returns self", and the `regime` argument threaded through
the simulator is an integer, not a 25-state distribution. So the manual's `Regime -> Life Balance Sheet` edge
does not exist yet, and the Trajectory this adapter returns carries no `RegimeRef`. See DECISIONS.md M5.
"""

from __future__ import annotations

import json
from typing import Any

from contracts.analysis import Trajectory, TrajectoryPoint
from engines.base import EngineAdapter, EngineFailed, EngineResult, register

#: Run a deterministic forward simulation and print the path as JSON. Deterministic because `rng=None`
#: suppresses the stochastic contribution, which is what makes the result reproducible bit for bit.
_SIMULATE = r"""
import json, sys
from personal_alm.model.controls import Control
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.sim.montecarlo import simulate

args = json.loads(sys.argv[1])
p = Params()
x0 = State.individual(
    W_L=args["W_L"], W_R=args["W_R"], D=args["D"],
    E=args["E"], N=args["N"], H=args["H"], age=args.get("age", 40.0),
        W_res=args.get("W_res"), W_hol=args.get("W_hol", 0.0),
)
c = args["control"]
u = Control(
    tau_Y=c["tau_Y"], tau_E=c["tau_E"], tau_N=c["tau_N"], tau_H=c["tau_H"],
    C=c["C"], m_E=c["m_E"], m_N=c["m_N"], p_A=c["p_A"], theta=c["theta"],
)
if not u.is_admissible():
    print(json.dumps({"error": "the control is not admissible: check the time budget, "
                               "non-negative money flows, and theta in [0, 1]"}))
    raise SystemExit(2)

# The step count comes from the engine's own dt, not from the caller. dt is monthly (1/12), so a ten-year
# horizon is 120 steps rather than 10, and assuming otherwise silently shortens the path by a factor of twelve.
steps = max(1, int(round(float(args["horizon_years"]) / float(p.dt))))
traj = simulate(x0, lambda k, x: u, p, n_steps=steps, rng=None)

out = []
for t, s in zip(traj.times, traj.states):
    out.append({
        "t": float(t),
        "net_worth": float(s.net_worth),
        "W_L": float(s.wealth.W_L),
        "W_R": float(s.wealth.W_R),
        "D": float(s.wealth.D),
    })
print(json.dumps({"path": out, "dt": float(p.dt), "tau_leisure": float(u.tau_leisure)}))
"""

#: A plausible standing control: mostly working, some learning and networking, a little recovery, with a
#: moderate portfolio tilt. Held here as a named default rather than a bare list, because the engine's control
#: is nine named levers and passing them positionally invites silent misalignment.
DEFAULT_CONTROL: dict[str, float] = {
    "tau_Y": 0.45,
    "tau_E": 0.15,
    "tau_N": 0.20,
    "tau_H": 0.15,
    "C": 90_000.0,
    "m_E": 5_000.0,
    "m_N": 10_000.0,
    "p_A": 20_000.0,
    "theta": 0.45,
}


class LifeBalanceSheetAdapter(EngineAdapter):
    name = "life_balance_sheet"
    produces = "Trajectory"
    model_version = "lbs@0.1.0"

    def run(
        self,
        household_id: str,
        W_L: float,
        W_R: float,
        D: float,
        E: float = 1.0,
        N: float = 1.0,
        H: float = 1.0,
        #: Years. Drives the age-earnings decline in earning_power. Defaults to 40 so any caller that does not
        #: know an age still runs; the roster supplies real ones (PLAN_2026-08.md §0B step 2).
        age: float = 40.0,
    #: Residence and second-home amounts, in CHF. `W_res=None` means all of `W_R` is the residence, which is the
    #: conservative reading — see `HouseholdWealth.W_res`. Only the LET remainder earns rent.
    W_res: float | None = None,
    W_hol: float = 0.0,
        horizon_years: float = 10.0,
        control: Any = None,
        goal_kind: str = "fi",
        target: float | None = None,
        epsilon: float = 0.10,
        as_of: str = "2024-12-31",
        **_: Any,
    ) -> EngineResult:
        """Simulate the household forward and return a Trajectory.

        Deterministic: the simulation is run with no random generator, so the stochastic contribution is
        suppressed and the same inputs give the same path.
        """
        arguments = {
            "W_L": W_L, "W_R": W_R, "D": D, "E": E, "N": N, "H": H, "age": float(age),
            **({} if W_res is None else {"W_res": float(W_res)}),
            "W_hol": float(W_hol),
            # The horizon in years. The step count is derived inside the engine from its own dt, so the
            # adapter never has to know or guess the discretisation.
            "horizon_years": float(horizon_years),
            # The engine's nine named control levers. Passed through unchanged rather than interpreted here.
            "control": dict(control) if control is not None else dict(DEFAULT_CONTROL),
        }
        call, stdout, stderr = self.invoke(
            ["-c", _SIMULATE, json.dumps(arguments)], timeout=600
        )

        try:
            payload = json.loads(stdout[stdout.find("{"):])
        except (ValueError, json.JSONDecodeError) as error:
            raise EngineFailed(
                f"the Life Balance Sheet produced no usable path: {error}",
                call.command, stdout, stderr,
            ) from error

        points = tuple(
            TrajectoryPoint(t_years=float(row["t"]), value=float(row["net_worth"]))
            for row in payload["path"]
        )
        final = points[-1].value

        trajectory = Trajectory(
            as_of=as_of,
            model_version=self.model_version,
            household_id=household_id,
            goal_kind=goal_kind,
            goal_ref=f"{goal_kind}-{horizon_years:g}y",
            horizon_years=float(horizon_years),
            epsilon=epsilon,
            points=points,
            target=target,
            on_track=None if target is None else bool(final >= target),
            # No RegimeRef: this engine does not read the Regime yet. See the module docstring and M5.
            regime=None,
        )

        notes = [
            "deterministic run: the stochastic contribution is suppressed, so this is the expected path and "
            "carries no confidence band. A band needs the Monte-Carlo or CVaR route.",
            "the engine does not read the Regime. Its regime seam is a documented no-op, so this path is "
            "regime-invariant. See architecture/DECISIONS.md M5.",
        ]
        if target is not None and not trajectory.on_track:
            notes.append(
                f"the projected path reaches {final:,.0f} against a target of {target:,.0f}, so the goal is "
                f"not met on the expected path."
            )

        return self.result(
            contract=trajectory,
            call=call,
            inputs=arguments | {"goal_kind": goal_kind, "epsilon": epsilon, "target": target},
            as_of=as_of,
            notes=notes,
            raw={"dt": payload.get("dt"), "steps": len(points)},
        )

    def snapshot(
        self,
        inputs: Any,
        regime: RegimeRef,
        returnset_payload: Any,
        universe: Any = None,
        **_: Any,
    ) -> EngineResult:
        """Derive a `BalanceSheetSnapshot`, mandate included.

        The v1 of `architecture/DESIGN_snapshot_to_mandate.md`. The target curve is the annual return this
        household's goal requires, the position caps come from its goal buffer against each block's published
        crisis loss, and liquidity and currency bounds follow from the goal. The five dimensions a household
        model cannot derive stay CIO policy and are labelled as such.

        The curve is flat and says so: a state-varying required return needs household parameters that respond
        to the macro state, and the regime seam is a no-op (M5).

        Args:
            inputs: A `DerivationInputs`.
            regime: The Regime the snapshot is computed under, stamped onto it.
            returnset_payload: The published ReturnSet, for each block's crisis return and metadata.
            universe: Restrict the investable set. Defaults to the whole ReturnSet.
        """
        from engines.lbs.derive import derive_snapshot

        snapshot, notes = derive_snapshot(
            inputs, regime=regime, returnset_payload=returnset_payload, universe=universe
        )
        return self.result(
            contract=snapshot,
            call=self._derivation_call(),
            inputs={
                "household_id": inputs.household_id,
                "position": {"W_L": inputs.W_L, "W_R": inputs.W_R, "D": inputs.D},
                "goal": {
                    "kind": inputs.goal_kind,
                    "target": inputs.target,
                    "horizon_years": inputs.horizon_years,
                    "epsilon": inputs.epsilon,
                },
                "annual_contribution": inputs.annual_contribution,
                "regime_id": regime.regime_id,
            },
            as_of=inputs.as_of,
            notes=notes,
            raw={
                "required_return": snapshot.mandate.curve.required_return,
                "buffer": snapshot.goal.buffer,
                "feasible": snapshot.goal.feasible,
                "caps_derived": snapshot.mandate.position_cap.derived,
                "bound_sources": snapshot.mandate.sources_in_use(),
                "snapshot_id": snapshot.snapshot_id(),
            },
        )

    def _derivation_call(self):
        """The derivation runs in this process even though the simulation does not.

        `personal_alm` is only needed for the household path; the mandate derivation is closed-form over the
        goal, so it does not inherit that engine's convergence as a correctness risk. M11's solver failures
        were fixed on 1 August 2026; the separation is kept because it is the right shape, not because the
        solve was broken.
        """
        from engines.base import EngineCall

        return EngineCall(
            engine=self.name,
            command=("<in-process>", "engines.lbs.derive.derive_snapshot"),
            cwd=str(self.home),
            returncode=0,
        )

    def smoke(self) -> EngineResult:
        """A plausible household, ten years forward."""
        return self.run(
            household_id="smoke-household",
            W_L=450_000, W_R=1_200_000, D=600_000,
            E=1.4, N=0.9, H=0.85,
            horizon_years=10.0,
            goal_kind="fi",
            target=2_000_000,
        )


register(LifeBalanceSheetAdapter())
