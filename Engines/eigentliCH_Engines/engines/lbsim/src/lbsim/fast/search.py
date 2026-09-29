"""The smallest change that makes a goal hold, searched rather than illustrated.

**What this replaces.** `app/paths` builds four named paths from a hand-written list. The three things they
vary -- education, Pensum, network -- are baked into a function signature, the levels are fixed at "today or
full" and "zero or the knee", and four of the eight combinations were chosen by hand. It illustrates. It does
not search, and it never touches the two things this household most needs varied: what it spends, and the goal
itself.

**Searching is affordable, and that is the whole payoff of setting the return to zero.** One path simulation
costs 0.5 ms -- measured, about 2 200 a second -- because at zero return the arithmetic is a loop and a
division rather than a solve. A grid of a few hundred combinations costs a fifth of a second. The expensive
instrument stays where it belongs, after this.

**Two frontiers, not one ranking, and that is a deliberate refusal.** Given a goal that does not hold, there
are two kinds of answer: change what you do, or change what you want. Ranking them against each other would
mean the machine deciding whether working more is better than wanting less, which is exactly the judgement it
must not make (G7). So it reports the cheapest change of each kind and lets the household choose:

    effort   the smallest set of moves in hours, education, network and spending that funds the goal
             as stated, on its own date, for its own amount
    goal     the smallest change to the goal's own date or amount that funds it at today's effort
    both     when neither alone is enough, the smallest combination that is

"Smallest" is counted in MOVES first and magnitude second, because a household reads one change as easier than
two regardless of size, and because a frontier ordered by francs alone would recommend a decade of extra work
over a two-year delay.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable

from ..model.params import Params
from . import paths as _paths

SCHEMA = "search@0.1.0"

#: A ceiling on the space, as a guard rather than as a working limit.
#:
#: **It used to truncate, and truncation produced a confident wrong answer.** Seven dimensions make 2 304
#: combinations; the cap was 2 000, and `product` varies the last dimension fastest, so the 304 dropped were
#: every combination with the largest goal reductions at the longest delays -- exactly where the answer for an
#: out-of-reach goal lives. The search reported "no way found" for a goal that a smaller amount at a later date
#: plainly funds.
#:
#: The scan now stops at the first hit per kind instead, so the whole space is reachable and most of it is
#: never evaluated. This bound only refuses a space that has grown past what a report should be searching, and
#: refusing is the point: a partial search that answers anyway is the failure it replaced.
MAX_COMBINATIONS = 20_000


@dataclass(frozen=True)
class Move:
    """One change from today, in one dimension.

    `effort` marks whether this is something the household DOES (hours, study, spending) or something it
    changes about what it WANTS (a goal's date or amount). The two are never traded against each other.
    """
    dimension: str
    label: str
    value: Any
    effort: bool
    #: Rough magnitude within its dimension, 0 for "no change". Used only to break ties between moves of the
    #: same count, never across dimensions -- a franc of spending and a year of delay are not comparable.
    size: float = 0.0

    @property
    def is_baseline(self) -> bool:
        return self.size == 0.0


def _pensum_values(sub: dict, raw: dict) -> list[Move]:
    """Pensum steps from today's up to full, skipping any that are not actually an increase."""
    now = _paths._pensum_now(raw)
    out = [Move("pensum", f"Pensum wie heute ({now:.0%})", now, True, 0.0)]
    for share in (0.6, 0.8, 1.0):
        if share > now + 0.05:
            out.append(Move("pensum", f"Pensum auf {share:.0%}", share, True, share - now))
    return out


def _learning_values(sub: dict, raw: dict) -> list[Move]:
    from .gameplan import education_hours
    hours = education_hours(raw) or 0.0
    out = [Move("learning", "ohne Weiterbildung", 0.0, True, 0.0)]
    if hours > 0:
        out.append(Move("learning", f"Weiterbildung, {hours:.0f} h/Woche", hours, True, hours))
    return out


def _network_values(sub: dict, raw: dict) -> list[Move]:
    knee = _paths.NETWORK_HOURS_AT_KNEE
    return [Move("network", "ohne Netzwerkarbeit", 0.0, True, 0.0),
            Move("network", f"Netzwerk, {knee:.0f} h/Woche", knee, True, knee)]


def _spending_values(sub: dict, raw: dict) -> list[Move]:
    """Spending cuts, as shares of today's. The report already prices a ten per cent cut as a lever; this
    lets it be part of a plan rather than a number in a list."""
    out = [Move("spending", "Ausgaben wie heute", 1.0, True, 0.0)]
    for cut in (0.10, 0.20):
        out.append(Move("spending", f"Ausgaben {cut:.0%} tiefer", 1.0 - cut, True, cut))
    return out


def _stop_age_values(sub: dict, raw: dict, p: Params) -> list[Move]:
    """Working longer, up to the reference age and never past it."""
    from .gameplan import _stop_age
    stated = _stop_age(sub, p)
    # lbsim port: the draft formats a stop age nobody stated and raises, so its frontier exists only for a
    # household that named one (every other report carries `search.error`). A submission from `lbsim.adapter`
    # reads an unstated stop age as the reference age, as `paths._working_until` already does. A draft
    # submission keeps the draft's behaviour (golden layer A).
    if stated is None and (sub.get("lbsim") or {}).get("unstated_stop_age_is_reference_age"):
        stated = float(p.ahv_age)
    out = [Move("stop_age", f"Erwerbsende mit {stated:.0f}", stated, True, 0.0)]
    for extra in (2.0, 5.0):
        later = min(stated + extra, p.ahv_age)
        if later > stated + 0.5:
            out.append(Move("stop_age", f"Erwerbsende mit {later:.0f}", later, True, extra))
    return out


def _goal_year_values(goal: dict) -> list[Move]:
    year = int(goal["target_year"])
    out = [Move("goal_year", f"Zieljahr {year}", 0, False, 0.0)]
    for delay in (3, 5, 10):
        out.append(Move("goal_year", f"Zieljahr {year + delay}", delay, False, float(delay)))
    return out


def _goal_amount_values(goal: dict) -> list[Move]:
    out = [Move("goal_amount", "Betrag wie genannt", 1.0, False, 0.0)]
    for share in (0.75, 0.5, 0.25):
        out.append(Move("goal_amount", f"Betrag auf {share:.0%}", share, False, 1.0 - share))
    return out


def _matching(candidate: dict, goal: dict) -> bool:
    """Whether this submission goal is the one the search is varying.

    Matched on kind, description and year together: a household may state two goals of the same kind, and
    replacing the wrong one would move a target the reader was never asked about.
    """
    return (str(candidate.get("kind")) == str(goal.get("kind"))
            and str(candidate.get("description") or "") == str(goal.get("description") or "")
            and candidate.get("target_year") == goal.get("target_year"))


def _apply(sub: dict, p: Params, combo: dict[str, Move], goal: dict | None = None) -> tuple[dict, float]:
    """A submission and a stop age reflecting these moves, including the change to the goal itself.

    **The goal variant has to go through the submission, not around it.** `paths.simulate` reads the goals off
    the household, so a later date or a smaller amount held in a local variable never reaches the arithmetic:
    the search would faithfully report that moving the goal changes nothing.

    Copied rather than mutated. A search that edits the household in place leaves the report describing
    whichever combination happened to be tried last.
    """
    raw = dict(sub.get("raw") or {})
    spend = raw.get("spend_now")
    if combo["spending"].value != 1.0 and isinstance(spend, (int, float)):
        raw["spend_now"] = float(spend) * float(combo["spending"].value)
    out = {**sub, "raw": raw}
    if goal is not None:
        wanted = _goal_variant(goal, combo)
        out["goals"] = [wanted if _matching(g, goal) else g for g in (sub.get("goals") or [])]
    return out, float(combo["stop_age"].value)


def _path_for(sub: dict, p: Params, combo: dict[str, Move]) -> dict:
    """One income path from the moves, through the same builder the four presets use."""
    return _paths.build_path(sub, p, code="search", name="gesucht",
                             learning=float(combo["learning"].value),
                             network_hours=float(combo["network"].value),
                             pensum_after=float(combo["pensum"].value))


def _goal_variant(goal: dict, combo: dict[str, Move]) -> dict:
    """The goal as these moves leave it: possibly later, possibly smaller.

    A flow goal's `amount_chf` is a spend per year rather than a capital sum, so scaling it means asking to
    live on less. That is a real choice and a different one from buying a smaller house; both are goal moves,
    and the label on the move says which was meant.
    """
    out = dict(goal)
    delay = int(combo["goal_year"].value or 0)
    share = float(combo["goal_amount"].value or 1.0)
    if delay:
        out["target_year"] = int(goal["target_year"]) + delay
    if share != 1.0 and goal.get("amount_chf"):
        out["amount_chf"] = float(goal["amount_chf"]) * share
    return out


def _describe(combo: dict[str, Move]) -> list[str]:
    return [m.label for m in combo.values() if not m.is_baseline]


def _cost(combo: dict[str, Move]) -> tuple[int, float]:
    """Moves first, magnitude second. A household reads one change as easier than two, whatever their size."""
    changed = [m for m in combo.values() if not m.is_baseline]
    return len(changed), sum(m.size for m in changed)


def frontier(submission: dict, p: Params, *, rate: float = 0.0) -> dict[str, Any]:
    """For each goal, the cheapest way to fund it: by effort, by changing the goal, or by both.

    `rate` is the return the test is run at. Zero is the default and the honest baseline; a caller that wants
    to ask "and with my own expected return?" passes it and gets the same frontier under that assumption.
    """
    raw = submission.get("raw") or {}
    dims: dict[str, list[Move]] = {
        "pensum": _pensum_values(submission, raw),
        "learning": _learning_values(submission, raw),
        "network": _network_values(submission, raw),
        "spending": _spending_values(submission, raw),
        "stop_age": _stop_age_values(submission, raw, p),
    }
    goal_dims = ("goal_year", "goal_amount")

    from .gameplan import _stop_age  # noqa: PLC0415
    base_stop = _stop_age(submission, p)
    base_combo = {k: v[0] for k, v in dims.items()}
    base_run = _paths.simulate(submission, p, _paths.income_paths(submission, p)[0],
                               stop_age=base_stop, rates=(rate,))
    base_rows = {(str(r["kind"]), int(r["target_year"])): r for r in base_run["goals"]}

    # **The household's goals, not the simulation's rows.** A row carries the capital a goal implies and no
    # `amount_chf`; varying rows meant every "smaller amount" move was a silent no-op, and the goal then
    # vanished from the simulation for having no amount at all. See the module note.
    goals = [g for g in (submission.get("goals") or []) if g.get("target_year")]

    results = []
    truncated = False
    for goal in goals:
        row0 = base_rows.get((str(goal.get("kind")), int(goal["target_year"])))
        if row0 is None:
            # Deferred at intake, or a kind the arithmetic has no target for. `findings.goal_not_computed`
            # already names it; a frontier over a goal nobody can compute would be search without a subject.
            continue
        per_goal_dims = {**dims, "goal_year": _goal_year_values(goal),
                         "goal_amount": _goal_amount_values(goal)}
        keys = list(per_goal_dims)
        space = 1
        for k in keys:
            space *= len(per_goal_dims[k])
        if space > MAX_COMBINATIONS:
            truncated = True
            results.append({
                "kind": goal["kind"], "description": goal.get("description") or goal["kind"],
                "target_year": int(goal["target_year"]), "target": row0["target"],
                "holds_today": bool(row0.get("reachable")),
                "cheapest_effort": None, "cheapest_goal_change": None, "cheapest_combination": None,
                "combinations_tried": 0,
                "refused": f"Der Suchraum umfasst {space} Kombinationen und damit mehr, als hier "
                           f"vollständig geprüft werden. Eine teilweise Suche würde eine Antwort geben, "
                           f"die keine ist.",
            })
            continue

        # **Sorted by cost, scanned until each kind has its first hit.** Under this ordering the first hit IS
        # the cheapest, so the rest of the space needs no evaluation -- which makes the complete search faster
        # than the truncated one it replaces.
        combos = sorted((dict(zip(keys, values))
                         for values in product(*(per_goal_dims[k] for k in keys))),
                        key=_cost)
        best: dict[str, Any] = {"effort": None, "goal": None, "both": None}
        tried = 0
        # Nothing to find: a frontier printed under a goal that is already funded reads as a demand.
        combos = [] if row0.get("reachable") else combos
        for combo in combos:
            if all(best[k] is not None for k in best):
                break
            changed = [m for m in combo.values() if not m.is_baseline]
            if not changed:
                continue
            kind = ("both" if any(m.effort for m in changed) and any(not m.effort for m in changed)
                    else "effort" if any(m.effort for m in changed) else "goal")
            if best[kind] is not None:
                continue
            tried += 1
            ok, row = _holds(submission, p, combo, goal, rate=rate)
            if not ok:
                continue
            best[kind] = {
                "moves": _describe(combo), "cost": _cost(combo),
                "goal_year": row["target_year"], "target": row["target"],
                # From the column actually being tested. Reading `required_saving` here printed the
                # zero-return figure beside a verdict reached at 8 %.
                "required": row["required_by_rate"][f"{rate:.4f}"],
                "available": row["available_saving"],
            }

        results.append({
            "kind": goal["kind"], "description": goal.get("description") or goal["kind"],
            "target_year": int(goal["target_year"]), "target": row0["target"],
            "holds_today": bool(row0.get("reachable")),
            "required_today": row0["required_by_rate"][f"{rate:.4f}"],
            "available_today": row0["available_saving"],
            "cheapest_effort": best["effort"], "cheapest_goal_change": best["goal"],
            "cheapest_combination": best["both"],
            "combinations_tried": tried,
            "combinations_possible": space,
        })

    return {"schema": SCHEMA, "rate": rate, "goals": results, "truncated": truncated,
            "dimensions": {k: [m.label for m in v] for k, v in
                           {**dims,
                            "goal_year": _goal_year_values(goals[0]) if goals else [],
                            "goal_amount": _goal_amount_values(goals[0]) if goals else []}.items()}}


def _holds(submission: dict, p: Params, combo: dict[str, Move], goal: dict, *,
           rate: float) -> tuple[bool, dict]:
    """Whether this goal, as these moves leave it, is funded by what these moves free."""
    sub, stop = _apply(submission, p, combo, goal)
    path = _path_for(sub, p, combo)
    variant = _goal_variant(goal, combo)
    run = _paths.simulate(sub, p, path, stop_age=stop, rates=(rate,))
    row = next((r for r in run["goals"]
                if r["kind"] == variant["kind"] and r["target_year"] == variant["target_year"]), None)
    if row is None:
        return False, {}
    return bool(row["available_saving"] >= row["required_by_rate"][f"{rate:.4f}"]), row
