"""The canton's effect on tax, as a mechanism with an external table rather than as invented numbers.

**The canton has been collected since the first interview and has reached no equation.** `income_tax` is a
smooth approximation with one asymptotic rate for the whole country, `wealth_tax_rate` is flat, and the comment
where the tax function is defined says so: matching a real cantonal tariff is a calibration task rather than a
modelling one. Until now that meant the report had to admit the canton changes nothing, which is honest and
useless -- between Zug and Geneva the same income carries a materially different burden, and a plan built on
one national rate is wrong for almost everybody.

**What is built here is the mechanism, not the numbers.** A twenty-six canton table written from memory is
exactly what the house rule forbids: if a number is not sourced, it does not appear. A wrong cantonal rate is
worse than none, because it looks authoritative -- a client in Zug reading a Geneva burden has no way to tell.

So the factors live in `data/canton_tax.json`, outside the code, and this module:

  - loads them if the file is there, validating every entry against the canton list the interview offers;
  - applies them to `tax_rate_max` and `wealth_tax_rate` in the CONVERTER, so `model/dynamics.py` and
    `optim/symbolic.py` are untouched and the dual-transcription parity tests still hold;
  - reports, for every household, whether its canton was calibrated -- so the dossier states a fact either
    way rather than falling silent.

**The file this wants.** Effective tax burden by canton is published by the Eidgenössische Steuerverwaltung
(ESTV) as "Steuerbelastung in den Kantonshauptorten", and the cantonal wealth-tax rates likewise. One
`factor` per canton, relative to the model's own national rate, with the vintage and the source recorded in
the file. Until it exists every factor is 1.0 and every report says the canton is recorded and not calibrated,
which is what it says today -- the difference is that dropping in the file is now the whole change.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from pathlib import Path
from typing import Any, Iterator

# lbsim port (LBSIM-12): the draft read `Projects/eigentliCH/data/canton_tax.json`, which does not exist. The
# table is the lbsim calibration's seed record `canton-tax` (a verbatim copy of the only file found, with an
# `_about` block added). A run sets the calibration's copy with `use_table`; without one the packaged seed record
# is read. Nothing below the loading step differs from the draft.

#: The packaged seed record.
TABLE = Path(__file__).resolve().parents[1] / "seed_records" / "canton-tax.json"

_ACTIVE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("lbsim_canton_table", default=None)

#: The twenty-six cantons, spelled as `onboarding-chat.html` offers them. A factor for a name not on this list
#: is a typo that would otherwise apply silently to nobody, so loading refuses it by name.
CANTONS: tuple[str, ...] = (
    "Aargau", "Appenzell Ausserrhoden", "Appenzell Innerrhoden", "Basel-Landschaft", "Basel-Stadt",
    "Bern", "Freiburg", "Genf", "Glarus", "Graubünden", "Jura", "Luzern", "Neuchâtel", "Nidwalden",
    "Obwalden", "Schaffhausen", "Schwyz", "Solothurn", "St. Gallen", "Tessin", "Thurgau", "Uri",
    "Waadt", "Wallis", "Zug", "Zürich",
)

#: A factor outside these ranges is refused rather than applied. The guard exists to catch a units error -- a
#: percentage entered as a rate is wrong by a hundred -- not to enforce a prior about how much cantons differ.
#:
#: **The two bounds differ because the two spreads differ, and measuring them corrected me.** The wealth bound
#: was 2.5 like the income one, and the first real table was refused for Freiburg at 2.8. That was not a units
#: error: wealth-tax burdens genuinely run from 0.12 % in Nidwalden to 0.68 % in Neuchâtel, a factor of nearly
#: six between cantons, against a national approximation of 0.2 %. Income burdens are far tighter -- 6.1 % in
#: Zug against 18.7 % in Neuchâtel, a factor of three -- because the federal share is common to all of them
#: and the cantonal share is not.
#:
#: Measured over the BFS table of 2023: income factors 0.68 to 1.65, wealth factors 0.60 to 3.40. The bounds
#: sit outside those with room, and far inside a hundred.
_FACTOR_MIN, _FACTOR_MAX = 0.4, 2.5
_WEALTH_FACTOR_MIN, _WEALTH_FACTOR_MAX = 0.2, 6.0


class CantonTableError(ValueError):
    """The table exists and cannot be trusted. Distinct from the table being absent, which is normal."""


@contextlib.contextmanager
def use_table(table: dict[str, Any] | None) -> Iterator[None]:
    """Run the block under this table (the calibration's `canton-tax` record). `None` is no table: every
    canton is then uncalibrated, as the draft reads a missing file."""
    token = _ACTIVE.set({"__absent__": True} if table is None else table)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def load(path: Path | None = None) -> dict[str, Any]:
    """The table, or an empty one. Never raises on absence; always raises on a table it cannot trust.

    **Absent and wrong are different states and are treated differently.** No file means no calibration, which
    is the current situation and is reported as such. A file with an unknown canton or an implausible factor
    means somebody built a table and made a mistake in it, and applying three quarters of it silently is worse
    than applying none: the households in the correct rows would be right and the others wrong, with nothing
    to distinguish them.
    """
    active = _ACTIVE.get() if path is None else None
    if active is not None and active.get("__absent__"):
        return {"present": False, "factors": {}, "wealth_factors": {}, "source": "", "as_of": ""}
    if active is not None:
        raw = active
        src_name = "canton-tax"
    else:
        p = path or TABLE
        src_name = p.name
        if not p.is_file():
            return {"present": False, "factors": {}, "wealth_factors": {}, "source": "", "as_of": ""}
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise CantonTableError(f"{p.name} is not valid JSON: {exc}") from exc

    if not raw.get("source") or not raw.get("as_of"):
        raise CantonTableError(
            f"{src_name} must carry `source` and `as_of`. A tax table without a vintage cannot be checked "
            f"against anything, and every forward-looking figure in a report inherits it."
        )

    factors = raw.get("income_factors") or {}
    wealth = raw.get("wealth_factors") or {}
    for name, table in (("income_factors", factors), ("wealth_factors", wealth)):
        for canton, value in table.items():
            if canton not in CANTONS:
                raise CantonTableError(
                    f"{src_name}: {table and name} names {canton!r}, which is not one of the 26 cantons the "
                    f"interview offers. A factor under a misspelled name applies to nobody and looks applied."
                )
            try:
                f = float(value)
            except (TypeError, ValueError) as exc:
                raise CantonTableError(f"{src_name}: {canton} has a non-numeric factor {value!r}") from exc
            lo, hi = ((_WEALTH_FACTOR_MIN, _WEALTH_FACTOR_MAX) if name == "wealth_factors"
                      else (_FACTOR_MIN, _FACTOR_MAX))
            if not lo <= f <= hi:
                raise CantonTableError(
                    f"{src_name}: {canton} has a {name[:-8]} factor of {f}, outside {lo} to {hi}. The national "
                    f"rate is a mid-country approximation and no canton is that far from it; this reads as a "
                    f"percentage entered as a rate."
                )
    return {"present": True, "factors": factors, "wealth_factors": wealth,
            "source": str(raw["source"]), "as_of": str(raw["as_of"])}


def factors_for(canton: str, path: Path | None = None) -> dict[str, Any]:
    """What to multiply the two tax rates by for this canton, and whether that came from a table.

    Returns 1.0 for both when the canton is unknown or the table absent, and says so. A caller that ignores
    `calibrated` will apply the national rate and report it as the canton's, which is the thing this module
    exists to stop.
    """
    table = load(path)
    name = (canton or "").strip()
    income = table["factors"].get(name)
    wealth = table["wealth_factors"].get(name)
    return {
        "canton": name,
        "calibrated": income is not None or wealth is not None,
        "income_factor": float(income) if income is not None else 1.0,
        "wealth_factor": float(wealth) if wealth is not None else 1.0,
        "source": table["source"],
        "as_of": table["as_of"],
        "why_not": ("" if table["present"] else
                    "Es liegt keine kantonale Steuertabelle vor. Gerechnet wird mit dem nationalen "
                    "Näherungssatz des Modells.")
        if not table["present"] else
        ("" if income is not None or wealth is not None else
         f"Für {name or 'diesen Kanton'} enthält die Tabelle keinen Faktor."),
    }
