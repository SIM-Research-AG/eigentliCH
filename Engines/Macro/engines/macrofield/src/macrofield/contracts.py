"""Contracts: every model this engine consumes or produces.

The contracts are the only thing another engine may rely on, so they depend on nothing in
this package. Every model is frozen and forbids extra fields. Collections are tuples.

Missing values travel as ``None``: JSON has no NaN, and a missing value must stay visibly
missing all the way to the consumer. A value that is present is always finite.

Paths are **column oriented**: every per-year tuple of an :class:`EconomyState` is aligned
to that economy's ``years``. Years need not be consecutive, because a year with any required
input missing is dropped rather than filled.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional, Union

from pydantic import (BaseModel, ConfigDict, Field, field_validator, model_serializer,
                      model_validator)

#: Contract versions this engine speaks. Bump on any change to a model's fields.
CONTRACT_VERSIONS: dict[str, str] = {
    "MacroRunRequest": "macrofield-run@1.1.0",
    #: Unchanged at 1.2.0 on purpose: cycle and aggregation pin this literal, and every field
    #: added since (inside Projection and Provenance) is optional and omitted while unset.
    "MacroState": "macrofield-state@1.2.0",
    #: 1.5.0 adds ``investment_share`` and ``projection.parameters_within_ranges`` (TB-27), both
    #: omitted while unset, so every earlier calibration hashes exactly as it was stored.
    "Calibration": "macrofield-calibration@1.5.0",
    "DataNeed": "macrofield-data-need@1.0.0",
    "ProjectionRequest": "macrofield-projection-request@1.1.0",
    "Projection": "macrofield-projection@1.2.0",
}

#: Printed on every artefact and in the README. House rule.
NOTICE = (
    "Model-derived research output of the three-body capital-saturation model. Simulated "
    "paths are illustrative consequences of the calibrated model, not forecasts. "
    "Not investment advice."
)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_CODE = re.compile(r"^[A-Z]{2}$")

Number = Optional[float]
Path = tuple[Number, ...]

Phase = Literal[1, 2, 3, 4]
PHASE_LABELS: dict[int, str] = {
    1: "Foundation",
    2: "Build-up",
    3: "Optimisation",
    4: "Saturation and reordering",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _omit_unset(data: dict, keys: tuple[str, ...]) -> dict:
    """Drop ``keys`` whose value is unset (None or empty). Fields added to a published model
    are omitted from its serialisation while unset, so every calibration hash and every
    artefact of an earlier version serialises exactly as it did before the field existed."""
    for key in keys:
        if key in data and (data[key] is None or (isinstance(data[key], (tuple, list, dict))
                                                  and len(data[key]) == 0)):
            del data[key]
    return data


def _finite_or_none(values: tuple) -> tuple:
    for v in values:
        if v is not None and not math.isfinite(v):
            raise ValueError("values must be finite or null")
    return values


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

StimulusProxy = Literal["fiscal_balance", "net_new_credit"]
#: ``bis_credit``: BIS total credit to the non-financial sector over GDP, times the credit uplift.
#: ``bank_balance_sheet``: Genreith's K, the balance-sheet total of all banks over nominal GDP,
#: no uplift (it is already the broad measure the uplift approximates).
#: ``imf_debt``: IMF Global Debt Database private debt plus general government debt over GDP,
#: times the credit uplift; the same concept as BIS total credit, for economies BIS does not
#: cover (checked against BIS where both exist: within a few per cent).
SaturationSource = Literal["bis_credit", "bank_balance_sheet", "imf_debt"]
#: Where the fiscal balance (the stimulus proxy) comes from.
FiscalSource = Literal["world_bank", "imf_weo"]


class EconomySpec(_Frozen):
    """One economy: where its series come from and what is distinctive about it."""

    code: str
    name: str = Field(min_length=1)
    #: World Bank country code (ISO 3166 alpha-3, or an aggregate such as EMU).
    world_bank: str = Field(min_length=3, max_length=3)
    #: BIS borrower country code. ``None`` where BIS publishes no total credit series.
    bis: Optional[str] = None
    #: Penn World Table country code. ``None`` where PWT publishes no capital stock.
    pwt: Optional[str] = None
    stimulus_proxy: StimulusProxy
    saturation_source: SaturationSource = "bis_credit"
    fiscal_source: FiscalSource = "world_bank"
    #: PWT countries whose capital and output are summed into this economy's real-capital ratio
    #: (sum of cn over sum of cgdpo, both at PPP). Empty: the economy's own PWT series.
    pwt_members: tuple[str, ...] = ()
    #: Area code of the bank balance-sheet series (``bank_balance_sheet`` only).
    bank_area: Optional[str] = None
    #: ``bank_balance_sheet`` only: nominal GDP comes from JST before this year and from the World
    #: Bank (national currency) from it on, so that the denominator covers the same territory as
    #: the bank statistics (for Germany: West Germany until the banks include the East in 1990).
    gdp_splice_year: Optional[int] = None
    #: National-currency units of the JST series per unit of the World Bank's (DM per euro).
    jst_currency_divisor: float = Field(default=1.0, gt=0.0)
    #: A fiscal deficit is an injection, so the fiscal balance normally enters sign reversed.
    stimulus_reverse_sign: bool
    #: Depreciation rate used only where PWT publishes none for an extension year.
    depreciation_prior: float = Field(gt=0.0, lt=1.0)
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    note: str = ""

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _CODE.match(v):
            raise ValueError("economy code must be two upper-case letters")
        return v


class Derivative(_Frozen):
    method: Literal["savitzky_golay", "central_difference"] = "savitzky_golay"
    window_years: int = Field(default=5, ge=3)
    polynomial_order: int = Field(default=2, ge=1)


class Integrator(_Frozen):
    method: Literal["Radau", "BDF", "LSODA"] = "Radau"
    rtol: float = Field(default=1e-8, gt=0.0)
    atol: float = Field(default=1e-10, gt=0.0)


class Search(_Frozen):
    """The least-squares search. Looser integrator settings than reporting, see fitting.py."""

    method: Literal["Radau", "BDF", "LSODA"] = "BDF"
    rtol: float = Field(default=1e-6, gt=0.0)
    atol: float = Field(default=1e-8, gt=0.0)
    max_evaluations: int = Field(default=120, ge=1)
    xtol: float = Field(default=1e-10, gt=0.0)
    ftol: float = Field(default=1e-10, gt=0.0)
    diff_step: float = Field(default=1e-4, gt=0.0)
    loss: Literal["linear", "soft_l1", "huber", "cauchy", "arctan"] = "soft_l1"
    f_scale: float = Field(default=1.0, gt=0.0)
    divergence_penalty: float = Field(default=1e3, gt=0.0)


class Bounds(_Frozen):
    lower: float
    upper: float

    @model_validator(mode="after")
    def _ordered(self) -> "Bounds":
        if not self.lower < self.upper:
            raise ValueError("lower must be below upper")
        return self


class PhaseThresholds(_Frozen):
    foundation_saturation_ceiling: float = 1.0
    optimisation_saturation_ceiling: float = 3.5
    saturation_real_to_financial_ceiling: float = 1.0
    production_economy_real_capital_ceiling: float = 1.0
    optimisation_real_capital_ceiling: float = 1.5
    balanced_band: Bounds = Bounds(lower=2.5, upper=3.5)
    unsecured_acceleration_periods: int = Field(default=3, ge=1)
    #: Once saturated, an economy stays in Phase 4 until saturation reaches the Foundation level.
    #: ``True`` runs that latch over the whole published history of the saturation axis, so an
    #: episode before the calibration window carries into it; ``False`` (the prototype's rule)
    #: starts the latch at the window.
    latch_from_full_history: bool = False
    #: Genreith's Phase IV test: loans to domestic non-banks below this share of the bank balance
    #: sheet. Applied only where that share is published (``bank_balance_sheet`` economies);
    #: ``None`` disables it.
    commercial_bank_share_floor: Optional[float] = Field(default=None, gt=0.0, lt=1.0)


ParameterMode = Literal["hold_last", "extend_trend"]

#: The four Phase IV resolution policies of ``Scenario_SAA.m`` (R-005). Engine 09 ``scenario``
#: uses the same ids.
ResolutionPolicyId = Literal["depression", "hyperinflation", "stagflation", "deferral"]
RESOLUTION_POLICIES: tuple[str, ...] = ("depression", "hyperinflation", "stagflation", "deferral")


class InflationSpec(_Frozen):
    """An annual inflation rate per crisis month, one of the three shapes of ``Scenario_SAA.m``.

    ``sigmoid``: from ``start`` to ``end`` with ``midpoint`` and ``steepness`` on t in [0, 1];
    ``reverse`` evaluates it the .m file's depression way (from end to start, then flipped).
    ``exponential``: ``start * exp(log(end / start) * t^power)``. ``hump``: two half Gaussians
    from ``start`` to a peak of ``end`` at ``midpoint`` and back, sigma = distance / ``width_divisor``.
    """

    form: Literal["sigmoid", "exponential", "hump"]
    start: float
    end: float
    midpoint: float = Field(default=0.5, gt=0.0, lt=1.0)
    steepness: float = Field(default=1.0, gt=0.0)
    power: float = Field(default=1.0, gt=0.0)
    width_divisor: float = Field(default=2.5, gt=0.0)
    reverse: bool = False

    @model_validator(mode="after")
    def _positive_for_exponential(self) -> "InflationSpec":
        if self.form == "exponential" and not (self.start > 0.0 and self.end > 0.0):
            raise ValueError("an exponential inflation path needs positive start and end")
        return self


class DefaultsSpec(_Frozen):
    """Share of claims that survive, ``Scenario_SAA.m``'s two-legged curve: by the inflection
    ``first_leg_share`` of the fall has happened on a root-shaped leg, the rest follows on a
    power-shaped one, ending at ``end``."""

    start: float = 1.0
    end: float = Field(gt=0.0, le=1.0)
    inflection: float = Field(default=0.5, gt=0.0, lt=1.0)
    steepness: float = Field(default=2.5, gt=0.0)
    first_leg_share: float = Field(default=0.3, ge=0.0, le=1.0)


class ValuationsSpec(_Frozen):
    """Valuation factor: linear from ``start`` to ``end`` over ``ramp_months``, then held."""

    start: float = 1.0
    end: float = Field(gt=0.0, le=1.0)
    ramp_months: int = Field(ge=1)


class ResolutionPolicy(_Frozen):
    """One Phase IV resolution policy (``Scenario_SAA.m``, one ``case``)."""

    label: str
    #: The target mix over (Boom, Recovery, Contraction, Bust) of the market risk signal. Not
    #: used by this engine; carried so Engine 09 and this engine share one definition.
    target_mix: tuple[float, float, float, float]
    inflation: InflationSpec
    defaults: DefaultsSpec
    valuations: ValuationsSpec
    #: Where in the saturation ceiling band this policy turns: 0 at the lower bound (early and
    #: low), 1 at the upper bound (late and high).
    turn_position: float = Field(ge=0.0, le=1.0)
    corrects_through: str
    mechanism: str
    asset_implication: str

    @field_validator("target_mix")
    @classmethod
    def _mix(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        if any(x < 0 for x in v) or abs(sum(v) - 1.0) > 1e-12:
            raise ValueError("the target mix must be non-negative and sum to one")
        return v


class SaturationCeiling(_Frozen):
    """R-005: a soft ceiling on projected saturation. Growth is damped from ``damping_onset``
    so the path bends and turns inside [``lower``, ``upper``] around ``centre``; there is no
    hard clamp. Each policy turns at its own position in the band."""

    centre: float = Field(gt=0.0)
    lower: float = Field(gt=0.0)
    upper: float = Field(gt=0.0)
    damping_onset: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> "SaturationCeiling":
        if not self.damping_onset < self.lower <= self.centre <= self.upper:
            raise ValueError("need damping_onset < lower <= centre <= upper")
        return self

    def turn_level(self, position: float) -> float:
        return self.lower + position * (self.upper - self.lower)


class ResetOverride(_Frozen):
    """A per-economy reset target, always with its reason."""

    level: float = Field(gt=0.0)
    years: Optional[int] = Field(default=None, ge=30, le=40)
    reason: str = Field(min_length=1)


class ResetSpec(_Frozen):
    """After the acute crisis saturation declines to the reset target over ``years``."""

    years: int = Field(default=35, ge=30, le=40)
    #: ``foundation``: the Foundation level, ``foundation_fraction`` x the Foundation ceiling
    #: (strictly inside Phase 1, so the reordering completes when the reset does).
    target: Literal["foundation"] = "foundation"
    foundation_fraction: float = Field(default=0.95, gt=0.0, lt=1.0)
    overrides: dict[str, ResetOverride] = {}


class CrisisReset(_Frozen):
    """R-005: what happens at the turn. The main path follows the selected policy through the
    acute crisis (``months``), then the reset, then re-integrates the model from the reset
    state with early-phase parameters."""

    months: int = Field(default=60, ge=12, le=120)
    default_policy: ResolutionPolicyId
    policies: dict[ResolutionPolicyId, ResolutionPolicy]
    reset: ResetSpec = ResetSpec()
    #: Window years whose latched phase is 1 or 2 give the post-reset parameters (their mean);
    #: with fewer than three such years, the first ``early_phase_years`` of the window do.
    early_phase_years: int = Field(default=5, ge=2)

    @model_validator(mode="after")
    def _complete(self) -> "CrisisReset":
        if set(self.policies) != set(RESOLUTION_POLICIES):
            raise ValueError(f"policies must define exactly {list(RESOLUTION_POLICIES)}")
        if self.months % 12:
            raise ValueError("the crisis must last whole years (months a multiple of 12)")
        return self


class ProjectionDefaults(_Frozen):
    """How the default projection in every artefact is made. A what-if can override each."""

    horizon: int = Field(default=15, ge=1, le=100)
    #: How p_p, p_b, alpha, p_s and S are carried past the window.
    parameter_mode: ParameterMode = "hold_last"
    #: Phase IV resolution rates: capital destroyed per year under debt deflation, nominal
    #: output growth per year under hyperinflation. Parameters, not predictions. Calibrations
    #: with a ``crisis`` section use its policies instead.
    deflation_capital_decline: float = Field(default=0.06, gt=0.0, lt=1.0)
    inflation_output_growth: float = Field(default=0.18, gt=0.0)
    #: Refuse to project an economy whose calibrated path does not integrate over its window
    #: (the prototype's rule). ``False`` projects it from the observed end state anyway and says so.
    require_integrable_fit: bool = True
    #: Integrated years whose growth rate is compared with the observed one when the model stops.
    extrapolation_window: int = Field(default=5, ge=2)
    max_horizon_attempts: int = Field(default=24, ge=1)
    # -- TB-27 (calibration 1.5.0); omitted from the serialisation while unset -----------
    #: Hold every parameter carried past the window (and the post-reset early-phase parameters)
    #: inside its meaningful range, ``Calibration.parameter_ranges``. The fit bounds only each
    #: parameter's window median by those ranges, so a last year can sit far outside (JP alpha
    #: -3.0, BD -0.46: a negative share of savings, which drains K_I through zero).
    parameters_within_ranges: Optional[bool] = None
    # -- R-005 (calibration 1.4.0); omitted from the serialisation while unset -----------
    #: Project to this calendar year instead of ``horizon`` years past the window end.
    horizon_until: Optional[int] = Field(default=None, ge=2000, le=2200)
    #: Years after this one carry a lower-confidence label; views show up to it by default.
    display_until: Optional[int] = Field(default=None, ge=2000, le=2200)
    saturation_ceiling: Optional[SaturationCeiling] = None
    crisis: Optional[CrisisReset] = None

    @model_validator(mode="after")
    def _crisis_needs_ceiling(self) -> "ProjectionDefaults":
        if (self.crisis is None) != (self.saturation_ceiling is None):
            raise ValueError("saturation_ceiling and crisis go together (R-005)")
        return self

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), ("horizon_until", "display_until",
                                           "saturation_ceiling", "crisis",
                                           "parameters_within_ranges"))


class Calibration(_Frozen):
    """A complete, versioned parameter set. Never edited; a change is a new version."""

    #: 1.4.0 adds the R-005 projection fields, 1.5.0 the bounded investment share (TB-27); a
    #: 1.3.0 or 1.4.0 calibration still reads as it was stored.
    contract_version: Literal["macrofield-calibration@1.3.0", "macrofield-calibration@1.4.0",
                              "macrofield-calibration@1.5.0"] = "macrofield-calibration@1.3.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""

    # -- assembly ------------------------------------------------------------
    #: Multiplicative uplift on BIS credit/GDP, the saturation axis and therefore K_I.
    credit_uplift: float = Field(gt=0.0)
    #: K_R/Y that the common capital normalisation maps the window maximum to.
    capital_target: float = Field(gt=0.0, lt=1.0)
    #: Above this saturation an economy is refused as an ingestion fault, not classified.
    refuse_above: float = Field(gt=0.0)
    #: IMF WEO panels carry forecasts; values after this year are not read.
    imf_last_actual_year: int = 2024

    # -- dynamics and fit ------------------------------------------------------
    closure: Literal["as_written", "identity_closed"] = "as_written"
    #: TB-27 (1.5.0). ``None`` (as written): r = 1 - K_R/Y, unbounded below, so once K_R passes Y
    #: the flow r K_I drains output and the path reaches Y = 0 in finite time. ``bounded``:
    #: r = max(0, 1 - K_R/Y), identical wherever K_R <= Y; past it financial capital stops
    #: flowing into real capital instead of real capital being liquidated at an unbounded rate.
    #: The right-hand side then grows at most linearly in the state, so no finite-time
    #: singularity exists (dynamics.py). Used by the fit and the projection alike. Omitted from
    #: the serialisation while unset.
    investment_share: Optional[Literal["as_written", "bounded"]] = None
    p_b_source: Literal["population_growth", "flow_ratio"] = "population_growth"
    derivative: Derivative = Derivative()
    integrator: Integrator = Integrator()
    search: Search = Search()
    residual_tolerance: float = Field(default=1e-6, gt=0.0)
    #: Meaningful ranges for p_p, p_b, alpha and p_s. The fit's scale bounds derive from them.
    parameter_ranges: dict[Literal["p_p", "p_b", "alpha", "p_s"], Bounds]
    stimulus_scale: Bounds
    initial_state_tolerance: float = Field(gt=0.0, lt=1.0)
    weak_identification_ratio: float = Field(gt=0.0)
    #: Departure of an identity correction from one above which a note is raised.
    identity_correction_note: float = Field(gt=0.0)

    # -- classification and projection ---------------------------------------
    phases: PhaseThresholds = PhaseThresholds()
    projection: ProjectionDefaults = ProjectionDefaults()

    economies: tuple[EconomySpec, ...] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "Calibration":
        codes = [e.code for e in self.economies]
        if len(set(codes)) != len(codes):
            raise ValueError("economy codes must be unique")
        missing = {"p_p", "p_b", "alpha", "p_s"} - set(self.parameter_ranges)
        if missing:
            raise ValueError(f"parameter_ranges lacks {sorted(missing)}")
        if self.derivative.polynomial_order >= self.derivative.window_years:
            raise ValueError("the derivative window must exceed the polynomial order")
        return self

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), ("investment_share",))

    @property
    def share_form(self) -> Literal["as_written", "bounded"]:
        """The investment share the equations use (``as_written`` while unset)."""
        return self.investment_share or "as_written"

    def economy(self, code: str) -> EconomySpec:
        for e in self.economies:
            if e.code == code:
                return e
        raise KeyError(code)


# ---------------------------------------------------------------------------
# Run request and status
# ---------------------------------------------------------------------------

class MacroRunRequest(_Frozen):
    """Body of ``POST /run``."""

    snapshot_id: str = Field(min_length=1)
    #: Economy codes. ``None`` runs every economy the calibration registers.
    economies: Optional[tuple[str, ...]] = None
    #: ``None`` uses the active calibration from ``config.yaml``.
    calibration_version: Optional[str] = None
    #: R-005: the Phase IV resolution the main projection path follows. ``None`` takes the
    #: calibration's default; ignored by a calibration without a crisis section. In the
    #: idempotency key.
    resolution_policy: Optional[ResolutionPolicyId] = None

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), ("resolution_policy",))

    @field_validator("economies")
    @classmethod
    def _economies(cls, v: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
        if v is None:
            return v
        if not v:
            raise ValueError("economies, when given, must name at least one economy")
        if len(set(v)) != len(v):
            raise ValueError("economies must not repeat")
        return v


RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


# ---------------------------------------------------------------------------
# Output: MacroState
# ---------------------------------------------------------------------------

class StatePaths(_Frozen):
    """Y, K_R and K_I in current US dollars, capital on the normalised scale."""

    Y: Path
    K_R: Path
    K_I: Path

    @field_validator("Y", "K_R", "K_I")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)


class InputPaths(_Frozen):
    """The assembled inputs, before and after the documented adjustments."""

    #: BIS total credit to the non-financial sector over GDP, as published (ratio, not %).
    credit_ratio_published: Path
    #: The saturation axis: the published ratio times the credit uplift.
    saturation: Path
    #: PWT cn/cgdpo, published through its last year and extended in ratio space after.
    real_capital_ratio: Path
    #: True where the real-capital ratio is a perpetual-inventory extension, not published.
    real_capital_ratio_extended: tuple[bool, ...]
    p_s: Path
    stimulus_share: Path
    S: Path
    population_growth: Path
    #: Loans to domestic non-banks over the bank balance sheet (Genreith's commercial-bank
    #: share); all null where the saturation source is BIS credit.
    commercial_bank_share: Path = ()

    @field_validator("credit_ratio_published", "saturation", "real_capital_ratio", "p_s",
                     "stimulus_share", "S", "population_growth", "commercial_bank_share")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)


class IdentityPaths(_Frozen):
    """The section 0.2 identities evaluated on the observed path."""

    r: Path
    alpha: Path
    p_p: Path
    p_b: Path
    #: (Y_dot + K_R_dot) / K_I_dot, the p_b formula as written. Reported, not used by default.
    p_b_flow_ratio: Path

    @field_validator("r", "alpha", "p_p", "p_b", "p_b_flow_ratio")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)


class CapitalNormalisation(_Frozen):
    scale: float
    target: float
    observed_max_ratio: float
    observed_max_year: int


class FitReport(_Frozen):
    free_parameters: dict[str, float]
    standard_errors: dict[str, Number]
    identifiability: dict[str, str]
    weakly_identified: tuple[str, ...]
    converged: bool
    optimiser_message: str
    evaluations: int
    #: ``reporting`` when the fitted path integrates at reporting tolerance, ``search`` when only
    #: at the looser search tolerance (the path runs close to the finite-time singularity),
    #: ``none`` when it does not integrate over the window at all.
    integration_accuracy: Literal["reporting", "search", "none"]
    #: Root mean square relative residual per state series; ``None`` when not integrable.
    residuals: dict[str, Number]
    two_body_worst_relative: Number
    identity_diagnostics: dict[str, Number]
    identity_corrections: dict[str, float]


class Diagnostics(_Frozen):
    """Algebraic functions of the observed state. Available whether or not the fit integrates."""

    capital_saturation: Path          # (K_R + K_I) / Y on the normalised scale
    real_to_financial: Path           # K_R / K_I, scale invariant
    unsecured_ratio: Path             # (K_R + K_I - Y) / Y on the normalised scale
    unsecured_accelerating: tuple[bool, ...]
    phase: tuple[Phase, ...]
    phase_unlatched: tuple[Phase, ...]
    in_balanced_band: tuple[bool, ...]
    economy_type: tuple[Literal["production", "financial"], ...]
    phase_rules: tuple[tuple[str, ...], ...]

    @field_validator("capital_saturation", "real_to_financial", "unsecured_ratio")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)


class PhaseHistory(_Frozen):
    """The saturation axis and phase over every year with data, before and inside the window.

    With ``latch_from_full_history`` the window's phases are the tail of this sequence. K_R/K_I
    is scale invariant, so it is published unnormalised here.
    """

    years: tuple[int, ...]
    saturation: Path
    real_to_financial: Path
    phase: tuple[Phase, ...]
    in_window: tuple[bool, ...]
    commercial_bank_share: Path = ()

    @field_validator("saturation", "real_to_financial", "commercial_bank_share")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)


ControlMode = Literal["constant", "step", "ramp", "pulse"]


class ControlSpec(_Frozen):
    """A forward lever: a multiplier over the projected years.

    ``constant`` holds ``base``; ``step`` moves to ``target`` from ``start_year``; ``ramp`` moves
    linearly to ``target`` between ``start_year`` and ``end_year`` and holds; ``pulse`` is at
    ``target`` from ``start_year`` to ``end_year`` and at ``base`` outside.
    """

    mode: ControlMode = "constant"
    base: float = 1.0
    target: Optional[float] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    @model_validator(mode="after")
    def _complete(self) -> "ControlSpec":
        if self.mode == "constant":
            return self
        if self.target is None or self.start_year is None:
            raise ValueError(f"a {self.mode} lever needs target and start_year")
        if self.mode in ("ramp", "pulse"):
            if self.end_year is None or self.end_year < self.start_year:
                raise ValueError(f"a {self.mode} lever needs end_year at or after start_year")
        return self

    @property
    def is_identity(self) -> bool:
        return self.mode == "constant" and self.base == 1.0


class ProjectionRequest(_Frozen):
    """Body of ``POST /project``: a what-if on a stored artefact. Omitted fields take the
    calibration's projection defaults."""

    artefact_id: str
    economy: str
    horizon: Optional[int] = Field(default=None, ge=1, le=100)
    parameter_mode: Optional[ParameterMode] = None
    stimulus: ControlSpec = ControlSpec()
    savings: ControlSpec = ControlSpec()
    deflation_capital_decline: Optional[float] = Field(default=None, gt=0.0, lt=1.0)
    inflation_output_growth: Optional[float] = Field(default=None, gt=0.0)
    #: R-005: the policy the main path follows at the turn (calibration default if omitted).
    resolution_policy: Optional[ResolutionPolicyId] = None
    #: R-005: project to this calendar year (overrides ``horizon``).
    horizon_until: Optional[int] = Field(default=None, ge=2000, le=2200)


