"""Contracts: every model ``pcp`` consumes or produces.

Inbound, from upstream engines, mirrored here and never imported (Engine Building Guide section 1):

* ``Regime`` from ``aggregation`` (``aggregation-regime@1.0.0``): the 25-state distribution per economy and
  per market blend, per month, and the ``regime_id``. Mirrored partially: the fields ``pcp`` reads, the
  version pinned exactly, everything else ignored.
* ``ReturnSet`` from ``fmre`` (``rs@1.0.0``): 25-state profiles per instrument, as annualised log returns,
  each state with its estimation method, measured in the currency pcp asked for (D-01, PCP-18). No moments.
* ``InstrumentOut`` from ``fmre``'s register: the classification of every instrument.

Own contracts, frozen, extra fields forbidden:

* ``Mandate`` (``pcp-mandate@1.0.0``): the client's target curve, universe and bounds, the economy weights
  the client's Regime is blended from (PCP-04), and the reporting currency (CHF, EUR or USD, PCP-18) every
  return figure is in, the target curve included. An optional ``basis`` (``nominal`` by default, or ``real``)
  says whether the target curve, and so every return figure, is nominal or net of the reporting currency's
  inflation (PCP-22).
* ``PCPRunRequest`` (``pcp-run@1.0.0``), body of ``POST /run`` and ``POST /validate``.
* ``Allocation`` (``pcp-allocation@1.0.0``): weights per instrument, raw and renormalised separately labelled,
  the same weights by role, the portfolio map, the curves, diagnostics and provenance.
  Constructed unreleased; a released one cannot be built (Manual section 15.7 test 6).
* ``Calibration`` (``pcp-calibration@1.0.0``): vocabularies, ingest maps, solver settings, the budget check and
  the instrument classification table. Immutable per version.

States run 1 (crisis, most cautious) to 25 (boom, most aggressive) on both upstream axes; ``pcp`` matches them
state for state (PCP-05).
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

N_STATES = 25

CONTRACT_VERSIONS: dict[str, str] = {
    "Mandate": "pcp-mandate@1.0.0",
    "PCPRunRequest": "pcp-run@1.0.0",
    "Allocation": "pcp-allocation@1.0.0",
    "ValidationReport": "pcp-validation@1.0.0",
    "Calibration": "pcp-calibration@1.0.0",
    "Regime(aggregation)": "aggregation-regime@1.0.0",
    "ReturnSet(fmre)": "rs@1.0.0",
    # fmre does not version its register rows; the mirror reads the fields named below (PCP-09).
    "InstrumentOut(fmre)": "fmre-register (unversioned)",
}

NOTICE = "Model-derived research output. Not investment advice."

#: The seven bounded dimensions, in constraint-block order (Manual section 15.2). ESG is a single row
#: between liquidity and phase and is not a dimension of its own.
DIMENSIONS: tuple[str, ...] = ("currency", "region", "role", "capital_type", "liquidity", "phase",
                               "asset_class")

#: Manual section 14.2: which dimensions take their bounds from the household ("derived") and which from
#: the house investment policy ("policy"). A mandate that labels a dimension the other way is refused, in
#: both directions (Manual section 15.7 test 5).
BOUND_SOURCE: dict[str, str] = {
    "currency": "derived", "liquidity": "derived", "role": "derived",
    "asset_class": "policy", "capital_type": "policy", "phase": "policy", "region": "policy",
}

SpeedMode = Literal["fast", "exact"]
CurveUnit = Literal["annualised_log_return", "annualised_decimal"]
BoundSource = Literal["derived", "policy"]

#: D-01 (review dossier) and PCP-18: the currencies a return figure is reported in. The mandate's
#: ``currency`` is one of these; fmre measures the instrument profiles in it on request.
REPORTING_CURRENCIES: tuple[str, ...] = ("CHF", "EUR", "USD")
ReportingCurrency = Literal["CHF", "EUR", "USD"]

#: How fmre names the currency of an opt-in set in its provenance notes today ("... in currency=CHF; ...",
#: or "currency=source" for the unconverted series). Read only while fmre has no structured field (PCP-19).
_NOTED_CURRENCY = re.compile(r"\bin currency=([A-Za-z]+)\b")

#: The nominal and real view (REAL_VIEW_INTERFACES.md, PCP-22): the basis of the mandate's target curve and so
#: of every return figure. Real is log-return net of the reporting currency's inflation per regime state,
#: ``real = nominal - ln(1 + inflation)``, deflated by fmre; nominal is the default everywhere.
BASES: tuple[str, ...] = ("nominal", "real")
Basis = Literal["nominal", "real"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _NominalOmitted(_Frozen):
    """A contract that gained an optional ``basis`` (PCP-22) and serialises it only when it is not the default.

    ``nominal`` is left out of the JSON, so every mandate, Allocation and provenance written before the field
    existed, and every nominal one written since, keeps its bytes and its content-addressed id (``mandate_id``,
    the idempotency key, ``artefact_id``). A body without ``basis`` reads back as nominal.
    """

    @model_serializer(mode="wrap")
    def _omit_nominal(self, handler):
        data = handler(self)
        if isinstance(data, dict):
            if data.get("basis") == "nominal":
                data.pop("basis")
            if "hard_currency_fallback" in data and data["hard_currency_fallback"] is None:
                data.pop("hard_currency_fallback")      # PCP-23: stated only when fmre fell back
        return data


#: The keys of fmre's decision-5 fallback (``Deflator.hard_currency_fallback`` in fmre's
#: ``contracts/return_set.py``, built by ``engines/fund_map/inflation.py::hard_currency``).
HARD_CURRENCY_FALLBACK_KEYS: tuple[str, ...] = ("from", "to", "states", "reason")


def check_fallback(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """PCP-23: ``{from, to, states, reason}`` as fmre states it, ``from`` and ``to`` two different reporting
    currencies. Kept exactly as fmre wrote it, never recomputed."""
    if value is None:
        return None
    missing = [k for k in HARD_CURRENCY_FALLBACK_KEYS if k not in value]
    if missing:
        raise ValueError(f"hard_currency_fallback lacks {missing}; fmre states {{from, to, states, reason}}")
    if value["from"] not in REPORTING_CURRENCIES or value["to"] not in REPORTING_CURRENCIES:
        raise ValueError("hard_currency_fallback names a currency outside CHF, EUR, USD")
    if value["from"] == value["to"]:
        raise ValueError("hard_currency_fallback falls back from a currency to itself")
    return value


class _Upstream(BaseModel):
    """A partial mirror: reads the named fields, ignores the rest."""

    model_config = ConfigDict(frozen=True, extra="ignore")


def _check_curve(value: tuple[float, ...], what: str) -> tuple[float, ...]:
    if len(value) != N_STATES:
        raise ValueError(f"{what} has {len(value)} points, expected {N_STATES}")
    if not all(math.isfinite(v) for v in value):
        raise ValueError(f"{what} has a non-finite value")
    return value


# ---------------------------------------------------------------------------
# Upstream mirrors
# ---------------------------------------------------------------------------

Distribution = tuple[float, ...]


class RegimeEconomy(_Upstream):
    code: str
    name: str = ""
    distribution: tuple[Optional[Distribution], ...]


class RegimeMarket(_Upstream):
    code: str
    weights: dict[str, float]
    distribution: tuple[Optional[Distribution], ...]


class RegimeProvenance(_Upstream):
    snapshot_id: str
    as_of: str
    calibration_version: str
    regime_id: str
    optimism_scale: str


class Regime(_Upstream):
    """``aggregation-regime@1.0.0``, as ``pcp`` reads it."""

    contract_version: Literal["aggregation-regime@1.0.0"]
    artefact_id: str
    regime_id: str
    optimism_scale: str
    n_states: Literal[25]
    dates: tuple[str, ...]
    economies: tuple[RegimeEconomy, ...]
    markets: tuple[RegimeMarket, ...] = ()
    provenance: RegimeProvenance

    @model_validator(mode="after")
    def _aligned(self) -> "Regime":
        n = len(self.dates)
        for e in self.economies:
            if len(e.distribution) != n:
                raise ValueError(f"regime economy {e.code} is not aligned to dates")
            for d in e.distribution:
                if d is not None and len(d) != N_STATES:
                    raise ValueError(f"regime economy {e.code} has a distribution of {len(d)} states")
        return self


class ProfileState(_Upstream):
    state: int = Field(ge=1, le=N_STATES)
    value: float
    method: str
    n_obs: int = Field(ge=0)


class Profile(_Upstream):
    key: str
    kind: Literal["role", "instrument", "block"]
    role: Optional[str] = None
    unit: str
    coverage: str
    states: tuple[ProfileState, ...]

    @field_validator("states")
    @classmethod
    def _ordered(cls, value: tuple[ProfileState, ...]) -> tuple[ProfileState, ...]:
        if [s.state for s in value] != list(range(1, N_STATES + 1)):
            raise ValueError("profile states must run 1..25 in order")
        return value


class ReturnSetProvenance(_Upstream):
    calibration_id: str
    regime_id: Optional[str] = None
    #: The currency the instrument profiles are measured in. fmre does not publish this field yet (PCP-19);
    #: read when it does, and then it wins over the notes.
    currency: Optional[str] = None
    universe_version: str
    estimator: str = ""
    notes: tuple[str, ...] = ()
    #: ``nominal`` or ``real`` (REAL_VIEW_INTERFACES.md): the basis the instrument profiles are on. A set that
    #: does not state one is nominal (fmre's sets before the real view, and its default).
    basis: Optional[str] = None
    #: On a real set, how fmre deflated it: ``{currency, index, method, labels per state,
    #: hard_currency_fallback}``. Read as fmre publishes it and reported, never recomputed here.
    deflator: Optional[dict[str, Any]] = None

    @model_serializer(mode="wrap")
    def _omit_unstated(self, handler):
        # The Allocation's ``fmre:sha256`` is the checksum of this mirror: a set that states no basis and no
        # deflator keeps the checksum, and so the Allocation its bytes, it had before these fields (PCP-22).
        data = handler(self)
        if isinstance(data, dict):
            for key in ("basis", "deflator"):
                if data.get(key) is None:
                    data.pop(key, None)
        return data

    def noted_currencies(self) -> tuple[str, ...]:
        """The currencies fmre's notes name for this set (``source`` for unconverted series), in order."""
        return tuple(dict.fromkeys(m.group(1) for n in self.notes for m in _NOTED_CURRENCY.finditer(n)))


