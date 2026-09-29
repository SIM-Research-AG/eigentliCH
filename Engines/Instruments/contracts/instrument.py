"""The instrument register contract.

The universe is **a versioned input, not code**. Manual section 11.4 says so directly --
"the register grows by data change" -- and it matters more than it looks: the Portfolio
Optimiser's objective has a floor that scales with the size of the universe, so changing
the count changes measured leverage. Adding an instrument must therefore be an auditable
data event with a timestamp, not a commit.

These models are the payloads the API accepts. They are deliberately thin: an instrument
is a name, a role, and enough classification to find it a peer when its own history is too
short to estimate from.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["gain", "income", "stabilisation", "protection"]
CapitalType = Literal["Financial", "Real", "Human", "Social"]

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

#: Any ``Growth`` label maps to ``Gain`` at the boundary -- manual section 2's vocabulary
#: table. Accepting both and normalising here means a caller using the older word does not
#: silently create a fifth role.
ROLE_ALIASES = {"growth": "gain", "stabilization": "stabilisation", "protect": "protection"}


class InstrumentIn(BaseModel):
    """Register a new instrument, or update an existing one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    role: Role
    asset_class: str = Field(min_length=1, max_length=80)
    ticker: str | None = Field(default=None, max_length=80)
    region_scope: str = "Global"
    region_geo: str | None = None
    capital_type: CapitalType = "Financial"
    currency: str = Field(default="CHF", pattern=r"^[A-Z]{3}$")
    liquidity: str | None = None
    note: str = ""
    #: Economies the instrument is exposed to, datafeed country codes; [] = no single economy.
    countries: tuple[str, ...] = ()

    @field_validator("countries")
    @classmethod
    def _country_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            if not re.fullmatch(r"[A-Z]{2}", code):
                raise ValueError(f"{code!r} is not a two-letter country code (ISO 3166, or EU)")
        if len(set(value)) != len(value):
            raise ValueError("a country is listed twice")
        return value

    @field_validator("role", mode="before")
    @classmethod
    def _normalise_role(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            return ROLE_ALIASES.get(lowered, lowered)
        return value


class ReturnPoint(BaseModel):
    """One month of one instrument's history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    period: str
    value: float

    @field_validator("period")
    @classmethod
    def _well_formed(cls, value: str) -> str:
        if not PERIOD_RE.match(value):
            raise ValueError(f"period {value!r} must be YYYY-MM")
        return value

    @field_validator("value")
    @classmethod
    def _not_a_total_loss(cls, value: float) -> float:
        # The estimator works in log space; -100 % is not representable and -200 % is not
        # a return. Refuse at the boundary rather than dropping the month silently later.
        if value <= -1.0:
            raise ValueError("a simple monthly return must be greater than -1.0")
        return value


class ReturnsIn(BaseModel):
    """A batch of monthly returns for one instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(default="manual", min_length=1, max_length=80)
    points: tuple[ReturnPoint, ...] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def _no_duplicate_periods(cls, value: tuple[ReturnPoint, ...]) -> tuple[ReturnPoint, ...]:
        periods = [p.period for p in value]
        if len(set(periods)) != len(periods):
            duplicates = sorted({p for p in periods if periods.count(p) > 1})
            raise ValueError(f"duplicate periods in one batch: {duplicates}")
        return value


class InstrumentOut(BaseModel):
    """An instrument as the register holds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    name: str
    role: Role
    asset_class: str
    ticker: str | None
    region_scope: str
    region_geo: str | None
    capital_type: str
    currency: str
    liquidity: str | None
    countries: tuple[str, ...] = ()
    active: bool
    created_at: str
    updated_at: str
    note: str
    months: int = 0
    first_period: str | None = None
    last_period: str | None = None