class ProjectedTransition(_Frozen):
    year: int
    from_phase: Phase
    to_phase: Phase
    saturation: float
    real_to_financial: float
    extrapolated: bool


class Turn(_Frozen):
    """R-005: where a projected path turns under the soft saturation ceiling."""

    policy: ResolutionPolicyId
    year: int
    level: float
    #: The policy's turn level inside the ceiling band.
    turn_level: float
    #: True where the turn falls in years the model did not integrate (log-linear tail).
    in_extrapolation: bool
    crisis_months: int
    crisis_end_year: int
    crisis_end_level: float
    reset_years: int
    reset_end_year: int
    reset_target: float
    #: ``foundation`` or the reason of the per-economy override.
    reset_target_source: str


class ResolutionScenario(_Frozen):
    """One Phase IV resolution. From calibration 1.4.0 one per policy of ``Scenario_SAA.m``,
    from its own turn to the horizon; before, the two stylised rates (1.3.0)."""

    name: Literal["debt_deflation", "hyperinflation", "depression", "stagflation", "deferral"]
    years: tuple[int, ...]
    capital_ratio: Path
    mechanism: str
    asset_implication: str
    # -- R-005, omitted while unset --------------------------------------------------
    label: Optional[str] = None
    saturation: Path = ()
    phase: tuple[Phase, ...] = ()
    segment: tuple[str, ...] = ()
    turn: Optional[Turn] = None
    corrects_through: Optional[str] = None
    target_mix: tuple[float, ...] = ()
    #: Monthly crisis paths as in ``Scenario_SAA.m`` (annual inflation rate per month,
    #: surviving share of claims, valuation factor) and the price level they imply.
    inflation: tuple[float, ...] = ()
    defaults: tuple[float, ...] = ()
    valuations: tuple[float, ...] = ()
    price_level: tuple[float, ...] = ()

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), (
            "label", "saturation", "phase", "segment", "turn", "corrects_through", "target_mix",
            "inflation", "defaults", "valuations", "price_level"))


