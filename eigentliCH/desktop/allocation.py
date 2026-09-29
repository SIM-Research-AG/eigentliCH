"""The asset allocation for one household, derived from its own position and goal.

Runs under `engines/PCP/.venv`, which is the only interpreter here that has both `pydantic` (for the contracts
and the mandate derivation) and the Optimiser itself. The root `.venv` has no numpy and the Life Balance Sheet's
has no pydantic, so this is a third leg of the same subprocess seam every other tool in this repo uses -- not a
new pattern, just one more crossing of an existing wall.

**What is derived and what is policy.** `engines/lbs/derive.py` is the authority and its table is not repeated
here: the target curve's LEVEL comes from the return this household's goal requires, its SHAPE is CIO policy,
the position caps come from the goal's buffer against each block's published crisis loss, the liquidity bounds
from the goal's deadline and the currency bounds from the goal's own currency. Region, role, capital type, phase
and asset class are policy. The ESG floor is a household preference and says so.

**This runs pass 0 of the fixed point, and no further.** `orchestration/per_user_path.py` iterates the mandate
and the allocation to a common return assumption (M63), because the mandate's level depends on what the
portfolio earns and what it earns depends on the allocation the mandate produced. That iteration needs the whole
shared path -- the regime checks, the returnset join, the convergence test -- and it belongs there. What runs
here is the first pass, seeded with the M59 role-bounded proxy, and **the proxy is an upper bound and not a
forecast**. Every report that carries this allocation carries that sentence with it, in the same words the
orchestration uses when the Optimiser is unavailable to it. A number whose provenance is stated as weaker than
it looks is usable; the same number presented as settled is not.

**Three things are written next to every allocation, because the manual requires them.** That it is
constraint-driven -- the optimiser reports what fraction of the objective's level the weights actually control,
measured between 1 and 4 % on real mandates, so the structure comes from the bounds and the curve fit breaks
ties. What it excludes, because in one case the only globally diversifying block received zero and lowering the
currency floor changed nothing. And the data vintage, because every forward-looking figure inherits it.

**The mandate file is written to disk and the report is not.** `desktop/server.py` states that nothing is
persisted, and that rule is about the household's answers. The Optimiser reads a mandate from a path -- that is
its interface, not a choice made here -- so the derived mandate is materialised under the name the household
already carries in the intake. It contains the household's position, so it is gitignored along with everything
else prefixed `onb-`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PCP_HOME = ROOT / "engines" / "PCP"
PCP_PY = PCP_HOME / ".venv" / "Scripts" / "python.exe"

#: The scope and horizon the published strategic vintage is filed under. Both are properties of the artefact,
#: not choices: `resolve_pair` refuses a regime and a returnset that disagree, so these two values select one
#: consistent pair rather than two independent things.
SCOPE = "Global"
RETURNSET_HORIZON_YEARS = 1.0

#: Minutes. The Optimiser is a convex solve over 8 blocks and 25 states and takes seconds; a minute is generous
#: and still short enough that a hung solve does not hold up a report.
OPTIMISER_TIMEOUT_S = 120

#: The child processes are told to speak UTF-8 explicitly. **Without this the server dies on a traceback
#: rather than reporting it.** Windows gives a subprocess the console codepage, so a Python traceback
#: containing an umlaut -- which every message in this codebase does -- arrives as cp1252 bytes, and
#: `subprocess.run(encoding="utf-8")` raises UnicodeDecodeError while trying to read the error. The failure
#: then has nothing to do with the actual fault and hides it completely, which is how it was found.
_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


#: What the mandate's target was derived FROM, in words a report prints. The distinction is not decoration:
#: a mandate derived from a shortfall is asking the portfolio to close a gap, and one derived from preservation
#: is asking it to still be there. Reading the second as the first would present a conservative allocation as
#: an ambitious one.
_BASIS_LABEL = {
    "gap": "dem Kapitalbedarf aus der Deckungslücke",
    "bridge": "dem Kapitalbedarf der Brücke bis zur Referenzaltersgrenze",
    "preservation": "dem Erhalt des heute entnahmefähigen Vermögens, weil keine Deckungslücke besteht",
}


class AllocationUnavailable(RuntimeError):
    """The allocation could not be produced. Carries why, in words a report can print."""


def available() -> bool:
    return PCP_PY.exists()


# --- the driver, executed inside the PCP interpreter ----------------------------------------------------
#
# Passed as a string to `python -c` rather than kept as a module on disk, for the same reason
# `engines/lbs/adapter.py` does it: the code that crosses the wall is small, it needs no imports from this side,
# and a file would invite someone to run it with the wrong interpreter. It writes one JSON object to stdout.

_DRIVER = r"""
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root))
args = json.loads(sys.argv[2])