class ReturnSet(_Upstream):
    """``rs@1.0.0``, as ``pcp`` reads it."""

    return_set_id: str
    contract_version: Literal["rs@1.0.0"]
    engine_version: str
    as_of: str
    state_grid: Literal[25]
    instrument_profiles: tuple[Profile, ...] = ()
    provenance: ReturnSetProvenance


class InstrumentOut(_Upstream):
    """One row of ``fmre``'s instrument register (``GET /v1/instruments``)."""

    instrument_id: str
    name: str
    role: str
    asset_class: str
    ticker: Optional[str] = None
    region_scope: str
    region_geo: Optional[str] = None
    capital_type: str
    currency: str
    liquidity: Optional[str] = None
    active: bool = True


# ---------------------------------------------------------------------------
# The mandate and the run request
# ---------------------------------------------------------------------------

class Bound(_Frozen):
    """A per-category bound, both ends fractions of the portfolio."""

    lower: float = Field(default=0.0, ge=0.0, le=1.0)
    upper: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "Bound":
        if self.lower > self.upper + 1e-12:
            raise ValueError(f"bound lower {self.lower} exceeds upper {self.upper}")
        return self


class Mandate(_NominalOmitted):
    """The client's mandate: what the portfolio must reach, from what, within which bounds.

    ``regime_weights`` blends the Regime's per-economy distributions for this client (PCP-04); a named
    ``regime_market`` stands for the weights ``aggregation`` published for that market blend. Exactly one
    of the two is given.

    ``currency`` is the reporting and return currency, one of CHF, EUR and USD (D-01, PCP-18): pcp asks fmre
    for the instrument profiles measured in it, and the ``target_curve`` is in it by definition (annualised
    log returns in that currency). It is not an exposure bound: the ``currency`` dimension of ``bounds``
    (CHF, USD, EUR, RMB, ...) limits what the portfolio holds, whatever it is reported in. CHF by default.

    ``basis`` is the basis of the ``target_curve`` (PCP-22): ``nominal`` (the default) or ``real``, annualised
    log returns net of the reporting currency's inflation. pcp asks fmre for the profiles on the same basis.
    A nominal mandate serialises without the field, so its ``mandate_id`` is the one it had before the field
    existed.
    """

    contract_version: Literal["pcp-mandate@1.0.0"] = "pcp-mandate@1.0.0"
    client: str = Field(min_length=1)
    name: str = Field(min_length=1)
    currency: ReportingCurrency = "CHF"
    basis: Basis = "nominal"
    horizon_years: float = Field(default=1.0, gt=0.0)
    curve_unit: CurveUnit = "annualised_log_return"
    target_curve: tuple[float, ...]
    universe: tuple[str, ...] = Field(min_length=1)
    max_single_position: float = Field(gt=0.0, le=1.0)
    esg_min: float = Field(default=0.0, ge=0.0)
    fixed_allocations: dict[str, float] = Field(default_factory=dict)
    bounds: dict[str, dict[str, Bound]] = Field(default_factory=dict)
    bound_sources: dict[str, BoundSource] = Field(default_factory=dict)
    regime_weights: Optional[dict[str, float]] = None
    regime_market: Optional[str] = None

    @field_validator("target_curve")
    @classmethod
    def _curve(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return _check_curve(value, "the target curve")

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: object) -> object:
        if value not in REPORTING_CURRENCIES:
            raise ValueError(f"currency {value!r} is not a reporting currency; pcp reports in "
                             f"{', '.join(REPORTING_CURRENCIES)} (D-01, PCP-18)")
        return value

    @field_validator("basis", mode="before")
    @classmethod
    def _basis(cls, value: object) -> object:
        if value not in BASES:
            raise ValueError(f"basis {value!r} is not one of {', '.join(BASES)}; it is the basis of the target "
                             "curve (PCP-22)")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "Mandate":
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("the universe repeats an instrument")
        for key, weight in self.fixed_allocations.items():
            if key not in self.universe:
                raise ValueError(f"the mandate pins {key}, which is not in its universe")
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"the mandate pins {key} at {weight}, outside [0, 1]")
        if sum(self.fixed_allocations.values()) > 1.0 + 1e-9:
            raise ValueError("the fixed allocations sum to more than 1")
        for dimension in self.bounds:
            if dimension not in DIMENSIONS:
                raise ValueError(f"unknown bound dimension {dimension!r}; expected one of {list(DIMENSIONS)}")
        # Manual section 14.2 / 15.7 test 5: every bounded dimension states its source, and the source must
        # be the one the Manual assigns. Refused in both directions.
        for dimension, source in self.bound_sources.items():
            if dimension not in BOUND_SOURCE:
                raise ValueError(f"bound source given for unknown dimension {dimension!r}")
            if source != BOUND_SOURCE[dimension]:
                raise ValueError(
                    f"the {dimension} bounds are labelled {source!r}, but the Manual (section 14.2) takes "
                    f"{dimension} bounds from the {BOUND_SOURCE[dimension]!r} source; a mislabelled bound "
                    f"source is refused")
        unlabelled = sorted(d for d in self.bounds if d not in self.bound_sources)
        if unlabelled:
            raise ValueError(f"bounds on {unlabelled} name no source; each bounded dimension must say "
                             f"whether it is 'derived' or 'policy' (Manual section 14.2)")
        if (self.regime_weights is None) == (self.regime_market is None):
            raise ValueError("give exactly one of regime_weights (economy code -> weight) or regime_market")
        if self.regime_weights is not None:
            if not self.regime_weights:
                raise ValueError("regime_weights is empty")
            if any(w < 0 or not math.isfinite(w) for w in self.regime_weights.values()):
                raise ValueError("regime_weights must be finite and non-negative")
            if abs(sum(self.regime_weights.values()) - 1.0) > 1e-9:
                raise ValueError(f"regime_weights sum to {sum(self.regime_weights.values())}, not 1")
        return self


