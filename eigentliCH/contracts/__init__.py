"""The andersCH contract layer.

Nine contracts, of which seven are defined here and two are **referenced** rather than redefined. Regime and
ReturnSet already exist as typed, versioned, schema-emitting contracts inside the engines that produce them,
and a second definition here would drift from the producer's the first time either changed. See
`references.py`.

    Shared compute (no user data)
      Regime          -> macrofield, contract rtl@0.1.0        referenced
      ReturnSet       -> fmre, contract re@0.2.0               referenced

    [ privacy boundary ]

    Per-user
      FDTEvent                Education-neutral, append-only
      BalanceSheetSnapshot    Education, carries the derived mandate
      Trajectory              Education
      Scenario                Conditional, client-originated changes only
      Score                   Education

    [ regulated wall ]

      Recommendation          Regulated, not advice until released
      AdviceRelease          Regulated, the wall's evidence

Every contract inherits determinism stamps and canonical serialisation from `base.Contract`, so
`hash(inputs + model_version)` and a derived `trace_id` are available uniformly and an unchanged contract is
byte-identical across runs.
"""

from contracts.advice import (
    BindingConstraint,
    Decision,
    AdviceRelease,
    FitQuality,
    Holding,
    Recommendation,
    WallBreach,
    release,
)
from contracts.analysis import (
    Scenario as ScenarioContract,
    ScenarioChange,
    Score,
    ScoreComponent,
    Trajectory,
    TrajectoryPoint,
)
from contracts.base import (
    BoundSource,
    Contract,
    Phase,
    Provenance,
    RegulatedStatus,
    Reliability,
    Role,
    Scenario,
    Sourced,
    canonical_json,
    content_id,
    idempotency_key,
    trace_id_from,
)
from contracts.fdt import EventKind, EventStream, FDTEvent
from contracts.references import (
    ContractUnavailable,
    RegimeMismatch,
    RegimeRef,
    ReturnSetRef,
    load_regime,
    load_returnset,
    require_regime_match,
    resolve_pair,
)
from contracts.snapshot import (
    BalanceSheetSnapshot,
    Bound,
    Costates,
    DerivedMandate,
    GoalRef,
    HouseholdPosition,
    MandateCurve,
    PositionCap,
)

__version__ = "0.1.0"

#: Every contract this layer defines. Used by the schema emitter and the round-trip test, so a new contract
#: cannot be added without both picking it up.
CONTRACTS: tuple[type[Contract], ...] = (
    FDTEvent,
    BalanceSheetSnapshot,
    Trajectory,
    ScenarioContract,
    Score,
    Recommendation,
    AdviceRelease,
)

__all__ = [
    "CONTRACTS",
    "BalanceSheetSnapshot",
    "BindingConstraint",
    "Bound",
    "BoundSource",
    "Contract",
    "ContractUnavailable",
    "Costates",
    "Decision",
    "AdviceRelease",
    "DerivedMandate",
    "EventKind",
    "EventStream",
    "FDTEvent",
    "FitQuality",
    "GoalRef",
    "Holding",
    "HouseholdPosition",
    "MandateCurve",
    "Phase",
    "PositionCap",
    "Provenance",
    "Recommendation",
    "RegimeMismatch",
    "RegimeRef",
    "RegulatedStatus",
    "Reliability",
    "ReturnSetRef",
    "Role",
    "Scenario",
    "ScenarioChange",
    "ScenarioContract",
    "Score",
    "ScoreComponent",
    "Sourced",
    "Trajectory",
    "TrajectoryPoint",
    "WallBreach",
    "__version__",
    "canonical_json",
    "content_id",
    "idempotency_key",
    "load_regime",
    "load_returnset",
    "release",
    "require_regime_match",
    "resolve_pair",
    "trace_id_from",
]
