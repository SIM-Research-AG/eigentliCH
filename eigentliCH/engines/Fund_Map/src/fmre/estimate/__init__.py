"""Return-estimation engine (spec section 5)."""

from fmre.estimate.aggregate import (
    RoleClassification,
    ScenarioProfile,
    aggregate_to_scenarios,
    classify_role,
)
from fmre.estimate.block import (
    BlockEstimate,
    Coverage,
    Method,
    StateEstimate,
    estimate_block,
)
from fmre.estimate.coverage import (
    CoverageReport,
    build_coverage_matrix,
    portfolio_scenario_return,
    resilience,
)
from fmre.estimate.map_states import bucket_returns_by_state
from fmre.estimate.mixture import (
    MixtureDecomposition,
    empirical_mixture_decomposition,
    mixture_recompose_error,
)
from fmre.estimate.per_state import (
    annualise_estimate,
    estimate_per_state_from_buckets,
)

__all__ = [
    "BlockEstimate",
    "Coverage",
    "Method",
    "StateEstimate",
    "estimate_block",
    "bucket_returns_by_state",
    "estimate_per_state_from_buckets",
    "annualise_estimate",
    "MixtureDecomposition",
    "empirical_mixture_decomposition",
    "mixture_recompose_error",
    "ScenarioProfile",
    "RoleClassification",
    "aggregate_to_scenarios",
    "classify_role",
    "CoverageReport",
    "build_coverage_matrix",
    "portfolio_scenario_return",
    "resilience",
]
