"""Golden layer B (LBSIM-13): lbsim's own behaviour, calibration 1.1.0 against 1.0.0, leaf by leaf.

Layer A holds the port to the draft. Layer B has no outside reference: it is lbsim's findings on the frozen lbs
cases (``golden/lbs_cases``) under both seeds, frozen as a regression reference, with the exact list of leaves
that differ and which of the three decisions moves each one. Attribution is by switching one decision on at a
time from 1.0.0: a leaf that moves with LBSIM-08 alone is LBSIM-08's; one that moves only with LBSIM-11 is
LBSIM-11's; one that moves only with LBSIM-07 is LBSIM-07's; a leaf that moves with none alone but with two
together names both. A leaf that moved under 1.1.0 and under no combination of the three would be unattributed,
and the test refuses it.

Compared as a flat map from a path to a leaf, with lists of records keyed by their id (a finding by its code, an
income path by its code, a saving need by its goal) and without the leaves that name the build rather than the
household (``artefact_id``, ``calibration_version`` and ``provenance``).
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from .calibration import ACTIVE_SEED, SEED
from .contracts import Calibration, LbsRequest, LbsSheet
from .fast.build import build_findings
from .ids import sha256

DECISIONS: dict[str, str] = {"LBSIM-08": "inflation", "LBSIM-11": "earning_power", "LBSIM-07": "market"}
_KEYS = ("code", "person_id", "goal_id", "key", "question_key", "when")
_SKIP = {"artefact_id", "calibration_version", "provenance"}


def flatten(value: Any, path: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {} if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            if not path and k in _SKIP:
                continue
            flatten(v, f"{path}.{k}" if path else k, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            label = str(i)
            if isinstance(v, dict):
                ident = [f"{k}={v[k]}" for k in _KEYS if k in v and isinstance(v[k], str)]
                if "rate_basis" in v:
                    ident.append(f"rate_basis={v['rate_basis']}")
                if ident:
                    label = ",".join(ident)
            flatten(v, f"{path}[{label}]", out)
    else:
        out[path] = value
    return out


def changed(a: dict[str, Any], b: dict[str, Any], tol: float = 1e-9) -> list[str]:
    keys = sorted(set(a) | set(b))
    out = []
    for k in keys:
        x, y = a.get(k, "<absent>"), b.get(k, "<absent>")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) \
                and not isinstance(y, bool):
            if abs(float(x) - float(y)) > tol * max(1.0, abs(float(x)), abs(float(y))):
                out.append(k)
        elif x != y:
            out.append(k)
    return out


def variant(names: tuple[str, ...]) -> Calibration:
    """1.0.0 with the named decisions switched to 1.1.0's reading."""
    update = {DECISIONS[n]: getattr(ACTIVE_SEED.behaviour, DECISIONS[n]) for n in names}
    behaviour = SEED.behaviour.model_copy(update=update)
    return SEED.model_copy(update={"behaviour": behaviour, "version": "1.0.0-" + "-".join(
        n.split("-")[1] for n in names)})


def load_case(folder: Path) -> tuple[LbsSheet, LbsRequest, dict[str, Any]]:
    sheet = json.loads((folder / "sheet.json").read_text(encoding="utf-8"))
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    return LbsSheet.model_validate(sheet), LbsRequest.model_validate(request), sheet


def findings(folder: Path, records: dict[str, Any], cal: Calibration) -> dict[str, Any]:
    sheet, request, raw = load_case(folder)
    return build_findings(sheet, request, records, cal, sheet_sha256=sha256(raw)).model_dump(mode="json")


def attribute(folder: Path, records: dict[str, Any]) -> dict[str, list[str]]:
    """Every leaf 1.1.0 changes, with the decisions that move it."""
    base = flatten(findings(folder, records, SEED))
    full = flatten(findings(folder, records, ACTIVE_SEED))
    moved = changed(base, full)
    alone = {n: set(changed(base, flatten(findings(folder, records, variant((n,)))))) for n in DECISIONS}
    out: dict[str, list[str]] = {}
    pairs = {c: None for c in itertools.combinations(DECISIONS, 2)}
    for leaf in moved:
        who = [n for n in DECISIONS if leaf in alone[n]]
        if not who:
            for combo in pairs:
                if pairs[combo] is None:
                    pairs[combo] = set(changed(base, flatten(findings(folder, records, variant(combo)))))
                if leaf in pairs[combo]:
                    who = list(combo)
                    break
        out[leaf] = who
    return out
