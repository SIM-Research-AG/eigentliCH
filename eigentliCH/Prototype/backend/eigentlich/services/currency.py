"""Provenance is not currency. Item 6 of the update script, and the gap page 3 leaves open by name.

The Befund guarantees that a figure came from somewhere. It does not guarantee that the figure is still
true. A plan can be quietly wrong for years while the app keeps re-solving it and stating properly-sourced
numbers — every check green, every source recorded, the answer stale.

So every input class carries two things: an **age**, which is a fact about the data, and a **validity
horizon**, which is a published judgement about how long that kind of fact stays usable. When a
load-bearing input passes its horizon, a finding built on it degrades to *could not be determined* rather
than being presented as certified.

===========================================================================================================
WHY THE THIRD STATE ALREADY EXISTS AND IS NOT INVENTED HERE
===========================================================================================================

The Household Optimiser returns three answers, not two: this plan funds the goal, it cannot, or it could
not be determined. Page 3 says so, and item 6 says to use the third rather than adding a fourth vocabulary
for staleness. `DETERMINATIONS` below is therefore two values from the *fact's* point of view — it stands,
or it could not be determined — and the second is deliberately spelled the same way the optimiser spells
it. A member who sees "could not be determined" because an input expired and one who sees it because the
solve did not converge are being told the same true thing: nobody can certify this today.

There is deliberately **no** `stale`, `expired`, `warning` or `needs_review` state. Those are all the
member's problem to fix, and naming them that way turns a property of the data into a nag — which is
Principle 4's territory and it forbids it.

===========================================================================================================
NO HORIZON IS WRITTEN HERE
===========================================================================================================

Not one number in this module. `content.horizon_months` reads them from
`client/content/currency-horizons.json`, published by a named person on a stated date, and it **raises**
for an input class nobody has published one for. That refusal is the design: an unpublished horizon means
the currency of a finding cannot be judged, and the honest response is to say so rather than to treat the
input as never expiring. Failing open would present a stale figure as certified, which is the exact defect
this module exists to close.

`expires_on` is computed by calendar arithmetic, which is not an assumption — twelve months after
14 March 2027 is 14 March 2028 in any published model.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from ..content import (
    ContentMissing,
    HorizonNotPublished,
    currency_horizons,
    horizon_is_load_bearing,
    horizon_months,
    horizon_provenance,
)

#: What a fact may say about itself. Two values, and the second is the Household Optimiser's own third
#: answer rather than a staleness vocabulary of its own — see the module docstring.
STANDS = "stands"
COULD_NOT_BE_DETERMINED = "could_not_be_determined"
DETERMINATIONS = (STANDS, COULD_NOT_BE_DETERMINED)

#: The input classes this application can currently age, which is a different list from the classes that
#: have a published horizon. A class here with no published horizon raises; a published horizon for a class
#: nothing reads is inert and harmless.
#:
#: **Closed, and asserted against the content file by a test.** A class the Befund attaches to a fact and
#: that nobody published a horizon for would raise at render time, which is loud but late; the test makes
#: it a suite failure instead.
INPUT_CLASSES = ("household_composition",)


def _add_months(start: date, months: int) -> date:
    """Calendar arithmetic, day-clamped. 31 January plus one month is 28 or 29 February, never 3 March.

    Written out rather than reached for in a dependency because the root environment gains nothing from
    `dateutil` for eleven lines, and because the clamping rule is the part a reader needs to see: rolling
    forward instead would make a horizon stated in months expire on a different day of the month depending
    on which month it started in.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


@dataclass(frozen=True)
class Currency:
    """How old one stated input is, and whether it is still inside its published horizon."""

    input_class: str
    #: The date the value describes. For a household this is `composition_as_of`, never `created_at`.
    stated_on: date
    age_days: int
    horizon_months: int
    expires_on: date
    expired: bool
    load_bearing: bool

    @property
    def degrades(self) -> bool:
        """Whether a finding resting on this input must report that it could not be determined.

        Expiry alone is not enough: a non-load-bearing input can pass its horizon without making a finding
        uncertifiable. Both conditions are published rather than decided here.
        """
        return self.expired and self.load_bearing

    def as_dict(self) -> dict:
        return {
            "input_class": self.input_class,
            "stated_on": self.stated_on.isoformat(),
            "age_days": self.age_days,
            "horizon_months": self.horizon_months,
            "expires_on": self.expires_on.isoformat(),
            "expired": self.expired,
            "load_bearing": self.load_bearing,
        }


def of(input_class: str, stated_on: date, *, today: date) -> Currency:
    """The currency of one stated input.

    `today` is required rather than defaulted. Every other date-sensitive service in this build takes it,
    for the reason A105's last paragraph records: a function that reaches for `date.today()` itself is a
    function whose tests pass only while the wall clock agrees with them.

    Raises:
        HorizonNotPublished: When no horizon is published for `input_class`.
    """
    months = horizon_months(input_class)
    expires_on = _add_months(stated_on, months)
    return Currency(
        input_class=input_class,
        stated_on=stated_on,
        age_days=(today - stated_on).days,
        horizon_months=months,
        expires_on=expires_on,
        # `>` and not `>=`: a value is still valid on the day it expires. A horizon that ran out at
        # midnight on its own expiry date would make the boundary depend on the reader's timezone.
        expired=today > expires_on,
        load_bearing=horizon_is_load_bearing(input_class),
    )


def determination(currencies: tuple[Currency, ...] | list[Currency]) -> str:
    """What a fact resting on these inputs may claim.

    One degraded input is enough. There is no weighting, no majority and no "mostly current": a figure
    computed from a household composition nobody has confirmed for over a year is not partly certifiable.
    """
    if any(one.degrades for one in currencies):
        return COULD_NOT_BE_DETERMINED
    return STANDS


def published_classes() -> tuple[str, ...]:
    """Input classes with a published horizon, for a caller that wants to report coverage."""
    return tuple(currency_horizons())


def unpublished_classes() -> tuple[str, ...]:
    """Input classes this application ages and nobody has published a horizon for.

    Empty in a correct build. A test asserts it, so a new entry in `INPUT_CLASSES` fails the suite rather
    than raising `HorizonNotPublished` at render time for a member.
    """
    published = set(currency_horizons())
    return tuple(name for name in INPUT_CLASSES if name not in published)


__all__ = [
    "COULD_NOT_BE_DETERMINED",
    "Currency",
    "DETERMINATIONS",
    "HorizonNotPublished",
    "INPUT_CLASSES",
    "STANDS",
    "determination",
    "of",
    "published_classes",
    "horizon_provenance_or_none",
    "unpublished_classes",
]


def horizon_provenance_or_none() -> dict | None:
    """`content.horizon_provenance()`, or None when no horizons are published at all.

    The Befund must render for a member even in a build where nobody has published a horizon file yet —
    the report is still true, it simply cannot judge currency. `None` says exactly that, and is different
    from a dict saying the horizons are provisional.
    """
    try:
        return horizon_provenance()
    except HorizonNotPublished:  # pragma: no cover - the file is published in this build
        return None
    except ContentMissing:
        return None