from contracts.references import resolve_pair, load_returnset
from engines.lbs.derive import (DerivationInputs, derive_snapshot, render_mandate_yaml,
                                proxy_expected_return, allocation_expected_return)

regime, returnset = resolve_pair(args["scope"], args["horizon_returnset"])
payload = load_returnset(args["scope"], args["horizon_returnset"])

# **The universe, narrowed before the derivation sees it** (A155). A bound of zero lets the optimiser
# see an instrument and choose none of it; removing the block means it is not on the table. The risk
# profile decides which asset classes are on the table at all, and doing it here rather than as a bound
# is the difference the record calls its one hard edge.
_drop = set(args.get("exclude_asset_classes") or ())
if _drop:
    payload = dict(payload)
    payload["building_blocks"] = [b for b in payload.get("building_blocks", [])
                                  if b.get("asset_class") not in _drop]

_bounds = args.get("policy_bounds")
inputs = DerivationInputs(
    household_id=args["household_id"],
    W_L=args["W_L"], W_R=args["W_R"], D=args["D"],
    E=args.get("E"), N=args.get("N"), H=args.get("H"),
    goal_kind=args["goal_kind"], target=args["target"],
    horizon_years=args["horizon_years"], epsilon=args["epsilon"],
    annual_contribution=args["annual_contribution"],
    currency=args["currency"], esg_min=args["esg_min"],
    as_of=returnset.as_of,
    # Per-client bounds where a profile produced them, the CIO block where it did not. Passing the
    # default explicitly rather than omitting the argument keeps one code path.
    **({"policy_bounds": {k: {kk: (vv["lower"], vv["upper"]) for kk, vv in v.items()}
                          for k, v in _bounds.items()}} if _bounds else {}),
)
snapshot, notes = derive_snapshot(inputs, regime, payload)
stem = "derived_" + args["household_id"].replace(" ", "_").replace("/", "_")
mandate_path = root / "engines" / "PCP" / "mandates" / (stem + ".yaml")
mandate_path.parent.mkdir(parents=True, exist_ok=True)
mandate_path.write_text(render_mandate_yaml(snapshot, payload, market=args["scope"]),
                        encoding="utf-8")

mandate = snapshot.mandate
out = {
    "universe_size": len(payload.get("building_blocks", [])),
    "asset_classes_dropped": sorted(_drop),
    "snapshot_id": snapshot.snapshot_id(),
    "regime_id": regime.regime_id,
    "returnset_as_of": returnset.as_of,
    "mandate_stem": stem,
    "mandate_path": str(mandate_path),
    "required_return": getattr(mandate.curve, "required_return", None),
    "buffer": getattr(snapshot.goal, "buffer", None),
    "feasible": getattr(snapshot.goal, "feasible", None),
    "position_cap": getattr(mandate.position_cap, "value", None),
    "position_cap_derived": getattr(mandate.position_cap, "derived", None),
    "bound_sources": mandate.sources_in_use(),
    "proxy_expected_return": float(proxy_expected_return(payload, None)),
    "notes": list(notes),
    "blocks": [
        {"id": b.get("bb_id"), "name": b.get("name"), "role": b.get("role"),
         "currency": b.get("currency"), "liquidity": b.get("liquidity")}
        for b in payload.get("building_blocks", [])
    ],
}

