"""Allocation by vessel for all ten members, read from the plan the product actually holds.

**By vessel and not by role**, and the choice is the finding. The four roles are the product's own frame
and they would split these ten into three near-identical bars — cash and collectibles both land on
Stabilisation, the 3a and the Pensionskasse both on Protection. The vessel is what a member recognises,
what the law treats differently, and what decides whether a franc can fund a purchase. Five categories in
one fixed order, never cycled.

Positions are read from `/api/positions`, which is the role grid the member sees — so the bars are the
plan and not the submission.
"""
import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Where `tools/run_cases.py` leaves what the running application answered. Regenerate that first: this
#: reads the plan as the product serves it, not the submissions, so it needs a run behind it.
CASES_FILE = Path(
    os.environ.get("ANDERSCH_CASES")
    or ROOT / "reports" / "cases.json"
)
if not CASES_FILE.exists():
    raise SystemExit(
        f"no case capture at {CASES_FILE}. Run tools/run_cases.py against a live server first, or point "
        f"ANDERSCH_CASES at its output."
    )
CASES = json.loads(io.open(CASES_FILE, encoding="utf-8").read())

#: Fixed order. Slots 1-5 of the validated categorical palette, assigned once and never rotated: a member
#: with no securities leaves slot 2 empty rather than shifting everything left.
VESSELS = [
    ("cash", "Bargeld und Kontoguthaben", "Konto"),
    ("securities", "Wertschriften", "Wertschriften"),
    ("collectibles", "Sammlungen, Kunst und Fahrzeuge", "Sammlungen"),
    ("pillar3a", "Säule 3a", "Säule 3a"),
    ("pillar2", "Pensionskasse", "Pensionskasse"),
]
BY_LABEL = {label: key for key, label, _ in VESSELS}

#: Which vessels may be drawn for a property the member lives in. The other two may not be drawn for a
#: holiday home or a let property at all — `client/content/property-funding.json`.
PENSION = {"pillar3a", "pillar2"}

out = {}
for person, record in CASES.items():
    name = record["session"]["display_name"]
    cells = record["positions"]["body"].get("cells", [])

    amounts = {key: 0 for key, _, _ in VESSELS}
    unmatched = []
    income = 0
    for cell in cells:
        for position in cell.get("positions", []):
            magnitude = position.get("magnitude")
            if magnitude is None:
                continue
            if position.get("magnitude_unit") == "chf_per_year":
                income += magnitude
                continue
            if position.get("magnitude_unit") != "chf":
                continue
            key = BY_LABEL.get(position.get("label"))
            if key is None:
                unmatched.append((position.get("label"), magnitude))
                continue
            amounts[key] += magnitude

    total = sum(amounts.values())
    out[person] = {
        "name": name,
        "amounts": amounts,
        "total": total,
        "income": income,
        "unmatched": unmatched,
        # What could go toward a deposit on a home they live in, and what could not on anything else.
        "hard": sum(v for k, v in amounts.items() if k not in PENSION),
        "pension": sum(v for k, v in amounts.items() if k in PENSION),
    }

io.open(ROOT / "reports" / "allocation.json", "w", encoding="utf-8", newline="\n").write(
    json.dumps(out, ensure_ascii=False, indent=1)
)


def m(x):
    return f"{x:,.0f}".replace(",", "’")


print(f"{'member':11} " + " ".join(f"{label:>11}" for _, _, label in VESSELS)
      + f" {'TOTAL':>11} {'income':>9}")
for person, d in out.items():
    row = " ".join(f"{m(d['amounts'][k]):>11}" for k, _, _ in VESSELS)
    print(f"{d['name'][:11]:11} {row} {m(d['total']):>11} {m(d['income']):>9}")
    if d["unmatched"]:
        print(f"            UNMATCHED: {d['unmatched']}")
print()
print(f"{'member':11} {'hard':>11} {'pension':>11}  pension share of the total")
for person, d in out.items():
    share = d["pension"] / d["total"] if d["total"] else 0
    print(f"{d['name'][:11]:11} {m(d['hard']):>11} {m(d['pension']):>11}  {share:6.0%}")