#: Per projected year, which part of the path it is (R-005). ``model``: integrated;
#: ``extrapolated``: log-linear tail; ``crisis``: the acute crisis of the selected policy;
#: ``reset``: the decline to the reset target; ``post_reset``: the model re-integrated from the
#: reset state with early-phase parameters; ``post_reset_extrapolated``: its log-linear tail.
Segment = Literal["model", "extrapolated", "crisis", "reset", "post_reset",
                  "post_reset_extrapolated"]


class Projection(_Frozen):
    """The calibrated model run forward from the observed end state.

    Conditional and structural: where the economy goes if the last observed conditions persist,
    or as the levers set them. Direction is the strongest reading, dates the weakest. Years past
    ``integrated_years`` are a log-linear extrapolation, flagged, not a model consequence.
    """

    status: Literal["ok", "unavailable"]
    reason: Optional[str] = None
    from_year: Optional[int] = None
    years: tuple[int, ...] = ()
    Y: Path = ()
    K_R: Path = ()
    K_I: Path = ()
    saturation: Path = ()
    real_to_financial: Path = ()
    capital_saturation: Path = ()
    phase: tuple[Phase, ...] = ()
    extrapolated: tuple[bool, ...] = ()
    requested_horizon: int = 0
    integrated_years: int = 0
    #: ``False`` where the calibrated path does not reproduce the observed window: the projection
    #: then rests on fitted parameters the window itself does not confirm. Weak evidence.
    fit_reproduces_window: bool = True
    transitions: tuple[ProjectedTransition, ...] = ()
    scenarios: tuple[ResolutionScenario, ...] = ()
    #: In-sample share of years whose simulated direction matches the observed, per series.
    directional_accuracy: dict[str, Number] = {}
    settings: dict[str, object] = {}
    assumptions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    label: str = "illustrative, model-derived"
    # -- R-005 (calibration 1.4.0), omitted while unset ----------------------------------
    #: The policy the main path follows after the turn.
    resolution_policy: Optional[ResolutionPolicyId] = None
    segment: tuple[Segment, ...] = ()
    #: Per year: "crisis and reset (<policy>)" after a turn, else null. Model-derived, and
    #: distinct from ``extrapolated``.
    segment_label: tuple[Optional[str], ...] = ()
    #: Years after ``display_until`` carry this flag: lower confidence, shown on request.
    lower_confidence: tuple[bool, ...] = ()
    display_until: Optional[int] = None
    turns: tuple[Turn, ...] = ()
    ceiling: Optional[SaturationCeiling] = None
    #: The saturation path the model gives before the ceiling (integrated, then extrapolated),
    #: up to the first turn; for inspection only.
    unbounded_saturation: Path = ()

    @field_validator("Y", "K_R", "K_I", "saturation", "real_to_financial", "capital_saturation",
                     "unbounded_saturation")
    @classmethod
    def _finite(cls, v: Path) -> Path:
        return _finite_or_none(v)

    @model_validator(mode="after")
    def _shape(self) -> "Projection":
        if self.status == "unavailable":
            if not self.reason:
                raise ValueError("an unavailable projection must say why")
            return self
        n = len(self.years)
        for name in ("Y", "K_R", "K_I", "saturation", "real_to_financial",
                     "capital_saturation", "phase", "extrapolated"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"projection {name} is not aligned to years")
        for name in ("segment", "segment_label", "lower_confidence", "unbounded_saturation"):
            if getattr(self, name) and len(getattr(self, name)) != n:
                raise ValueError(f"projection {name} is not aligned to years")
        return self

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), (
            "resolution_policy", "segment", "segment_label", "lower_confidence", "display_until",
            "turns", "ceiling", "unbounded_saturation"))