class PCPRunRequest(_Frozen):
    """Body of ``POST /run`` and ``POST /validate``."""

    regime_id: str = Field(min_length=1)
    return_set_id: str = Field(min_length=1)
    mandate: Mandate
    #: ``None`` uses ``run.speed_mode`` from ``config.yaml``.
    speed_mode: Optional[SpeedMode] = None
    #: The Regime month to solve (``YYYY-MM`` or ``YYYY-MM-DD``). ``None`` takes the latest month in which
    #: every economy the mandate weights is assessed.
    date: Optional[str] = None
    #: ``None`` uses the active calibration from ``config.yaml``.
    calibration_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class Vocabularies(_Frozen):
    """Bucket labels per dimension. Order is load-bearing: it fixes the constraint rows."""

    currency: tuple[str, ...]
    region: tuple[str, ...]
    role: tuple[str, ...]
    capital_type: tuple[str, ...]
    liquidity: tuple[str, ...]
    phase: tuple[str, ...]
    asset_class: tuple[str, ...]
    scenario: tuple[str, ...]

    def of(self, dimension: str) -> tuple[str, ...]:
        return getattr(self, dimension)


class ObjectiveSpec(_Frozen):
    #: The draft's objective, sum over states of (sum over instruments of max(C - M x BB, 0)) squared
    #: (owner's ruling, 28.09.2026, PCP-03).
    form: Literal["per_instrument_shortfall"] = "per_instrument_shortfall"
    #: Multiplies every profile value inside the objective. 1.0 is the draft; MATLAB effectively used 100
    #: (profiles in percent against a decimal curve). A change is a new calibration.
    profile_scale: float = Field(default=1.0, gt=0.0)


