"""The ``ReturnSet`` contract, and the boundary checks that make it worth having.

Every model here is ``frozen`` with ``extra='forbid'``, per manual section 4: contracts are
immutable value objects, and a field nobody declared is a field nobody validated.

**What this contract refuses to carry is the point of it.** Not a mean, not a variance,
not a covariance matrix. A moment is a summary over states, and summarising over states
destroys exactly the information everything downstream runs on -- fold crisis behaviour
into a variance and no engine can price crisis behaviour specifically. The refusal is
*enforced*, not documented: :func:`reject_moments` walks a payload and raises if it finds
a banned key, and the API calls it before anything leaves the process.

Whoever owns this engine has to be able to defend that against somebody who wants a
covariance matrix. The defence is that the 25-state profile contains strictly more
information than any moment computed from it, and the consumer that genuinely needs a
moment can compute one -- against a regime distribution it chooses, at the point of use,
where the choice is visible.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

STATE_COUNT = 25

Role = Literal["gain", "income", "stabilisation", "protection"]

MethodLabel = Literal[
    "data-driven",
    "data-driven-trimmed",
    "interpolated",
    "extrapolated",
    "borrowed",
    # D2's label, also used by the 12 month forward measurement for a phase it had to
    # fill. Admitted for the opt-in sets first (FMRE-09); since 29.09.2026 the default
    # emits it too, for a phase the forward measurement could not measure (FMRE-22).
    "shape-scaled",
    # The default estimator since 29.09.2026 (FMRE-22): the 12 month forward measurement
    # after a light smoothing across neighbouring states. Additive; rs@1.0.0 stays.
    "forward-12m-smoothed",
    "seed",
]

#: Keys that must never appear anywhere in an emitted payload. Checked recursively at the
#: boundary. ``std`` and ``variance`` are included even though the calibration computes a
#: per-phase spread internally: it is a diagnostic, and it does not cross the wire.
BANNED_KEYS: frozenset[str] = frozenset(
    {
        "mean", "mu", "expected_return", "e_r",
        "variance", "var", "std", "stdev", "standard_deviation", "sigma", "vol", "volatility",
        "covariance", "cov", "covariance_matrix", "correlation", "corr",
        "sharpe", "skew", "kurtosis", "moments",
    }
)


class ContractError(ValueError):
    """Raised when a payload fails a boundary check."""


def reject_moments(payload: Any, *, path: str = "$") -> None:
    """Walk a payload and raise if any banned key appears at any depth.

    Manual section 11.7 test 4: a payload carrying a mean or a covariance is refused. This
    is the implementation of that test, and it runs in production rather than only in the
    suite -- a boundary check that only exists in a test is a convention, not a boundary.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in BANNED_KEYS:
                raise ContractError(
                    f"{path}.{key} is a moment. A ReturnSet carries per-state profiles and "
                    f"nothing summarised over states; see contracts/return_set.py."
                )
            reject_moments(value, path=f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            reject_moments(value, path=f"{path}[{index}]")


class StateValue(BaseModel):
    """One state of one profile: the number, how it was produced, and how well observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: int = Field(ge=1, le=STATE_COUNT)
    value: float
    method: MethodLabel
    n_obs: int = Field(ge=0)

    @model_validator(mode="after")
    def _fills_carry_no_observations(self) -> "StateValue":
        """A filled value must report ``n_obs = 0``.

        Manual section 11.2 is explicit about this, and the reason is that a reader should
        be able to tell a measurement from a fill by looking at either field, not by
        knowing to cross-check both.
        """
        filled = self.method in ("interpolated", "extrapolated", "borrowed", "seed")
        if filled and self.n_obs != 0:
            raise ValueError(
                f"state {self.state} is {self.method} but claims n_obs={self.n_obs}; "
                f"a filled value carries no observations"
            )
        if not filled and self.n_obs == 0:
            raise ValueError(
                f"state {self.state} claims to be {self.method} with no observations"
            )
        return self


class Profile(BaseModel):
    """A complete 25-state profile for one role or one instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    kind: Literal["role", "instrument", "block"]
    role: Role | None = None
    unit: Literal["annualised_log_return"] = "annualised_log_return"
    #: The weakest method present. A single seeded state makes the whole profile seeded.
    coverage: MethodLabel
    states: tuple[StateValue, ...]
    #: Set only where the cascade borrowed, naming what it borrowed from.
    borrowed_from: str | None = None
    match_score: float | None = None

    @field_validator("states")
    @classmethod
    def _complete_and_ordered(cls, value: tuple[StateValue, ...]) -> tuple[StateValue, ...]:
        if len(value) != STATE_COUNT:
            raise ValueError(f"a profile has {len(value)} states, expected {STATE_COUNT}")
        if [s.state for s in value] != list(range(1, STATE_COUNT + 1)):
            raise ValueError("profile states must run 1..25 in order, with no gaps")
        return value


DeflatorLabel = Literal["measured", "extrapolated", "fallback", "not_computable"]


class DeflatorCurve(BaseModel):
    """One currency's per-state log inflation, as a real set subtracted it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: Literal["CHF", "EUR", "USD"]
    index: str
    source: str
    #: ``ln(1 + inflation)`` per state, 25 values: ``real = nominal - log_inflation``.
    log_inflation: tuple[float, ...]
    labels: tuple[DeflatorLabel, ...]
    #: What each part of the set was deflated with: ``instruments`` and/or ``roles``.
    applied_to: tuple[str, ...]


class Deflator(BaseModel):
    """How a real ReturnSet was deflated (nominal and real view, 29 September 2026).

    Additive and optional: only a ``basis=real`` set carries it, so the nominal default
    serialises byte for byte as before and the contract stays ``rs@1.0.0``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The currency the real figures are in; null when each instrument is deflated in its
    #: series' own (source) currency.
    currency: Literal["CHF", "EUR", "USD"] | None
    index: str
    method: str
    #: Per state, the weakest ceiling label over every curve applied to the instruments.
    labels: tuple[DeflatorLabel, ...]
    #: Decision 5: ``{from, to, states, reason}`` when the asked currency's inflation left
    #: the band and the set is real in a hard currency instead; null otherwise.
    hard_currency_fallback: dict[str, Any] | None = None
    #: The scenario Regime whose policy inflation was applied (decision 2); null for the
    #: historical per-state deflator.
    scenario: str | None = None
    curves: tuple[DeflatorCurve, ...] = ()


class PassThroughInstrument(BaseModel):
    """The inflation pass-through one instrument was carried to the scenario with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    #: The house type (``engines/fund_map/pass_through.py::HOUSE_TABLE``).
    type: str
    beta: float
    #: ``house`` or ``override`` (the CIO's, ``PUT /v1/inflation-beta/{id}``).
    source: Literal["house", "override"]
    #: Years, for a nominal bond (or where the CIO set one); null otherwise.
    duration: float | None = None
    duration_source: Literal["house", "override"] | None = None
    #: The override version in force, when there is one.
    override_version: int | None = None
    #: The currency whose historical per-state inflation gives the historical real return.
    deflator_currency: Literal["CHF", "EUR", "USD"]


class PassThroughBlock(BaseModel):
    """One block of a role's blended pass-through (FMRE-40)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    block: str
    #: The block's share of the role (normalised).
    weight: float
    #: The block's house type (``pass_through.BLOCK_TYPES``).
    type: str
    beta: float
    duration: float | None = None


class PassThroughRole(BaseModel):
    """The blended pass-through one role profile was carried to the scenario with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    #: ``sum(weight * beta)`` over the role's blocks.
    beta: float
    #: ``sum(weight * duration)`` over its nominal bond blocks; null when it has none.
    duration: float | None = None
    #: A role profile is the long annual record in USD: its historical real return is
    #: measured with the historical USD inflation.
    deflator_currency: Literal["CHF", "EUR", "USD"] = "USD"
    composition: tuple[PassThroughBlock, ...] = ()


class InflationPassThrough(BaseModel):
    """How a scenario set's instruments were carried to the scenario's inflation (FMRE-33).

    Additive and optional: only a set stamped against a scenario Regime carries it, so every
    other set serialises byte for byte as before and the contract stays ``rs@1.0.0``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    calibration_version: str
    calibration_id: str
    source: str
    scenario: str
    policy: str | None = None
    #: The scenario's inflation, simple annual rate (aggregation ``inflation_final_12m``).
    inflation_final_12m: float
    #: ``ipt@1.0.0`` capped a bond's loss at 99 % of its price (0.01); null since
    #: ``ipt@1.1.0``, whose log-form duration loss needs no cap (FMRE-38).
    price_floor: float | None = None
    formula: str
    #: What was carried: ``instruments`` and, in a ReturnSet since ``ipt@1.1.0``, ``roles``
    #: (FMRE-40). Block profiles carry no pass-through.
    applied_to: tuple[str, ...] = ("instruments",)
    instruments: tuple[PassThroughInstrument, ...] = ()
    #: Per role, the blended beta and its composition (FMRE-40).
    roles: tuple[PassThroughRole, ...] = ()


class Provenance(BaseModel):
    """Where a ReturnSet came from, in enough detail to reproduce it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calibration_id: str
    state_map_id: str
    #: The Regime (issued by aggregation) this set is stamped against, confirmed with
    #: aggregation before stamping; null when the request named none. A ReturnSet whose
    #: regime id differs from the Regime it is optimised against is rejected downstream
    #: rather than reconciled.
    regime_id: str | None = None
    universe_version: str
    calibration_window: str
    signal_window: str
    estimator: str
    source_sha256: dict[str, str]
    notes: tuple[str, ...] = ()
    #: The currency the instrument profiles were measured in when the request asked for
    #: one (``currency=`` on ``/v1/return-set``, D-01): converted monthly before
    #: estimation. Null on the unconverted default, where each series is in its source
    #: currency. The role profiles are never converted. Added 29 September 2026 for pcp
    #: v1.1.0, optional and additive, so the contract stays ``rs@1.0.0``; the provenance
    #: note on an opt-in set still names the currency as well.
    currency: Literal["CHF", "EUR", "USD"] | None = None
    #: ``real`` on a ``basis=real`` set (29 September 2026); the fields below are **left out
    #: of the JSON** when absent (not null), so a nominal set serialises byte for byte as
    #: before. Everything is stored nominal; real is derived at the point of use.
    basis: Literal["nominal", "real"] | None = None
    deflator: Deflator | None = None
    #: Under a scenario Regime only (FMRE-33): the inflation pass-through calibration and,
    #: per instrument, the beta used and its source. Left out of the JSON when absent.
    inflation_pass_through: InflationPassThrough | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_basis(self, handler):
        data = handler(self)
        if isinstance(data, dict):
            for name in ("basis", "deflator", "inflation_pass_through"):
                if data.get(name) is None:
                    data.pop(name, None)
        return data


class ReturnSet(BaseModel):
    """The artefact this engine publishes. Shared layer, no user data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    return_set_id: str
    contract_version: Literal["rs@1.0.0"] = "rs@1.0.0"
    engine_version: str
    as_of: str
    state_grid: Literal[25] = 25
    #: The stored calibration artefact: four role profiles.
    role_profiles: tuple[Profile, ...]
    #: Per-instrument profiles, estimated through the cascade.
    instrument_profiles: tuple[Profile, ...] = ()
    #: The eight long-record block profiles. Diagnostic only -- they are what the section
    #: 11.3 shape assertions run against -- and excluded from the published set by default.
    block_profiles: tuple[Profile, ...] = ()
    provenance: Provenance
    run_id: str

    @field_validator("role_profiles")
    @classmethod
    def _four_roles(cls, value: tuple[Profile, ...]) -> tuple[Profile, ...]:
        roles = sorted(p.key for p in value)
        expected = sorted(("gain", "income", "stabilisation", "protection"))
        if roles != expected:
            raise ValueError(f"expected the four roles {expected}, got {roles}")
        return value

    def checked_dump(self) -> dict[str, Any]:
        """Serialise, then refuse the result if it carries a moment."""
        payload = self.model_dump(mode="json")
        reject_moments(payload)
        return payload