class CurrentState(_Frozen):
    year: int
    phase: Phase
    phase_label: str
    saturation: float
    saturation_pct: float
    in_balanced_band: bool
    distance_to_band_upper: float
    real_to_financial: float
    unsecured_ratio: float


class EconomyState(_Frozen):
    code: str
    name: str
    status: Literal["ok", "unavailable"]
    #: Why an economy is unavailable. ``None`` when ``status`` is ``ok``.
    reason: Optional[str] = None
    missing_inputs: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    #: Years inside the window dropped because a required value is missing. Never filled.
    dropped_years: tuple[int, ...] = ()
    inputs: Optional[InputPaths] = None
    observed: Optional[StatePaths] = None
    identities: Optional[IdentityPaths] = None
    capital_normalisation: Optional[CapitalNormalisation] = None
    fit: Optional[FitReport] = None
    simulated: Optional[StatePaths] = None
    diagnostics: Optional[Diagnostics] = None
    current: Optional[CurrentState] = None
    phase_history: Optional[PhaseHistory] = None
    projection: Optional[Projection] = None
    stimulus_proxy: Optional[StimulusProxy] = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> "EconomyState":
        if self.status == "unavailable":
            if not self.reason:
                raise ValueError("an unavailable economy must say why")
            return self
        if self.reason is not None:
            raise ValueError("an available economy carries no reason")
        n = len(self.years)
        if n == 0 or any(b <= a for a, b in zip(self.years, self.years[1:])):
            raise ValueError("years must be non-empty and strictly increasing")
        for label, part in (("inputs", self.inputs), ("observed", self.observed),
                            ("identities", self.identities), ("diagnostics", self.diagnostics)):
            if part is None:
                raise ValueError(f"an available economy needs {label}")
            for name, value in part:
                if isinstance(value, tuple) and len(value) != n:
                    raise ValueError(f"{label}.{name} is not aligned to years")
        if self.simulated is not None:
            for name, value in self.simulated:
                if len(value) != n:
                    raise ValueError(f"simulated.{name} is not aligned to years")
        if self.fit is None or self.current is None or self.capital_normalisation is None:
            raise ValueError("an available economy needs fit, current and capital_normalisation")
        return self