class SpeedSpec(_Frozen):
    ftol: float = Field(gt=0.0)
    maxiter: int = Field(ge=1)


class SolverSpec(_Frozen):
    method: Literal["SLSQP"] = "SLSQP"
    fallback_method: Literal["trust-constr"] = "trust-constr"
    #: Fixed start point, every weight at this value (the draft, D20): deterministic.
    start_value: float = 0.5
    speeds: dict[str, SpeedSpec]


class BudgetCheck(_Frozen):
    """Whether the raw solution meets the budget, read before renormalising (Manual section 15.2).

    ``rounded`` is the legacy check, ``round(sum, decimals) == 1`` (accepts 0.95 to 1.05 at one decimal);
    ``absolute`` requires ``|sum - 1| <= tolerance``.
    """

    mode: Literal["rounded", "absolute"]
    decimals: int = 1
    tolerance: float = 1e-6


class InstrumentClass(_Frozen):
    """What ``fmre``'s register does not carry, per instrument (PCP-06)."""

    name: str
    phase: str
    home_scenario: str
    esg: float
    liquidity: Optional[str] = None
    region: Optional[str] = None


class Calibration(_Frozen):
    contract_version: Literal["pcp-calibration@1.0.0"] = "pcp-calibration@1.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    objective: ObjectiveSpec
    vocabularies: Vocabularies
    #: Dimension -> the label an unknown value folds into. A dimension without one refuses unknown values.
    catch_all: dict[str, str]
    #: Dimension -> upstream spelling -> vocabulary label, applied before classifying.
    ingest_maps: dict[str, dict[str, str]]
    solver: SolverSpec
    budget_check: BudgetCheck
    #: A constraint is reported as binding when its slack is at most this.
    binding_tolerance: float = 1e-6
    #: A note is added when the weights control less than this share of the objective (draft D28).
    leverage_note_below: float = 0.05
    #: Profile methods reported as weak in the coverage (the engine page's open point: reported, not
    #: penalised, PCP-07).
    weak_methods: tuple[str, ...] = ("borrowed", "seed")
    classification: dict[str, InstrumentClass]

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$", value):
            raise ValueError(f"calibration version {value!r} is not semantic")
        return value

    @model_validator(mode="after")
    def _checks(self) -> "Calibration":
        for dimension, label in self.catch_all.items():
            if label not in self.vocabularies.of(dimension):
                raise ValueError(f"catch-all {label!r} is not in the {dimension} vocabulary")
        if len(self.vocabularies.role) != 4 or len(self.vocabularies.scenario) != 5:
            raise ValueError("the portfolio map needs 4 roles and 5 scenarios")
        if "exact" not in self.solver.speeds or "fast" not in self.solver.speeds:
            raise ValueError("the solver needs a fast and an exact speed")
        return self


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class ConstraintRow(_Frozen):
    row: int = Field(ge=1)
    dimension: str
    category: str
    side: Literal["floor", "ceiling"]
    bound: float


