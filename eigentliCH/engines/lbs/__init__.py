"""Life Balance Sheet: the household ALM engine, and the mandate derived from it.

Two modules:

- `adapter.py` wraps `personal_alm` unchanged and produces a household `Trajectory`.
- `derive.py` derives the `BalanceSheetSnapshot`, including the mandate the Optimiser reads.

The derivation lives here rather than in an adapter between the two engines, per `DECISIONS.md` M4: the
required return is what makes *this household's* goal attainable, and the position cap follows from *its*
buffer, so the engine that owns the household's economics owns the derivation.

**Why this package is `lbs` and not `life_balance_sheet`.** The engine is registered under the name
`life_balance_sheet`, and the project it wraps now sits at `engines/Life_Balance_Sheet`. Windows filesystems
are case-insensitive, so a package named `life_balance_sheet` resolves to the *same directory* as the vendored
project, and its files land inside it among the project's own documents. The other three wrapped engines do not
collide because their registry names differ from their project directory names. See `DECISIONS.md` M13.
"""

from engines.lbs.adapter import DEFAULT_CONTROL, LifeBalanceSheetAdapter
from engines.lbs.derive import (
    CURVE_HORIZON_YEARS,
    DEFAULT_POLICY_CAP,
    POLICY_BOUNDS,
    DerivationInputs,
    derive_snapshot,
    render_mandate_yaml,
)

__all__ = [
    "CURVE_HORIZON_YEARS",
    "DEFAULT_CONTROL",
    "DEFAULT_POLICY_CAP",
    "POLICY_BOUNDS",
    "DerivationInputs",
    "LifeBalanceSheetAdapter",
    "derive_snapshot",
    "render_mandate_yaml",
]