class EconomyCoverage(_Frozen):
    code: str
    status: Literal["ok", "unavailable"]
    first_year: Optional[int]
    last_year: Optional[int]
    years: int
    dropped_years: tuple[int, ...]
    extended_years: tuple[int, ...]


class CoverageReport(_Frozen):
    requested: tuple[str, ...]
    available: tuple[str, ...]
    unavailable: dict[str, str]
    economies: tuple[EconomyCoverage, ...]


class Provenance(_Frozen):
    snapshot_id: str
    as_of: str
    #: Raw source file path -> SHA-256, exactly the files the snapshot was built from.
    sources: dict[str, str]
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: R-005: the resolution policy the projections follow (null for a calibration without one).
    resolution_policy: Optional[ResolutionPolicyId] = None

    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        return _omit_unset(handler(self), ("resolution_policy",))


class MacroState(_Frozen):
    """The artefact of one run."""

    contract_version: Literal["macrofield-state@1.2.0"] = "macrofield-state@1.2.0"
    artefact_id: str
    economies: tuple[EconomyState, ...]
    coverage: CoverageReport
    provenance: Provenance
    notice: str = NOTICE

    def economy(self, code: str) -> EconomyState:
        for e in self.economies:
            if e.code == code:
                return e
        raise KeyError(code)


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: MacroRunRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[Provenance]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Data need (the specification that feeds the Data Feed engine)
# ---------------------------------------------------------------------------

