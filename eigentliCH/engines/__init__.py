"""The engine room: every engine reachable through one interface.

Importing this module registers all seven adapters, so `engines.get(name)` works without the caller knowing which
module an engine lives in, or whether it runs in this process. That is Phase 2's "one interface".

    from engines import get, health, registry

    with mediate(agent="investment", purpose="..."):        # Phase 5: not optional, see below
        regime = get("market_signal").run(scope="Global")
        rs     = get("return_estimation").run(scope="Global", regime_id=regime.contract.regime_id)
        rec    = get("portfolio_optimiser").run(mandate="fixture_balanced")
        path   = get("life_balance_sheet").run(household_id="hh-1", W_L=450_000, W_R=1_200_000, D=600_000)

**Four engines run out of process, under their own interpreter**, because their dependencies are mutually
incompatible. No engine's internals were changed. The other three are native to the master model and run here:
they are pure Python over the contracts, so a subprocess would buy nothing. A caller cannot tell from the
interface which kind it is holding. See `base.py` and architecture/DECISIONS.md M6.

**Every call must be mediated.** An engine call outside a control-plane context raises `UnmediatedCall`, guarded
at `EngineAdapter.invoke()` and `EngineAdapter.result()` rather than on each adapter, so a new engine inherits the
rule. See `orchestration.control_plane` and DECISIONS.md M16 to M18.
"""

from engines.base import (
    ENGINE_HOMES,
    EngineAdapter,
    EngineCall,
    EngineFailed,
    EngineResult,
    EngineUnavailable,
    NativeEngineAdapter,
    get,
    health,
    register,
    registry,
)

# Importing each module registers its adapter. Order is not significant.
#
# The first four are wrapped from sibling projects and run out of process, because their dependencies are
# mutually incompatible. The last three are native to the master model and run in this process: they are pure
# Python over the contracts, so a subprocess would buy nothing.
#
# `lbs` rather than `life_balance_sheet`: Windows is case-insensitive, so a package of that name would be the
# same directory as the vendored `engines/Life_Balance_Sheet` project. The engine is still *registered* as
# `life_balance_sheet`. See DECISIONS.md M13.
from engines import lbs, market_signal, portfolio_optimiser, return_estimation  # noqa: F401,E402
from engines import s_curve_trajectory, scenario_generator, score  # noqa: F401,E402

#: All seven canonical engines are now implemented. Kept as an empty tuple rather than deleted, so the registry
#: keeps a place to declare a gap if the register grows.
MISSING_ENGINES: tuple[str, ...] = ()

#: Wrapped from sibling projects, run out of process, internals unchanged.
WRAPPED_ENGINES: tuple[str, ...] = (
    "market_signal",
    "return_estimation",
    "life_balance_sheet",
    "portfolio_optimiser",
)

#: Built here, run in process.
NATIVE_ENGINES: tuple[str, ...] = (
    "s_curve_trajectory",
    "scenario_generator",
    "score_engine",
)

__all__ = [
    "ENGINE_HOMES",
    "MISSING_ENGINES",
    "NATIVE_ENGINES",
    "WRAPPED_ENGINES",
    "EngineAdapter",
    "EngineCall",
    "EngineFailed",
    "EngineResult",
    "EngineUnavailable",
    "NativeEngineAdapter",
    "get",
    "health",
    "register",
    "registry",
]
