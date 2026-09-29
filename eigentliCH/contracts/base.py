"""The contract spine: determinism, provenance, and the base every contract inherits.

Three guarantees live here so that no individual contract has to remember them.

**Determinism.** `idempotency_key = hash(inputs + model_version)` and a `trace_id` derived from it. Both
are pure functions of what went in, so replaying the same inputs reproduces the same identifiers. There is
no wall-clock and no unseeded value anywhere in either. This is what makes "same inputs and version
reproduce the same output, bit for bit" checkable rather than aspirational.

**Provenance.** Every value that a human might read carries where it came from. `Provenance` is the wrapper;
`Sourced` is a value with one attached.

**Canonical serialisation.** One serialiser, sorted keys and compact separators, so that an unchanged
contract produces byte-identical output and two vintages can be diffed meaningfully. The round-trip identity
the Phase 1 gate tests depends on this being the only way contracts are written.

**Why the timestamp is an input, not a reading.** A contract records `as_of`, the date the data describes,
and never the moment the object was built. Stamping build time would make every rebuild a different
artefact and the determinism guarantee untestable. Where a genuine event time is needed (a Decision Record
is signed at a moment), it is passed in by the caller and travels as data.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Vocabularies, fixed and ordered
# ---------------------------------------------------------------------------


class Scenario(str, Enum):
    """The five regimes of the book, ordered cautious to aggressive.

    Order is load-bearing: it matches the 25-state axis, index 0 crisis to 24 boom. Anything that presents
    them boom-first is doing so for display only.
    """

    CRISIS = "Crisis"
    CONTRACTION = "Contraction"
    STAGNATION = "Stagnation"
    EXPANSION = "Expansion"
    BOOM = "Boom"


class Role(str, Enum):
    """The four portfolio roles."""

    GAIN = "Gain"
    INCOME = "Income"
    STABILISATION = "Stabilisation"
    PROTECTION = "Protection"


class Phase(str, Enum):
    """The four capital-cycle phases.

    `Maturing` from the Fund Map register folds into `Build-up`, decided 2026-07-28. See
    architecture/DECISIONS.md M2, and do not confuse `Maturing` (position 2) with the legacy `Client`
    sheet's `Maturity` (position 4).
    """

    FOUNDATION = "Foundation"
    BUILD_UP = "Build-up"
    OPTIMISATION = "Optimisation"
    SATURATION = "Saturation"


class Reliability(str, Enum):
    """How far a value can be trusted. Mirrors the macro programme's ladder.

    `SYNTHETIC` must never reach a client-facing surface or a regulated decision. The ground rules forbid
    filling a gap with placeholder data, so this level exists to make a breach detectable rather than to
    permit one.
    """

    PUBLISHED = "published"
    DERIVED = "derived"
    INTERPOLATED = "interpolated"
    SYNTHETIC = "synthetic"


class BoundSource(str, Enum):
    """Where an allocation bound came from.

    The distinction a reader of a Recommendation needs: which limits are the household's own economics, and
    which are house policy. Those are different kinds of fact and must not be presented identically. See
    architecture/DESIGN_snapshot_to_mandate.md section 5.5.
    """

    #: Computed from the household's position and goal.
    DERIVED = "derived"
    #: Investment policy, owned by the CIO and the Investment Committee, set per client segment.
    POLICY = "policy"
    #: A Curator's deliberate departure from policy for one client, against a Decision Record.
    CURATOR_OVERRIDE = "curator_override"


class RegulatedStatus(str, Enum):
    """Whether a contract may cross the regulated wall unaided."""

    EDUCATION = "Education"
    CONDITIONAL = "Conditional"
    REGULATED = "Regulated"
    NOT_APPLICABLE = "n/a"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    """Where a value came from.

    `as_of` is the date the data describes. It is deliberately not the time the object was built: see the
    module docstring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(description="Publishing institution, engine, or person")
    as_of: str = Field(description="The date the value describes, ISO or YYYY-MM")
    model_version: str = Field(description="Version of the engine or model that produced it")
    reliability: Reliability = Reliability.DERIVED
    unit: str | None = None
    note: str | None = None

    def is_fit_for_advice(self) -> bool:
        """Whether this value may inform a regulated Recommendation.

        Synthetic values may not, ever. The control-plane pre-check calls this rather than inspecting the
        reliability field itself, so the rule lives in one place.
        """
        return self.reliability is not Reliability.SYNTHETIC