class DataNeedRow(_Frozen):
    """One row in the T5 format (sim-tech task T5)."""

    proposed_series_id: str
    model: Literal["macrofield"] = "macrofield"
    index_block: str
    country_or_scope: str
    description: str
    native_frequency: Literal["A", "Q", "M", "D"]
    required_history_years: int = Field(ge=1)
    leading_concurrent_lagging: Literal["leading", "concurrent", "lagging"]
    scale_critical: bool
    candidate_source: str
    already_in_catalogue: bool
    status: Literal["in_snapshot", "missing"]


class DataNeed(_Frozen):
    contract_version: Literal["macrofield-data-need@1.0.0"] = "macrofield-data-need@1.0.0"
    rows: tuple[DataNeedRow, ...]

# ---------------------------------------------------------------------------
# Model card (GET /model): the model explained on its own data
# ---------------------------------------------------------------------------
#
# ``model-card@1.0.0`` is the same shape in every engine (each engine keeps its own copy, as
# engines share no code), so one cockpit page can show any of them: what comes in, in plain
# names; every calculation step with its formula, parameters and the numbers it produced; and
# what goes out. The engine computes every figure; the consumer only draws it.
#
# The card is a view, not a result: it is deliberately not in CONTRACT_VERSIONS, which feeds
# every artefact's idempotency key and id, so adding or changing it never changes a result.

