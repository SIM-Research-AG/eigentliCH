"""The macro regime, as a population-level read. Item 5's Regime pane.

Item 5: "The Regime pane is population-level. It carries no member data, sits below both regulatory
boundaries, and can be shown to anyone — including before sign-in. **This is the product's most
distinctive output at zero data cost**, and today nothing exposes it to someone who has not completed an
intake."

Journey & Design page 3 makes the same point as architecture rather than as marketing: "The regime and the
return profiles are population-level and carry no member data at all: computed once, shared by everyone
... The first boundary is what makes the public question field possible: everything on the population side
can be shown to anyone, before signup, without member data and without regulatory exposure."

===========================================================================================================
A READING, NEVER AN ARTEFACT
===========================================================================================================

The AssumptionSet's `rates` block carries a great deal more than a regime read: the Fund Map's per-state
return profiles, its state grid, its scenario probabilities, the state-to-scenario map. Those are engine
**artefacts**, and C-03 and R-304 both say the ids travel and the artefacts do not —
`services/assumptions.describe` sets `artefacts_served: False` for exactly this reason.

So this module does not pass `rates` through. It takes the Regime's own `current` block and admits **only
scalar values** from it. That is a structural rule rather than a list of keys: a scalar is a reading — a
phase name, a probability, a date — and a nested array or matrix is a piece of a model. A key added to the
Regime upstream is therefore served if it is a reading and dropped if it is an artefact, without anybody
having to remember to update a whitelist.

**What travels beside it is provenance**, not payload: the regime id, the scope, the model version and the
`as_of` date the engines stamp. That is what makes a figure on a public page traceable to a run somebody
can replay.

===========================================================================================================
NOT AVAILABLE IS AN ANSWER
===========================================================================================================

If no AssumptionSet has been published, this says so. R-302's shape, and `services/assumptions.current`
already raises rather than defaulting: "a default rate is an invented rate wearing a different hat". A
public page that invented a regime read would be the same defect with a larger audience.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..models import NoAssumptionSet
from .assumptions import current as current_assumption_set

#: What may be served out of the Regime's `current` block. A structural rule, not a list of keys.
SERVABLE = (str, int, float, bool)


def _readings(current: object) -> dict:
    """The scalar readings in a Regime's `current` block, and nothing nested.

    A nested value is a piece of the model — a state grid, a profile vector, a timeline — and C-03 keeps
    those on the server. Dropping by SHAPE rather than by name means a reading added upstream is served
    and an artefact added upstream is not, with nobody having to maintain a whitelist.
    """
    if not isinstance(current, dict):
        return {}
    # `bool` is a subclass of `int`, so it is already covered; `None` is not in the tuple and is dropped,
    # which is right — an absent reading is absent rather than served as null.
    return {key: value for key, value in current.items() if isinstance(value, SERVABLE)}


def read(session: Session, *, on: date | None = None) -> dict:
    """The current macro read, or an honest statement that there is none.

    Takes no `member_id` and touches no member table. That is the whole claim of this module and a test
    asserts it over the source rather than trusting the signature.
    """
    try:
        published = current_assumption_set(session, on=on)
    except NoAssumptionSet as missing:
        return {
            "available": False,
            # The reason, in the estate's own words, rather than a bare false.
            "reason": str(missing),
            "regime": {},
            "source": None,
            # Stated on the payload so a client reads one key rather than inferring from the shape.
            "population_level": True,
            "carries_member_data": False,
        }

    rates = published.rates or {}
    source = (rates.get("source") or {}).get("market_signal") or {}
    return {
        "available": True,
        "reason": None,
        "regime": _readings(rates.get("regime_current")),
        # Provenance, not payload: the ids that make a public figure traceable to a run.
        "source": {
            "regime_id": source.get("regime_id"),
            "scope": source.get("scope"),
            "as_of": source.get("as_of"),
            "model_version": source.get("model_version"),
            "assumption_set_id": published.id,
            "assumption_set_version": published.version,
            "published_by": published.published_by,
        },
        "population_level": True,
        "carries_member_data": False,
        # C-03 / R-304, stated where a client author reads it.
        "artefacts_served": False,
    }


__all__ = ["SERVABLE", "read"]