class BindingRow(_Frozen):
    row: int = Field(ge=1)
    dimension: str
    category: str
    side: Literal["floor", "ceiling"]
    bound: float
    realised: float


class ValidationReport(_Frozen):
    contract_version: Literal["pcp-validation@1.0.0"] = "pcp-validation@1.0.0"
    ok: bool
    mandate_id: str
    regime_id: str
    return_set_id: str
    #: The mandate's reporting currency, the one the ReturnSet was asked for in (PCP-18).
    currency: Optional[ReportingCurrency] = None
    #: The mandate's basis, the one the ReturnSet was asked for on (PCP-22).
    basis: Optional[Basis] = None
    #: PCP-23: fmre's ``{from, to, states, reason}`` when the real set is measured in a hard currency because
    #: the mandate's inflation left fmre's band. Left out of the JSON when there is none.
    hard_currency_fallback: Optional[dict[str, Any]] = None
    date: Optional[str]
    universe_size: int
    constraint_rows: int
    #: Why the mandate cannot be solved as stated. Empty when ``ok``.
    problems: tuple[str, ...]
    notes: tuple[str, ...] = ()
    notice: str = NOTICE

    @model_serializer(mode="wrap")
    def _omit_no_fallback(self, handler):
        data = handler(self)
        if isinstance(data, dict) and data.get("hard_currency_fallback", 0) is None:
            data.pop("hard_currency_fallback")
        return data


