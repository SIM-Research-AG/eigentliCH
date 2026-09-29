"""The optimisation model of record, and the comparison branch.

`objective` is the asymmetric squared shortfall the framework specifies. `constraints` assembles the
mandate's bounds in the one order the rows are meaningful in. `optimiser_curve` solves it.
`optimiser_mv` is a mean-variance comparison, labelled as such wherever it appears, and is not the model
of record.
"""

from pcp.model.constraints import ConstraintSystem, build_constraints, realised_exposures
from pcp.model.objective import curve_objective, curve_objective_gradient, shortfall_by_state
from pcp.model.pfmap import portfolio_map, role_allocation
from pcp.model.optimiser_curve import SolveResult, solve_curve

__all__ = [
    "ConstraintSystem",
    "SolveResult",
    "build_constraints",
    "curve_objective",
    "curve_objective_gradient",
    "portfolio_map",
    "realised_exposures",
    "role_allocation",
    "shortfall_by_state",
    "solve_curve",
]