bounds = {}
for family in ("liquidity", "currency", "role", "asset_class", "region"):
    got = getattr(mandate, family, None) or getattr(mandate, "bounds", {}).get(family, None) \
        if hasattr(mandate, "bounds") else None
    if got:
        bounds[family] = {k: {"lower": getattr(v, "lower", None), "upper": getattr(v, "upper", None),
                              "source": getattr(v, "source", None)}
                          for k, v in dict(got).items()}
out["bounds"] = bounds
sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
"""


def derive(*, household_id: str, W_L: float, W_R: float, D: float,
           E: float | None, N: float | None, H: float | None,
           goal_kind: str, target: float, horizon_years: float, epsilon: float,
           annual_contribution: float, currency: str = "CHF",
           esg_min: float = 0.0, policy_bounds: dict | None = None,
           exclude_asset_classes: list | None = None) -> dict[str, Any]:
    """Derive the mandate and materialise it. Returns the mandate's own description of itself."""
    if not available():
        raise AllocationUnavailable(
            f"the Optimiser's interpreter is missing at {PCP_PY}. The allocation needs "
            f"engines/PCP/.venv, which carries pydantic and the Optimiser itself."
        )
    args = {"scope": SCOPE, "horizon_returnset": RETURNSET_HORIZON_YEARS,
            "household_id": household_id, "W_L": W_L, "W_R": W_R, "D": D,
            "E": E, "N": N, "H": H, "goal_kind": goal_kind, "target": target,
            "horizon_years": horizon_years, "epsilon": epsilon,
            "annual_contribution": annual_contribution, "currency": currency,
            "esg_min": esg_min, "policy_bounds": policy_bounds,
            "exclude_asset_classes": list(exclude_asset_classes or ())}
    proc = subprocess.run([str(PCP_PY), "-c", _DRIVER, str(ROOT), json.dumps(args)],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_CHILD_ENV,
                          timeout=OPTIMISER_TIMEOUT_S, cwd=str(ROOT))
    if proc.returncode != 0:
        raise AllocationUnavailable(_reason(proc.stderr or proc.stdout))
    start = proc.stdout.find("{")
    if start < 0:
        raise AllocationUnavailable("the derivation produced no JSON payload")
    return json.loads(proc.stdout[start:])


def optimise(mandate_stem: str) -> dict[str, Any]:
    """Run the Optimiser against a materialised mandate. Returns its own JSON payload."""
    # `--json` is a GLOBAL flag and goes BEFORE the subcommand. Without it the CLI prints its human
    # report, and the first `{` in that text is not the start of a payload: the parse then fails with the
    # report's own disclaimer line as the reason, which reads like a refusal rather than a wrong call.
    cmd = [str(PCP_PY), "-m", "pcp.cli", "--json", "optimise", "--mandate", mandate_stem]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_CHILD_ENV,
                          timeout=OPTIMISER_TIMEOUT_S, cwd=str(PCP_HOME))
    start = proc.stdout.find("{")
    if proc.returncode != 0 or start < 0:
        raise AllocationUnavailable(_reason(proc.stderr or proc.stdout))
    return json.loads(proc.stdout[start:])


def _reason(text: str) -> str:
    """The last meaningful line of a traceback, which is the only part worth showing a reader."""
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


def _chf(x: float) -> str:
    """A franc figure in Swiss grouping. **Only the number is formatted, not the sentence around it.**
    The first version ran `.replace(",", " ")` over the whole string and turned "dem, was Haushalt" into
    "dem  was Haushalt": a thousands separator and a German comma are the same character.
    """
    return f"{x:,.0f}".replace(",", " ")


