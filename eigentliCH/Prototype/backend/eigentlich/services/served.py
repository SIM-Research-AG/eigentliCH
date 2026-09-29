"""C-03 / R-304 at the last boundary: what may be put in front of a member.

**Why this is a function and not a rule everyone remembers.** Two new surfaces now carry engine output to a
member — a stored run result (`services/runs.py`) and a goal illustration (`services/illustration.py`) —
and both are built by copying fields out of something bigger. Copying is exactly how an artefact escapes:
not by anyone deciding to serve one, but by a dict being passed through one layer more than intended.
`tests/test_constraints.py::test_no_engine_artefact_served_over_http` checks the *static* shape of the
application — the mounts, the bundle, and the API layer's imports. It cannot check a payload assembled at
runtime, so this is the runtime half, and it **raises** rather than filtering, because a payload that
reached here carrying an artefact key was built wrong and filtering it would hide that.

**Allowlist, then check.** Both callers build their payload from a named allowlist of keys; this module is
the second net under that. A denylist alone would pass the first field a new engine version adds.

The markers are the same four `test_no_engine_artefact_served_over_http` scans the client bundle for, plus
the three ways the estate hands back something that is not a reading:

  * `regime_timeline_id`, `return_set_id` — name a *published artefact*, not a run. The AssumptionSet
    legitimately stores both in `rates["source"]` (they are what makes a number traceable, and that table
    is K0 and never served); an illustration or a run result carries the `assumption_set_id` instead.
  * `state_grid`, `state_to_scenario`, `building_blocks`, `distributions` — the artefact's payload.
  * `replay` — the command that runs an engine by hand. Not an artefact; a route to one, which R-304's
    "under any circumstance" covers just as squarely.

**`raw` is deliberately NOT in the list**, and that is a decision worth stating. It is the engine's own
internals and no member's business, so it is kept out by the allowlist in `services/runs.py` — not by a
marker, because `raw` is three letters that occur inside ordinary German and English words and a substring
check on it would refuse `Drawdown` and `Vorrat`. A marker has to be specific enough to be checked as a
substring, and the ones above are.
"""

from __future__ import annotations

import json
from typing import Any

#: Keys that must not appear anywhere in a member-facing payload, at any depth, as a key or inside a
#: string. Checked as substrings of the rendered document as well as as keys, because a marker arriving as
#: a *value* — an id pasted into a note, an engine caveat quoting its own artefact — is the same disclosure.
ARTEFACT_MARKERS = (
    "regime_timeline_id",
    "return_set_id",
    "building_blocks",
    "state_grid",
    "state_to_scenario",
    "distributions",
    "replay",
)


class EngineArtefactWouldBeServed(Exception):
    """C-03 / R-304. A payload about to reach a member carries an engine artefact.

    Raised, not filtered. R-304 says "under any circumstance", and a filter here would turn a construction
    defect into a payload that is quietly one field short of what its author believed it contained.
    """


def artefact_markers_in(payload: Any) -> list[str]:
    """Which markers occur in `payload`, at any depth, as a key or inside a rendered value.

    Separated from the assertion so a test can hand it a payload that *does* carry one and watch it come
    back. A check that has only ever been shown to return an empty list is the shape this estate has been
    bitten by five times (A20, A63, A66, A68, A81).
    """
    rendered = json.dumps(payload, default=str, sort_keys=True)
    return [marker for marker in ARTEFACT_MARKERS if marker in rendered]


def assert_no_engine_artefact(payload: Any, *, where: str) -> Any:
    """Return `payload` unchanged, or raise. C-03 / R-304.

    Returns its argument so it can be wrapped around the value being built — `return
    assert_no_engine_artefact(illustration, where="goal illustration")` — which is the form that cannot be
    added and then forgotten at the one call site that skipped it.
    """
    found = artefact_markers_in(payload)
    if found:
        raise EngineArtefactWouldBeServed(
            f"C-03 / R-304: the {where} carries engine artefact keys {found}. No engine, weight file or "
            f"model artefact is served to the browser under any circumstance. Build the payload from the "
            f"named allowlist in this module's callers; do not copy an engine reply through."
        )
    return payload


def strip_artefacts(value: Any) -> Any:
    """Recursively drop `ARTEFACT_MARKERS` keys from a mapping. For sanitising an engine reply once.

    Used on the way IN — before a run's result is stored — rather than on the way out, so the stored row,
    the HTTP poll and the R-154 export are all covered by the same single pass. It removes keys only; a
    marker appearing as a *value* is left for `assert_no_engine_artefact` to refuse, because a value that
    names an artefact is a construction defect and not something to tidy away.
    """
    if isinstance(value, dict):
        return {
            key: strip_artefacts(inner)
            for key, inner in value.items()
            if key not in ARTEFACT_MARKERS
        }
    if isinstance(value, (list, tuple)):
        return [strip_artefacts(inner) for inner in value]
    return value


__all__ = [
    "ARTEFACT_MARKERS",
    "EngineArtefactWouldBeServed",
    "artefact_markers_in",
    "assert_no_engine_artefact",
    "strip_artefacts",
]
