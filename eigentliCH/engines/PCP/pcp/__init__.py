"""Portfolio Creation Program (PCP): the Portfolio Optimiser of the shared macro compute path.

Consumes the Regime timeline (from the macro field-model programme) and the ReturnSet (from the Fund
Map and Return Estimation programme), both by reference and read-only, and produces a client
allocation whose blended return profile best matches the mandate's target curve under the mandate's
constraints, integrated over the live Regime.

The optimisation model of record is an asymmetric squared-shortfall curve fit, not mean-variance.
There is no expected-return vector, no variance, and no covariance matrix in the objective. A
mean-variance branch exists for comparison only and is labelled as such wherever it appears.

This is decision-support and research tooling, not investment advice.
"""

__version__ = "0.1.0"

ENGINE_VERSION = f"pcp@{__version__}"
