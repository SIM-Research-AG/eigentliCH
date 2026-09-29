"""Turn front-end form inputs into a Case, and back — plus saved-user storage.

This is what makes the app a tool rather than a viewer: any set of inputs becomes
a `Case` the engine runs, the five book lives are just editable presets, and the
user's own people persist to a JSON file next to the project.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..cases import FIVE_LIVES, Case
from ..goals.spec import GoalSpec
from ..model.state import State

USERS_FILE = Path(__file__).resolve().parents[2] / "lbs_users.json"

# Goal parameter fields exposed in the form, per kind.
GOAL_FIELDS = {
    "fi": ["G", "swr", "h_res"],
    "home": ["price"],
    "company": ["B_buffer", "N_min", "E_min"],
    "retirement": ["G_ret", "years_in_retirement"],
}


def _spec_from(gd: dict) -> GoalSpec:
    kind = gd["kind"]
    conf = float(gd["confidence"])
    src = gd.get("params", {})
    params = {k: float(src[k]) for k in GOAL_FIELDS[kind] if k in src and src[k] is not None}
    return GoalSpec(kind=kind, horizon_years=float(gd["horizon"]),
                    epsilon=max(0.01, 1.0 - conf), params=params)


def _goal_to_dict(g: GoalSpec) -> dict:
    return {"kind": g.kind, "horizon": g.horizon_years,
            "confidence": round(1.0 - g.epsilon, 2),
            "params": {k: g.params.get(k) for k in GOAL_FIELDS[g.kind]}}


def case_from_input(d: dict) -> Case:
    """Build a Case from a form-input dict. `goals` is a list; the first is primary."""
    age = float(d["age"])
    # `age=age` reaches the STATE, not just the label. Until 4 August 2026 it was passed only to `Case.age` and
    # the persona string while `State.individual` took its 40.0 default, so a user who typed 60 was modelled at
    # 40 — every age-dependent term (AHV, the pension gates, 3a availability, the post-55 earning decline) read
    # the wrong age while the screen showed the right one. See `Case.age` and M76.
    st = State.individual(
        W_L=float(d["W_L"]), W_R=float(d["W_R"]), D=float(d["D"]),
        E=float(d["E"]), N=float(d["N"]), H=float(d["H"]), age=age,
    )
    specs = [_spec_from(g) for g in d.get("goals", [])]
    if not specs:
        raise ValueError("at least one goal is required")
    return Case(name=d.get("name", "Custom"), persona=f"age {age:.0f} · custom input",
                x0=st, goal=specs[0], confidence=1.0 - specs[0].epsilon,
                extra_goals=specs[1:], calibrated=bool(d.get("calibrated", False)))


def to_input(case: Case) -> dict:
    """Reverse: a Case → a form-input dict (used to load presets and saved users)."""
    w = case.x0.wealth
    person = case.x0.person
    return {
        "name": case.name, "age": case.age,
        "W_L": w.W_L, "W_R": w.W_R, "D": w.D,
        "E": round(person.E.aggregate(), 3), "N": round(person.N, 3), "H": round(person.H, 3),
        "calibrated": case.calibrated,
        "goals": [_goal_to_dict(g) for g in case.goals],
    }


def presets() -> list[dict]:
    """The five book lives as editable form inputs."""
    return [to_input(c) for c in FIVE_LIVES]


def load_users() -> list[dict]:
    if not USERS_FILE.exists():
        return []
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_user(d: dict) -> list[dict]:
    """Upsert a user by name; returns the full list."""
    users = [u for u in load_users() if u.get("name") != d.get("name")]
    users.append(d)
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    return users


def delete_user(name: str) -> list[dict]:
    users = [u for u in load_users() if u.get("name") != name]
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    return users