MODEL_CARD_VERSION = "model-card@1.0.0"

ChartX = Union[int, float, str]


class ChartSeries(_Frozen):
    """One line or set of bars of a chart, aligned to the chart's ``x``. ``slot`` fixes the
    categorical colour (0 to 4), so one entity wears one colour in every chart; ``muted``
    draws a reference series in grey."""

    name: str
    y: tuple[Number, ...]
    kind: Literal["line", "bar", "markers"] = "line"
    dash: Literal["solid", "dash", "dot"] = "solid"
    slot: Optional[int] = Field(default=None, ge=0, le=4)
    muted: bool = False


class Chart(_Frozen):
    """A chart the engine has computed. ``xy``: series against ``x``. ``heatmap``: ``z`` rows
    are ``rows`` (top to bottom), columns are ``x``; with ``categories`` the cells are indices
    into it (a categorical heatmap, drawn with one colour per category)."""

    title: str
    kind: Literal["xy", "heatmap"] = "xy"
    x: tuple[ChartX, ...]
    x_label: str = ""
    y_label: str = ""
    series: tuple[ChartSeries, ...] = ()
    rows: tuple[str, ...] = ()
    z: tuple[tuple[Number, ...], ...] = ()
    categories: tuple[str, ...] = ()
    #: x from which the values are projected, not observed (drawn shaded); null if none.
    projected_from: Optional[ChartX] = None
    note: str = ""

    @model_validator(mode="after")
    def _aligned(self) -> "Chart":
        n = len(self.x)
        for s in self.series:
            if len(s.y) != n:
                raise ValueError(f"chart {self.title!r}: series {s.name!r} has {len(s.y)} values for {n} x")
        if self.kind == "heatmap":
            if len(self.z) != len(self.rows) or any(len(r) != n for r in self.z):
                raise ValueError(f"chart {self.title!r}: z must be rows by x")
        return self


