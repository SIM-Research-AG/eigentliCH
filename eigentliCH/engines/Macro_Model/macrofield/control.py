"""Control paths and provenance, the two foundations the control board rests on.

Phase 0 of docs/BATTLE_PLAN.md.

**Why a control is not a number.** The board has to express things like "a stimulus programme of three per
cent of output starting in 2027 and running four years". A scalar multiplier cannot say that, and
`/api/project` previously took `stimulus_multiplier` as a scalar, so every lever was implicitly flat
forever. `ControlPath` is the smallest type that expresses a shape over time without becoming a
free-form editor: four modes, four numbers, and a resolved array.

**Why provenance is not optional.** Phase 2 of the plan asks the programme to carry on where it currently
refuses: to extrapolate past a failed integration, and to assume a capital-cycle anchor for an economy that
has not reached one. Both invent values. That is a reasonable thing for a control board to do, and it is
only reasonable if the invented values are labelled, because the whole programme rests on a reader being
able to tell a measurement from a computation from an assumption. `Provenance` is that label, and it is
ordered, so a series of mixed provenance takes the weakest of its parts.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np


class ControlError(ValueError):
    """Raised when a control path is not usable."""


class Provenance(enum.Enum):
    """How much a number is worth, weakest last.

    The order is the point. `weakest_of` takes the lowest-confidence member of a set, so a series that is
    observed for fifty years and extrapolated for two is an extrapolated series, not an observed one.

    - `OBSERVED`: it came from a source with a vintage.
    - `DERIVED`: computed from observed values by a documented definition. A ratio, a growth rate.
    - `INTEGRATED`: produced by running the model forward from an observed state.
    - `EXTRAPOLATED`: continued past where the model could integrate, by a stated rule.
    - `ASSUMED`: supplied because the data could not say. The capital-cycle anchor of an economy that has
      not crossed the anchor ratio is the live case.
    """

    OBSERVED = "observed"
    DERIVED = "derived"
    INTEGRATED = "integrated"
    EXTRAPOLATED = "extrapolated"
    ASSUMED = "assumed"

    @property
    def rank(self) -> int:
        return _PROVENANCE_ORDER.index(self)

    @property
    def is_invented(self) -> bool:
        """Whether the value was produced without data supporting that particular value."""
        return self in (Provenance.EXTRAPOLATED, Provenance.ASSUMED)

    @classmethod
    def weakest_of(cls, values: Sequence["Provenance"]) -> "Provenance":
        """The weakest provenance in a set, which is what a mixed series carries."""
        if not values:
            raise ControlError("no provenance values were given")
        return max(values, key=lambda p: p.rank)


_PROVENANCE_ORDER = [
    Provenance.OBSERVED,
    Provenance.DERIVED,
    Provenance.INTEGRATED,
    Provenance.EXTRAPOLATED,
    Provenance.ASSUMED,
]


@dataclass(frozen=True)
class Segment:
    """One period's provenance, for a series assembled from parts.

    Attributes:
        start: First index the provenance applies to.
        end: Last index it applies to, inclusive.
        provenance: What the values in the range are.
        detail: Why, in a sentence a reader can act on.
    """

    start: int
    end: int
    provenance: Provenance
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "provenance": self.provenance.value,
            "invented": self.provenance.is_invented,
            "detail": self.detail,
        }


@dataclass
class Traced:
    """A series with its provenance broken down by range.

    A chart can then draw the observed part solid and anything invented dashed, without the caller having
    to remember where the join was.
    """

    values: np.ndarray
    segments: list[Segment] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=float)

    @property
    def provenance(self) -> Provenance:
        """The provenance of the series as a whole, which is the weakest of its parts."""
        if not self.segments:
            raise ControlError("a traced series carries no segments")
        return Provenance.weakest_of([s.provenance for s in self.segments])

    def first_invented_index(self) -> int | None:
        """Where the invented part starts, for splitting a chart trace."""
        invented = [s.start for s in self.segments if s.provenance.is_invented]
        return min(invented) if invented else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "values": [None if not np.isfinite(v) else float(v) for v in self.values],
            "provenance": self.provenance.value,
            "first_invented_index": self.first_invented_index(),
            "segments": [s.as_dict() for s in self.segments],
        }


class ControlMode(enum.Enum):
    """The shapes a control can take over time.

    Four, deliberately. Each is describable in a sentence and reproducible from four numbers, which keeps a
    board state a shareable URL rather than a document.
    """

    CONSTANT = "constant"
    STEP = "step"
    RAMP = "ramp"
    PULSE = "pulse"


@dataclass(frozen=True)
class ControlPath:
    """One lever, over time.

    Attributes:
        mode: The shape.
        base: The value before the change, and after it for a pulse.
        target: The value the change reaches. Ignored by `constant`.
        start_period: When the change begins. Required by every mode but `constant`.
        end_period: When a `ramp` finishes rising, or a `pulse` returns to base. Required by both.
        label: What the lever is, for the chart and the manifest.

    A `step` holds `base` before `start_period` and `target` from it on. A `ramp` interpolates linearly
    between them and then holds `target`. A `pulse` rises to `target` at `start_period` and returns to
    `base` after `end_period`, which is the shape a time-limited stimulus programme takes.
    """

    mode: ControlMode = ControlMode.CONSTANT
    base: float = 1.0
    target: float | None = None
    start_period: int | None = None
    end_period: int | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.mode is ControlMode.CONSTANT:
            return

        if self.target is None:
            raise ControlError(
                f"mode {self.mode.value!r} needs a target. Only 'constant' may omit it."
            )
        if self.start_period is None:
            raise ControlError(f"mode {self.mode.value!r} needs a start_period")
        if self.mode in (ControlMode.RAMP, ControlMode.PULSE):
            if self.end_period is None:
                raise ControlError(f"mode {self.mode.value!r} needs an end_period")
            if self.end_period < self.start_period:
                raise ControlError(
                    f"end_period {self.end_period} is before start_period {self.start_period}"
                )

    @property
    def is_identity(self) -> bool:
        """Whether the path leaves its quantity untouched, so a manifest can say 'nothing applied'."""
        return self.mode is ControlMode.CONSTANT and self.base == 1.0

    def to_array(self, periods: Sequence[Any]) -> np.ndarray:
        """Resolve the path over a set of periods.

        Args:
            periods: The period labels, which must be numeric so a start period can be located.

        Returns:
            One value per period.

        Raises:
            ControlError: If the periods are not numeric, since a shape over time needs an ordering.
        """
        try:
            years = np.asarray(list(periods), dtype=float)
        except (TypeError, ValueError) as error:
            raise ControlError(
                f"a control path needs numeric periods to resolve against, got {periods!r}"
            ) from error

        if years.size == 0:
            return np.zeros(0, dtype=float)

        out = np.full(years.shape, float(self.base), dtype=float)
        if self.mode is ControlMode.CONSTANT:
            return out

        start = float(self.start_period)
        target = float(self.target)

        if self.mode is ControlMode.STEP:
            out[years >= start] = target
            return out

        end = float(self.end_period)

        if self.mode is ControlMode.RAMP:
            if end == start:
                out[years >= start] = target
                return out
            rising = (years >= start) & (years <= end)
            out[rising] = self.base + (target - self.base) * (years[rising] - start) / (end - start)
            out[years > end] = target
            return out

        # PULSE: at target between start and end inclusive, at base outside.
        out[(years >= start) & (years <= end)] = target
        return out

    def describe(self) -> str:
        """A sentence for the manifest and the chart footer."""
        name = self.label or "the control"
        if self.mode is ControlMode.CONSTANT:
            return f"{name} held at {self.base:g} throughout"
        if self.mode is ControlMode.STEP:
            return f"{name} steps from {self.base:g} to {self.target:g} in {self.start_period}"
        if self.mode is ControlMode.RAMP:
            return (
                f"{name} ramps from {self.base:g} to {self.target:g} between "
                f"{self.start_period} and {self.end_period}, then holds"
            )
        return (
            f"{name} pulses to {self.target:g} from {self.start_period} to {self.end_period}, "
            f"returning to {self.base:g}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "base": self.base,
            "target": self.target,
            "start_period": self.start_period,
            "end_period": self.end_period,
            "label": self.label,
            "identity": self.is_identity,
            "description": self.describe(),
        }

    @classmethod
    def constant(cls, value: float = 1.0, label: str = "") -> "ControlPath":
        return cls(mode=ControlMode.CONSTANT, base=value, label=label)

    @classmethod
    def from_spec(cls, spec: Any, label: str = "") -> "ControlPath":
        """Build from a scalar, a string, or a mapping.

        A bare number is a constant, which is what keeps the existing scalar API working unchanged. A
        string is the compact form the board puts in a URL:

            "constant:1.0"
            "step:1.0>1.5@2027"
            "ramp:1.0>1.5@2027-2031"
            "pulse:1.0>1.03@2027-2030"
        """
        if spec is None:
            return cls.constant(1.0, label)
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            return cls.constant(float(spec), label)
        if isinstance(spec, ControlPath):
            return spec
        if isinstance(spec, Mapping):
            mode = ControlMode(str(spec.get("mode", "constant")))
            return cls(
                mode=mode,
                base=float(spec.get("base", 1.0)),
                target=None if spec.get("target") is None else float(spec["target"]),
                start_period=None if spec.get("start_period") is None else int(spec["start_period"]),
                end_period=None if spec.get("end_period") is None else int(spec["end_period"]),
                label=str(spec.get("label", label)),
            )
        if isinstance(spec, str):
            return cls._from_string(spec, label)
        raise ControlError(f"cannot read a control path from {spec!r}")

    @classmethod
    def _from_string(cls, spec: str, label: str) -> "ControlPath":
        text = spec.strip()
        if ":" not in text:
            try:
                return cls.constant(float(text), label)
            except ValueError as error:
                raise ControlError(
                    f"{spec!r} is not a control path. Expected a number or "
                    f"'mode:base>target@start[-end]'."
                ) from error

        mode_text, remainder = text.split(":", 1)
        try:
            mode = ControlMode(mode_text.strip())
        except ValueError as error:
            modes = ", ".join(m.value for m in ControlMode)
            raise ControlError(f"unknown control mode {mode_text!r}. Expected one of {modes}.") from error

        if mode is ControlMode.CONSTANT:
            return cls.constant(float(remainder), label)

        if "@" not in remainder or ">" not in remainder:
            raise ControlError(
                f"{spec!r} is incomplete. A {mode.value} needs 'base>target@start' and a ramp or pulse "
                f"also needs an end, as 'base>target@start-end'."
            )
        values, window = remainder.split("@", 1)
        base_text, target_text = values.split(">", 1)
        if "-" in window:
            start_text, end_text = window.split("-", 1)
        else:
            start_text, end_text = window, None

        return cls(
            mode=mode,
            base=float(base_text),
            target=float(target_text),
            start_period=int(start_text),
            end_period=None if end_text is None else int(end_text),
            label=label,
        )