class InstrumentWeight(_Frozen):
    instrument_id: str
    name: str
    role: str
    #: Renormalised to sum to one.
    weight: float
    #: The solver's own solution, before renormalisation.
    raw_weight: float
    #: The weakest estimation method behind the instrument's profile.
    coverage: str


class PortfolioMap(_Frozen):
    """Role by home scenario. ``grid[role][scenario]`` is weight; scenarios crisis first."""

    roles: tuple[str, ...]
    scenarios: tuple[str, ...]
    grid: tuple[tuple[float, ...], ...]


class Curves(_Frozen):
    """Every curve in the Allocation's ``currency`` and on its ``basis``: the target by definition, the
    profiles as fmre measured them in it (PCP-18, PCP-22)."""

    target: tuple[float, ...]
    #: ``x'BB``: what the portfolio returns per state (not what the objective compares).
    achieved: tuple[float, ...]
    #: Per state, the summed positive shortfall before squaring.
    shortfall_by_state: tuple[float, ...]
    #: The blended regime distribution the run was solved against.
    regime: tuple[float, ...]


class Diagnostics(_Frozen):
    objective: float
    #: The objective with nothing allocated (draft D28): the part no weighting reaches.
    objective_floor: float
    #: ``(floor - objective) / floor``; ``None`` when the floor is zero.
    weight_leverage: Optional[float]
    solver_method: str
    solver_status: str
    iterations: int
    success: bool
    constraint_rows: int
    binding: tuple[BindingRow, ...]
    exposures: dict[str, dict[str, float]]
    esg: float
    notes: tuple[str, ...] = ()


class Coverage(_Frozen):
    #: Instrument -> the weakest method behind its profile.
    profile_methods: dict[str, str]
    #: Share of the allocated weight on instruments whose profile's weakest method is a weak one.
    weight_on_weak_profiles: float
    warnings: tuple[str, ...] = ()


