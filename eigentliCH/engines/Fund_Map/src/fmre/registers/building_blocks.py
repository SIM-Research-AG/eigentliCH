"""Fund Map register: load, validate, and expose the building-block universe.

The seed CSV at ``fmre/registers/seed/fund_map_seed.csv`` is the bootstrap
dataset per spec section 4.1. Loading it is the first acceptance test.

State axis convention (see decisions.md D1): index 0 is the worst / crisis-like
state; index 24 is the best / boom-like state.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Iterator

STATE_GRID: int = 25


class AssetClass(str, Enum):
    EQUITY = "Equity"
    FIXED_INCOME = "Fixed Income"
    REAL_ESTATE = "Real Estate"
    ALTERNATIVE = "Alternative"
    CASH = "Cash"


class Role(str, Enum):
    """Role as authored in the seed (US spelling preserved)."""

    GROWTH = "Growth"
    INCOME = "Income"
    STABILIZATION = "Stabilization"
    PROTECTION = "Protection"

    def canonical(self) -> "CanonicalRole":
        return _ROLE_TO_CANONICAL[self]


class CanonicalRole(str, Enum):
    """The four framework roles, British spelling (spec 3.1)."""

    GAIN = "Gain"
    INCOME = "Income"
    STABILISATION = "Stabilisation"
    PROTECTION = "Protection"


_ROLE_TO_CANONICAL: dict[Role, CanonicalRole] = {
    Role.GROWTH: CanonicalRole.GAIN,
    Role.INCOME: CanonicalRole.INCOME,
    Role.STABILIZATION: CanonicalRole.STABILISATION,
    Role.PROTECTION: CanonicalRole.PROTECTION,
}


class Scenario(str, Enum):
    """Home-scenario labels observed in the seed (no `Boom` — see D3)."""

    EXPANSION = "Expansion"
    STAGNATION = "Stagnation"
    CONTRACTION = "Contraction"
    CRISIS = "Crisis"


class Region(str, Enum):
    """The regime signal scope, not a place.

    This is which macro Regime applies to a block, which is why `MXWO0FD Index` (a World index) reads
    `Europe` in the seed. It is published as `region_scope` and must never be used as geography. The
    geographic field is `RegionGeo` below. See decisions.md D11.
    """

    EUROPE = "Europe"
    AMERICAS = "Americas"
    ASIA = "Asia"
    SINO = "Sino"
    GLOBAL = "Global"


class RegionGeo(str, Enum):
    """Where the exposure actually is.

    The seven-value vocabulary the downstream regional allocation constraint is assembled over, in the
    order that constraint expects. Order is load-bearing there, so it is fixed here.

    `Others` covers an exposure with no single geography (a World index, gold, bitcoin, a global
    hedge-fund index) rather than an unknown one. Assignments and their basis are recorded in
    docs/region_assignments.md, which separates what was read from a ticker from what was inferred.
    """

    SWITZERLAND = "Switzerland"
    EUROPE = "Europe"
    EAST_ASIA = "East Asia"
    SOUTH_ASIA = "South Asia"
    NORTH_AMERICA = "North America"
    SOUTH_PACIFIC = "South Pacific"
    OTHERS = "Others"


class EconomicPhase(str, Enum):
    """Seed labels. `Maturing ~ Build-up` in the macro Regime (see D2)."""

    FOUNDATION = "Foundation"
    MATURING = "Maturing"
    OPTIMIZING = "Optimizing"
    SATURATION = "Saturation"


class CapitalType(str, Enum):
    REAL = "Real"
    FINANCIAL = "Financial"


class Liquidity(str, Enum):
    DAILY = "Daily"
    QUARTERLY = "Quarterly"
    YEARLY = "Yearly"
    DECADE = "Decade"


@dataclass(frozen=True, slots=True)
class BuildingBlock:
    """One row of the Fund Map register.

    Fields mirror the spec 3.1 schema. `ret_distribution` is length exactly
    ``STATE_GRID`` and is ordered crisis (index 0) to boom (index 24).
    """

    id: int
    name_en: str
    name_de: str | None
    ticker: str
    asset_class: AssetClass
    role: Role
    home_scenario: Scenario
    ret_distribution: tuple[float, ...]
    #: The regime signal scope. Which Regime applies to this block, not where it is.
    region: Region
    #: Where the exposure is. Drives the downstream regional allocation constraint.
    region_geo: RegionGeo
    economic_phase: EconomicPhase
    capital_type: CapitalType
    currency: str
    liquidity: Liquidity
    esg: int

    def __post_init__(self) -> None:
        if len(self.ret_distribution) != STATE_GRID:
            raise ValueError(
                f"BuildingBlock id={self.id} '{self.name_en}': "
                f"ret_distribution length={len(self.ret_distribution)}, "
                f"expected {STATE_GRID}"
            )

    @property
    def canonical_role(self) -> CanonicalRole:
        return self.role.canonical()


class SeedLoadError(ValueError):
    """Raised when the seed CSV cannot be parsed into valid BuildingBlocks."""


def _real_seed_path() -> Path:
    """The production register's path on disk, always.

    Separate from `_seed_path` on purpose. `_seed_path` is what a bare `load_seed()` consults, and the Fund
    Map's own test suite replaces it with a fixture register (see `tests/conftest.py`). A test that means the
    *live* register therefore cannot go through `_seed_path`, or it would silently read the fixture and assert
    nothing about production. This function is the honest route to the real file and is not patched.
    """
    return Path(resources.files("fmre.registers").joinpath("seed/fund_map_seed.csv"))


def _seed_path() -> Path:
    return _real_seed_path()


def _split_names(raw: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) == 1:
        return parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1]
    raise SeedLoadError(f"names field has {len(parts)} comma-separated parts, expected 1 or 2: {raw!r}")


def _parse_distribution(raw: str, row_id: int) -> tuple[float, ...]:
    parts = [p.strip() for p in raw.split(",")]
    try:
        values = tuple(float(p) for p in parts)
    except ValueError as exc:
        raise SeedLoadError(f"row id={row_id}: ret_distribution parse error: {exc}") from exc
    if len(values) != STATE_GRID:
        raise SeedLoadError(
            f"row id={row_id}: ret_distribution length={len(values)}, expected {STATE_GRID}"
        )
    return values


def _coerce_enum(enum_cls: type[Enum], raw: str, row_id: int, field: str) -> Enum:
    try:
        return enum_cls(raw)
    except ValueError as exc:
        allowed = ", ".join(sorted(e.value for e in enum_cls))
        raise SeedLoadError(
            f"row id={row_id}: unknown {field}={raw!r}. Allowed: {allowed}"
        ) from exc


def load_seed(path: Path | str | None = None) -> list[BuildingBlock]:
    """Load and validate the seed register.

    Returns a list of typed BuildingBlock records. Raises SeedLoadError on the
    first parse or validation failure with a clear per-row message.
    """
    csv_path = Path(path) if path is not None else _seed_path()
    blocks: list[BuildingBlock] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        expected_cols = {
            "ID", "names", "Ticker", "Asset Class", "Portfolio Role", "Portfolio Scenario",
            "Ret Distribution", "Risk Signal", "Economic Phase", "Capital Type",
            "Currency", "Liquidity", "ESG", "Region",
        }
        missing = expected_cols - set(reader.fieldnames or [])
        if missing:
            raise SeedLoadError(f"seed CSV missing columns: {sorted(missing)}")
        for row in reader:
            try:
                row_id = int(row["ID"])
            except (ValueError, TypeError) as exc:
                raise SeedLoadError(f"invalid ID: {row.get('ID')!r}") from exc
            name_en, name_de = _split_names(row["names"].strip())
            block = BuildingBlock(
                id=row_id,
                name_en=name_en,
                name_de=name_de,
                ticker=row["Ticker"].strip(),
                asset_class=_coerce_enum(AssetClass, row["Asset Class"].strip(), row_id, "Asset Class"),  # type: ignore[arg-type]
                role=_coerce_enum(Role, row["Portfolio Role"].strip(), row_id, "Portfolio Role"),  # type: ignore[arg-type]
                home_scenario=_coerce_enum(Scenario, row["Portfolio Scenario"].strip(), row_id, "Portfolio Scenario"),  # type: ignore[arg-type]
                ret_distribution=_parse_distribution(row["Ret Distribution"], row_id),
                region=_coerce_enum(Region, row["Risk Signal"].strip(), row_id, "Risk Signal"),  # type: ignore[arg-type]
                region_geo=_coerce_enum(RegionGeo, row["Region"].strip(), row_id, "Region"),  # type: ignore[arg-type]
                economic_phase=_coerce_enum(EconomicPhase, row["Economic Phase"].strip(), row_id, "Economic Phase"),  # type: ignore[arg-type]
                capital_type=_coerce_enum(CapitalType, row["Capital Type"].strip(), row_id, "Capital Type"),  # type: ignore[arg-type]
                currency=row["Currency"].strip(),
                liquidity=_coerce_enum(Liquidity, row["Liquidity"].strip(), row_id, "Liquidity"),  # type: ignore[arg-type]
                esg=int(row["ESG"]),
            )
            blocks.append(block)
    return blocks


def iter_ticker_collisions(blocks: list[BuildingBlock]) -> Iterator[tuple[str, list[int]]]:
    """Yield (ticker, ids) for every instrument named by more than one block.

    **Reported, not refused, and the first version of this did refuse.** The collisions are real and they
    matter: in the 54-row register four tickers were shared across nine blocks, and because the estimator's
    input is the ticker, those blocks published **byte-identical** `profile_by_state`. Measured on the
    artefact, 54 blocks carried 49 distinct profiles and every collision was a duplicate ticker. The
    optimiser was offered the same column twice under two names, so the weight split between them was
    arbitrary rather than chosen. `MXWO Index` served as Global Equities, Fundo World Equity *and* Mining
    Equities, which is a plain error in the last case.

    It is nevertheless not a load-time refusal, because sharing a ticker across blocks is a **supported
    capability of this engine**, not an accident: `data_series` dedupes the fetch for shared proxies and
    `test_full_seed_proxies_produce_independent_block_estimates` pins that two blocks on one proxy still
    estimate separately. Refusing at load would have deleted a tested feature in order to enforce a policy
    about one particular register. The policy belongs where policy lives — in the register — and the check
    belongs where it can be asserted against production without constraining the engine:
    `tests/test_seed_load.py::test_the_production_register_is_well_formed`.

    So: the eight-instrument production register has no collisions and a test says so. A register that wants
    proxies may still have them, and this function is how a reviewer sees them.
    """
    seen: dict[str, list[int]] = {}
    for b in blocks:
        seen.setdefault(b.ticker, []).append(b.id)
    for ticker, ids in seen.items():
        if len(ids) > 1:
            yield ticker, ids


def iter_profile_collisions(blocks: list[BuildingBlock]) -> Iterator[tuple[tuple[float, ...], list[int]]]:
    """Yield (profile, ids) for every authored return distribution shared by more than one block.

    **This is reported, not refused, and the distinction was measured rather than assumed.** A shared seed
    profile does *not* make two blocks interchangeable downstream: the Fund Map estimates per block, and
    `home_scenario` and `region_scope` enter that estimate, so blocks with the same authored row routinely
    publish different profiles. In the 54-row register 24 blocks shared just two authored profiles, yet the
    published ReturnSet carried 49 distinct ones. An earlier reading of this file concluded the effective
    universe was 30 wide; that was wrong, and it was wrong because it read the seed instead of the artefact.

    What a collision does mean is that the *author* did not differentiate two instruments, which is worth
    seeing when reviewing a register even though it is not by itself a defect.
    """
    seen: dict[tuple[float, ...], list[int]] = {}
    for b in blocks:
        seen.setdefault(b.ret_distribution, []).append(b.id)
    for profile, ids in seen.items():
        if len(ids) > 1:
            yield profile, ids


# ---------------------------------------------------------------------------
# Invariants used by the seed-integrity tests (spec section 8, test 1) and by
# any downstream consumer that wants to check a mutated universe.
# ---------------------------------------------------------------------------


def iter_role_violations(blocks: list[BuildingBlock]) -> Iterator[tuple[BuildingBlock, str]]:
    """Yield (block, reason) for every block whose ret_distribution shape does
    not match the invariant for its role (see D9 in decisions.md).

    - Growth: mean(last 5) > mean(first 5). Net ascending.
    - Protection: either (a) mean(first 5) >= mean(last 5) [hedge], or
      (b) max(|value|) <= 5 [low-volatility floor, e.g. cash].
    - Income: bounded-magnitude, max(|value|) <= 60. Shape is not constrained
      beyond bounds because Income covers both flat-plateau (row 21 Global
      Govs) and ascending (row 20 Global Bonds).
    - Stabilisation: bounded-magnitude, max(|value|) <= 30. Shape unconstrained
      (row 34 Commodities, row 52 Digital Assets, row 54 Trend Following all
      have complex, bounded shapes).
    """
    for b in blocks:
        vals = b.ret_distribution
        first5 = sum(vals[:5]) / 5.0
        last5 = sum(vals[-5:]) / 5.0
        max_abs = max(abs(v) for v in vals)
        role = b.role
        if role is Role.GROWTH:
            if not (last5 > first5):
                yield b, f"Growth block not net-ascending: mean(first 5)={first5:.2f}, mean(last 5)={last5:.2f}"
        elif role is Role.PROTECTION:
            hedge_ok = first5 >= last5
            floor_ok = max_abs <= 5.0
            if not (hedge_ok or floor_ok):
                yield b, (
                    f"Protection block is neither descending (first5={first5:.2f} < last5={last5:.2f}) "
                    f"nor a low-volatility floor (max|value|={max_abs:.2f} > 5)"
                )
        elif role is Role.INCOME:
            if max_abs > 60.0:
                yield b, f"Income block magnitude out of bounds: max|value|={max_abs:.2f} > 60"
        elif role is Role.STABILIZATION:
            if max_abs > 30.0:
                yield b, f"Stabilization block magnitude out of bounds: max|value|={max_abs:.2f} > 30"