class ModelInput(_Frozen):
    """One input as the engine receives it: plain name, unit, where it comes from, the data."""

    key: str
    name: str
    unit: str
    frequency: str
    source: str
    description: str
    x: tuple[ChartX, ...]
    y: tuple[Number, ...]


class Parameter(_Frozen):
    symbol: str
    name: str
    value: str


class ModelStep(_Frozen):
    """One calculation: what it does in words, the formula (LaTeX), its parameters and charts."""

    key: str
    title: str
    text: str
    formulas: tuple[str, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    charts: tuple[Chart, ...] = ()


class ModelOutputField(_Frozen):
    key: str
    name: str
    unit: str
    description: str


class EconomyOption(_Frozen):
    code: str
    name: str


class ModelCard(_Frozen):
    """``GET /model``: the model for one economy, on the data in the store today."""

    contract_version: Literal["model-card@1.0.0"] = "model-card@1.0.0"
    engine: str
    title: str
    summary: str
    engine_version: str
    calibration_version: str
    data: str
    economy: EconomyOption
    economies: tuple[EconomyOption, ...]
    inputs: tuple[ModelInput, ...]
    steps: tuple[ModelStep, ...]
    outputs: tuple[ModelOutputField, ...]
    output_charts: tuple[Chart, ...] = ()
    notes: tuple[str, ...] = ()
    notice: str = NOTICE