class Provenance(_NominalOmitted):
    regime_id: str
    return_set_id: str
    #: The currency the ReturnSet was served in, checked against the mandate's (PCP-18). ``None`` only on
    #: Allocations published before PCP-18, whose profiles were fmre's source-currency default.
    currency: Optional[ReportingCurrency] = None
    #: The basis the ReturnSet was served on, checked against the mandate's (PCP-22). Serialised only when
    #: ``real``; absent means nominal, which every Allocation published before PCP-22 is.
    basis: Basis = "nominal"
    #: PCP-23, decision 5 of the real view: fmre's ``{from, to, states, reason}`` when the mandate's currency
    #: (``from``) left fmre's inflation band and the real set is measured in the hard currency ``to``, which is
    #: then ``currency``. Real only; serialised only when present, so every other Allocation keeps its bytes.
    hard_currency_fallback: Optional[dict[str, Any]] = None
    snapshot_id: str
    as_of: str
    date: str
    upstream: dict[str, str]
    #: The economy weights the client's Regime was blended from.
    regime_weights: dict[str, float]
    regime_market: Optional[str]
    mandate_id: str
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    speed_mode: SpeedMode
    label: Literal["model-derived"] = "model-derived"

    @field_validator("hard_currency_fallback")
    @classmethod
    def _fallback(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return check_fallback(value)


class Allocation(_NominalOmitted):
    """The artefact of one run. Weights per instrument with the ``regime_id`` stamped.

    ``release_state`` is ``unreleased`` and cannot be anything else here: releasing advice is a person's
    act outside this engine (Manual section 15.6, section 21), so constructing a released Allocation raises
    (section 15.7 test 6).
    """

    contract_version: Literal["pcp-allocation@1.0.0"] = "pcp-allocation@1.0.0"
    artefact_id: str
    regime_id: str
    return_set_id: str
    #: The reporting currency of every return figure in this Allocation: the mandate's, and the one the
    #: ReturnSet was measured in (PCP-18). ``None`` only on Allocations published before PCP-18. On a real
    #: Allocation with ``provenance.hard_currency_fallback`` (PCP-23) it is the hard currency the figures are
    #: measured in (the fallback's ``to``), not the mandate's (the fallback's ``from``).
    currency: Optional[ReportingCurrency] = None
    #: The basis of every return figure in this Allocation: the mandate's, and the one the ReturnSet was served
    #: on (PCP-22). Stated in the JSON when ``real``; a body without it is nominal (every Allocation published
    #: before PCP-22, and every nominal one since, byte for byte as before).
    basis: Basis = "nominal"
    mandate_id: str
    client: str
    mandate_name: str
    date: str
    speed_mode: SpeedMode
    calibration_version: str
    release_state: Literal["unreleased"] = "unreleased"
    instruments: tuple[InstrumentWeight, ...]
    raw_weight_sum: float
    #: Read from the raw weights, before renormalising (Manual section 15.2).
    budget_met: bool
    weights_by_role: dict[str, float]
    portfolio_map: PortfolioMap
    curves: Curves
    diagnostics: Diagnostics
    coverage: Coverage
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _shape(self) -> "Allocation":
        for name in ("target", "achieved", "shortfall_by_state", "regime"):
            _check_curve(getattr(self.curves, name), f"curves.{name}")
        if self.provenance.regime_id != self.regime_id:
            raise ValueError("the provenance regime_id differs from the Allocation's")
        if self.provenance.currency != self.currency:
            raise ValueError("the provenance currency differs from the Allocation's")
        if self.provenance.basis != self.basis:
            raise ValueError("the provenance basis differs from the Allocation's")
        fb = self.provenance.hard_currency_fallback
        if fb is not None and (self.basis != "real" or fb["to"] != self.currency):
            raise ValueError("a hard-currency fallback is real only, and its 'to' is the Allocation's currency")
        if self.budget_met and abs(sum(i.weight for i in self.instruments) - 1.0) > 1e-9:
            raise ValueError("renormalised weights must sum to one")
        return self


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    regime_id: str
    idempotency_key: str
    cached: bool


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: PCPRunRequest
    artefact_id: Optional[str]
    regime_id: str
    warnings: tuple[str, ...]
    coverage: Optional[Coverage]
    provenance: Optional[Provenance]
    error: Optional[str]