def for_household(quantities: dict, *, household_id: str) -> dict[str, Any]:
    """The allocation section of a gameplan, from the deterministic quantities.

    **The goal fed to the derivation is the one the mandate is FOR, and choosing it is a real decision.** The
    target is the capital the household's own gap implies, at the model's own withdrawal rate, and the horizon
    is the span to the reference age or to the household's own deadline. Where the gap is already covered by the
    flows at 65, there is no capital requirement to fund and the mandate has no level to derive: that is
    reported as such rather than as a mandate for a target of zero, which would ask the portfolio for nothing
    and then be read as a recommendation to hold cash.
    """
    rr = quantities["required_return"]
    b = quantities["balance"]
    cf = quantities["cash_flow"]
    goal = quantities.get("plan") or {}
    epsilon = float(goal.get("goal_epsilon") or 0.10) or 0.10
    # **The computed free cash flow, not the stated saving.** `app/gameplan` solves the required return at
    # the computed figure and records why: a household that states 30 000 while its income and outgoings free
    # nothing would otherwise be handed a plan funded by money it does not have. This function took the stated
    # figure, and on one live submission the two sections of the same report disagreed by a factor of nineteen
    # -- 17,50 % a year against 0,9 %, feasible, on a contribution of 30 000 against an income of 24 000.
    #
    # The stated figure travels with the result rather than being discarded, because the gap between the two
    # is itself a finding, and a reader comparing this section with the cash-flow table is entitled to see it.
    computed = float(cf.get("free") or 0.0)
    stated = float(cf.get("stated_saving") or 0.0)
    contribution = max(0.0, computed)
    horizon = rr["years"]
    target, basis = rr["target"], "gap"

    # **A household with no shortfall still needs an allocation, and refusing to derive one was wrong.**
    #
    # The first version of this function returned `no_capital_requirement` and stopped. That is defensible in
    # one sense -- a mandate for a target of zero asks the portfolio for nothing -- and useless in the sense
    # that matters: the money exists, it is invested in something today, and "you have no shortfall" is not an
    # answer to "where should this sit". A bridge to an early stop is a capital requirement even when the
    # pension at 65 is comfortable, and where there is no requirement at all the goal is to still hold the
    # capital at the end of the horizon.
    #
    # So the target is taken from the first of these that exists, and which one it was travels with the result:
    # the shortfall's capital, the bridge, or preservation of what is drawable today.
    if target <= 0:
        br = quantities.get("bridge") or {}
        if br.get("need", 0) > 0:
            target, basis = float(br["need"]), "bridge"
            horizon = max(1.0, float(br.get("years") or 1.0)
                          + max(0.0, float(br.get("stop_age") or 0.0)
                                - float(quantities.get("age") or 0.0)))
        elif b["drawable"] > 0:
            target, basis = float(b["drawable"]), "preservation"
        else:
            return {"state": "no_capital_and_nothing_drawable",
                    "why": ("Es gibt keinen Kapitalbedarf und kein entnahmefähiges Vermögen, aus dem "
                            "ein Mandat abgeleitet werden könnte. Eine Allokation ohne Kapital ist "
                            "keine Aussage über die Anlage.")}

    try:
        derived = derive(
            household_id=household_id,
            W_L=b["liquid"], W_R=b["property_total"], D=b["debt"],
            E=None, N=None, H=quantities.get("health", {}).get("H0"),
            goal_kind="fi", target=target, horizon_years=horizon,
            epsilon=epsilon, annual_contribution=contribution,
        )
    except (AllocationUnavailable, subprocess.SubprocessError, OSError) as exc:
        return {"state": "unavailable", "why": str(exc)}

    out: dict[str, Any] = {"state": "mandate_only", "target": target, "target_basis": basis,
                           "target_basis_label": _BASIS_LABEL[basis], "horizon_years": horizon,
                           "annual_contribution": contribution,
                           "contribution_basis": "computed",
                           "contribution_stated": stated,
                           "contribution_computed": computed,
                           "contribution_note": (
                               f"Finanziert wird mit {_chf(contribution)} pro Jahr — dem, was Haushalt und "
                               f"Steuern rechnerisch frei lassen. Angegeben waren {_chf(stated)}. Die "
                               f"Differenz ist ein Befund und keine Eingabe: eine Allokation auf die "
                               f"höhere Zahl gerechnet sieht besser aus und beruht auf Mitteln, die in "
                               f"dieser Rechnung nicht vorkommen."
                               if abs(stated - computed) > 1.0 else ""),
                           **derived}
    try:
        payload = optimise(derived["mandate_stem"])
    except (AllocationUnavailable, subprocess.SubprocessError, OSError) as exc:
        out["optimiser_error"] = str(exc)
        return out

    out["state"] = "optimised"
    rows = payload.get("allocation", [])
    out["allocation"] = [{"id": r.get("bb_id"), "name": r.get("name"), "role": r.get("role"),
                          "asset_class": r.get("asset_class"), "currency": r.get("currency"),
                          "liquidity": r.get("liquidity"), "region": r.get("region_geo"),
                          "weight": float(r.get("weight") or 0.0)}
                         for r in sorted(rows, key=lambda r: -float(r.get("weight") or 0.0))]
    out["role_allocation"] = payload.get("role_allocation") or {}
    header = payload.get("header") or {}
    diag = payload.get("diagnostics") or {}
    # **Weight leverage is the number that keeps this section honest**, and it is reported rather than buried:
    # it is the fraction of the objective's level the weights actually control. Measured between 1 and 4 % on
    # real mandates, so the structure comes from the bounds and the curve fit only breaks ties.
    out["fit"] = {
        "weight_leverage": header.get("weight_leverage", diag.get("weight_leverage")),
        "objective": payload.get("objective_value"),
        "objective_floor": header.get("objective_floor", diag.get("objective_floor")),
        "conditions_met": header.get("conditions_met") or (payload.get("solver") or {}).get(
            "conditions_met"),
        "solver": (payload.get("solver") or {}).get("method"),
        "universe_size": diag.get("universe_size"),
    }
    out["optimiser_notes"] = list(payload.get("notes") or [])
    # What received nothing is as much a part of the answer as what received something: in one case the only
    # globally diversifying block was excluded and lowering the currency floor changed nothing. The threshold
    # is 5 basis points, because the solver returns exact zeros as tiny negatives.
    got = {r["id"] for r in out["allocation"] if r["weight"] > 0.0005}
    out["excluded"] = [blk for blk in derived.get("blocks", []) if blk.get("id") not in got]
    out["provenance"] = (
        f"Regime {derived.get('regime_id')}, ReturnSet vom {derived.get('returnset_as_of')}. "
        "Jede vorwärtsgerichtete Zahl erbt diesen Stand."
    )
    out["proxy_note"] = (
        "Das Mandat ruht auf der rollengebundenen Näherung der erwarteten Rendite. Diese Näherung ist "
        "eine Obergrenze und keine Prognose: der Fixpunkt zwischen Mandat und Allokation ist hier nicht "
        "iteriert."
    )
    out["constraint_note"] = (
        "Die Allokation ist schrankengetrieben. Der Optimierer weist aus, welchen Anteil des Zielniveaus "
        "die Gewichte tatsächlich beeinflussen; auf echten Mandaten sind das gemessen 1 bis 4 %. Die "
        "Struktur kommt damit aus den Schranken, und die Kurvenanpassung entscheidet nur Gleichstände."
    )
    return out


def main(argv: list[str] | None = None) -> int:
    """`python desktop/allocation.py --in quantities.json --id onb-xxxx`. For checking the seam by hand."""
    import argparse
    ap = argparse.ArgumentParser(description="Derive and optimise one household's allocation.")
    ap.add_argument("--in", dest="infile", required=True, help="gameplan quantities JSON")
    ap.add_argument("--id", dest="household_id", required=True)
    args = ap.parse_args(argv)
    q = json.loads(Path(args.infile).read_text(encoding="utf-8-sig"))
    sys.stdout.write(json.dumps(for_household(q, household_id=args.household_id),
                                ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
