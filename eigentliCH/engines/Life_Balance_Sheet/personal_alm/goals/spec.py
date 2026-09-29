"""GoalSpec — the archetype-agnostic goal *input* (bridges the two goal worlds).

A goal is specified once, as data: its kind, deadline, confidence, and the
kind-specific parameters. From that single spec we produce both
  - the Python `Goal` (for Monte-Carlo feasibility, goals.py), and
  - the symbolic slack (for the optimiser's CVaR constraint, optim/symbolic.py).

This is what lets every archetype (home, company, retirement, FI) be an input to
the same engine rather than bespoke code per case (see personal_alm/cases.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import casadi as ca

from ..model.params import Params
from ..optim import symbolic as sym
from . import goals as G

_AT_DEADLINE = {"fi", "retirement"}      # point-in-time funding tests
_BY_DEADLINE = {"home", "company"}       # reach the region by the deadline


@dataclass
class GoalSpec:
    kind: str
    horizon_years: float
    epsilon: float = 0.10
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in _AT_DEADLINE | _BY_DEADLINE:
            raise ValueError(f"unknown goal kind: {self.kind}")

    @property
    def mode(self) -> str:
        return "by_deadline" if self.kind in _BY_DEADLINE else "at_deadline"

    @property
    def name(self) -> str:
        return {"fi": "financial independence", "home": "home purchase",
                "company": "company founding", "retirement": "retirement funding"}[self.kind]

    def to_goal(self) -> G.Goal:
        """Build the Python Goal for Monte-Carlo feasibility."""
        pr, h, e = self.params, self.horizon_years, self.epsilon
        if self.kind == "fi":
            return G.fi_goal(horizon_years=h, epsilon=e, **pr)
        if self.kind == "home":
            return G.home_goal(horizon_years=h, epsilon=e, **pr)
        if self.kind == "company":
            return G.company_goal(horizon_years=h, epsilon=e, **pr)
        return G.retirement_goal(horizon_years=h, epsilon=e, **pr)

    def symbolic_slack(self, x: ca.SX, u: ca.SX, p: Params) -> ca.SX:
        """Symbolic terminal slack for the optimiser's CVaR constraint.

        **The spend targets are indexed here exactly as on the numpy path**, via `G.indexed_spend`. An indexed
        simulator against a nominal optimiser would be worse than no indexing at all: the solver would optimise
        against an easier goal than the one its result is then measured on, and the disagreement would show up as
        an unexplained gap between the in-sample and evaluated feasibility rather than as an error.
        """
        pr = self.params
        if self.kind == "fi":
            # `q_inv` must be threaded explicitly. Both symbolic slack functions default it to 1.0 so that a
            # caller predating step 3 still builds, and that default is exactly what made this test fail on its
            # first run: the numpy path used `p.q_inv = 0.85` while this one silently took 1.0.
            return sym.fi_slack(x, G=G.indexed_spend(pr.get("G", p.G), p.pi, self.horizon_years),
                                swr=pr.get("swr", p.swr),
                                h_res=pr.get("h_res", p.h_res), y_R=p.y_R,
                                q_inv=pr.get("q_inv", p.q_inv),
                                y_hol=p.y_hol, q_hol=pr.get("q_hol", p.q_hol))
        if self.kind == "home":
            return sym.home_slack(x, u, p, price=pr["price"], xi=pr.get("xi", p.xi),
                                  i_calc=pr.get("i_calc", p.i_calc),
                                  maint_rate=pr.get("maint_rate", 0.01),
                                  affordability=pr.get("affordability", 1.0 / 3.0))
        if self.kind == "company":
            return sym.company_slack(x, B_buffer=pr["B_buffer"],
                                     N_min=pr["N_min"], E_min=pr["E_min"])
        return sym.retirement_slack(x, p,
                                    G_ret=G.indexed_spend(pr["G_ret"], p.pi, self.horizon_years),
                                    years_in_retirement=pr["years_in_retirement"],
                                    r_disc=pr.get("r_disc", 0.02), h_res=pr.get("h_res", 0.0),
                                    q_inv=pr.get("q_inv", p.q_inv),
                                    q_hol=pr.get("q_hol", p.q_hol),
                                    horizon_years=self.horizon_years)