class Sourced(BaseModel):
    """A number with its provenance attached, for values a human will read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    provenance: Provenance


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def canonical_json(payload: Any, round_floats: bool = True) -> str:
    """The one serialisation. Sorted keys, compact separators, ASCII-safe.

    **Two callers with different needs, so the rounding is a parameter.**

    *Hashing* wants tolerance: a value differing only in its last bit must not produce a different
    identifier, or determinism would fail on arithmetic noise rather than on real change. So
    `round_floats=True`, the default, rounds to twelve places. This is what `idempotency_key` and
    `content_id` use.

    *Storage* wants exactness: a stored artefact must read back as the object that was written, and rounding
    silently changes the values. So `Contract.to_canonical_json` passes `round_floats=False`.

    Conflating the two was a real defect: with rounding applied to storage, a round-trip returned an object
    that compared unequal to the original, and the Phase 1 gate would have been passing on a technicality.
    """
    return json.dumps(
        _plain(payload, round_floats=round_floats),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _plain(value: Any, round_floats: bool = True) -> Any:
    """Reduce to JSON-native types, deterministically."""
    if isinstance(value, BaseModel):
        return _plain(value.model_dump(mode="json"), round_floats)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): _plain(v, round_floats)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_plain(v, round_floats) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return round(value, 12) if round_floats else value
    return str(value)


def idempotency_key(inputs: Any, model_version: str) -> str:
    """`hash(inputs + model_version)`, per the ground rules.

    The version is part of the key deliberately: the same inputs through a changed model are a different
    computation and must not share an identifier, or a cache would serve a stale answer.
    """
    return hashlib.sha256(
        canonical_json({"inputs": inputs, "model_version": model_version}).encode("utf-8")
    ).hexdigest()


def trace_id_from(key: str) -> str:
    """A short replay handle derived from the key.

    Derived rather than random so replaying the same inputs reproduces the same trace, which is the point
    of recording one.
    """
    return f"TR-{key[:16]}"


def content_id(prefix: str, payload: Any) -> str:
    """A content-addressed identifier: `<PREFIX>-<16 hex>`.

    Used where an object's identity *is* its content, so two engines producing the same object produce the
    same id and a consumer can tell whether anything changed.
    """
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:16]}"


# ---------------------------------------------------------------------------
# The base contract
# ---------------------------------------------------------------------------


class Contract(BaseModel):
    """Base for every versioned contract passed between engines.

    Subclasses set `CONTRACT_NAME` and `CONTRACT_VERSION`. Both are stamped onto the payload at
    serialisation, so an artefact on disk always says what shape it is and a consumer can refuse a version
    it does not understand rather than misreading it.

    Frozen and `extra="forbid"`: a contract is a promise, so a field nobody declared is an error rather than
    something to carry along silently.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_NAME: ClassVar[str] = "Contract"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    #: Whether this contract may cross the regulated wall unaided.
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.NOT_APPLICABLE

    #: The date the contract's data describes.
    as_of: str
    #: The engine version that produced it.
    model_version: str
    #: Replay handles. Optional so a contract can be constructed before it is stamped.
    idempotency_key: str | None = None
    trace_id: str | None = None
    #: Anything a reader must know. Never silently dropped.
    notes: tuple[str, ...] = ()

    @field_validator("as_of")
    @classmethod
    def _as_of_looks_like_a_date(cls, value: str) -> str:
        if not value or not value[:4].isdigit():
            raise ValueError(
                f"as_of={value!r} does not start with a year. It is the date the data describes, not a "
                f"free-text label."
            )
        return value

    # -- identity ---------------------------------------------------------

    def envelope(self) -> dict[str, Any]:
        """The contract's payload plus its shape stamps.

        This, not `model_dump`, is what gets written. A payload without its contract name and version is not
        interpretable by a consumer six months later.
        """
        return {
            "contract": self.CONTRACT_NAME,
            "contract_version": self.CONTRACT_VERSION,
            "regulated": self.REGULATED.value,
            "payload": self.model_dump(mode="json"),
        }

    def to_canonical_json(self) -> str:
        """The stored form. Exact: floats are not rounded, so a round trip returns the same object.

        Still byte-identical across runs, because key order and separators are fixed and float repr is
        deterministic. See `canonical_json` for why rounding belongs only in the hashing path.
        """
        return canonical_json(self.envelope(), round_floats=False)

    def stamped(self, inputs: Any) -> "Contract":
        """Return a copy carrying its determinism stamps, computed from `inputs`.

        Returns a copy rather than mutating, because the contract is frozen and because a stamp applied in
        place would make it impossible to tell a stamped object from an unstamped one.
        """
        key = idempotency_key(inputs, self.model_version)
        return self.model_copy(update={"idempotency_key": key, "trace_id": trace_id_from(key)})

    def is_stamped(self) -> bool:
        return bool(self.idempotency_key) and bool(self.trace_id)

    # -- round trip -------------------------------------------------------

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "Contract":
        """Rebuild from an envelope, refusing a shape this class does not implement.

        The name and version are checked rather than ignored. Reading a `Recommendation` as a `Score`
        because both happen to have overlapping fields is precisely the failure typed contracts exist to
        prevent.
        """
        for required in ("contract", "contract_version", "payload"):
            if required not in envelope:
                raise ValueError(f"envelope is missing {required!r}")
        if envelope["contract"] != cls.CONTRACT_NAME:
            raise ValueError(
                f"envelope holds a {envelope['contract']!r} but {cls.__name__} reads "
                f"{cls.CONTRACT_NAME!r}"
            )
        if envelope["contract_version"] != cls.CONTRACT_VERSION:
            raise ValueError(
                f"envelope is {cls.CONTRACT_NAME} v{envelope['contract_version']}, but this build reads "
                f"v{cls.CONTRACT_VERSION}. Migrate it rather than reading it as though the versions agree."
            )
        return cls.model_validate(envelope["payload"])

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """The emitted JSON Schema, as the Phase 1 gate requires."""
        schema = cls.model_json_schema()
        schema["title"] = cls.CONTRACT_NAME
        schema["x-contract-version"] = cls.CONTRACT_VERSION
        schema["x-regulated"] = cls.REGULATED.value
        return schema


def require_length(values: Sequence[float], expected: int, what: str) -> tuple[float, ...]:
    """Check a fixed-length vector, naming what it is when it is wrong."""
    out = tuple(float(v) for v in values)
    if len(out) != expected:
        raise ValueError(f"{what} has {len(out)} entries, expected {expected}")
    return out
