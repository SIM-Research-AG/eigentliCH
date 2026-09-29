"""What the balance sheet is missing, in terms a client understands (owner feedback 29.09.2026, EIG-49).

lbs names each gap by a section (``property.<goal id>``, ``pensions.<person id>``, ``totals``, ...) and an input
(``occupancy``, ``<position id>.vessel``, a reason key such as ``the_goal_names_no_amount``), in English. None of
that reaches the client. ``describe`` turns each gap into

* ``key``: the gap's kind without ids (``property.the_goal_does_not_say_whether_the_member_will_live_in_it``),
  which the browser app turns into a sentence in the client's language (``gap.<key>`` in ``client/app/i18n.js``);
* ``name``: the object it is about, from the store (the goal's name, the position's label, the person's label);
* ``action``: where the client can supply it (``plan``, ``onboarding``, ``intake``), or None;
* ``group``: ``you`` (the client can supply it) or ``us`` (a published table, another model, a figure nobody has
  published yet: nothing for the client to do).

``KNOWN`` lists every key lbs can emit (read from ``engines/lbs/src/lbs/engine.py`` on 29.09.2026; a test reads
that file again and fails on a key missing here or in the i18n table). A key lbs adds later still reads: the
browser falls back to a sentence for its kind (``gapkind.<kind>``), never the key.
"""

from __future__ import annotations

from typing import Any, Optional

#: key -> where the client can supply it (None: nothing the client can do).
KNOWN: dict[str, Optional[str]] = {
    # household
    "household.household": "plan",
    "household.civil_status": "onboarding",
    "household.composition_as_of": "plan",
    # totals
    "totals.household_income": "plan",
    "totals.liabilities": "plan",
    "totals.assets": "plan",
    "totals.vessel": "plan",
    "totals.drawable": "plan",
    # human capital, per person
    "human_capital.E": "onboarding",
    "human_capital.N": "onboarding",
    "human_capital.H": "onboarding",
    "human_capital.earning_power": None,
    # pensions, per person
    "pensions.ahv": None,
    "pensions.mdje": "plan",
    "pensions.bvg": None,
    "pensions.age": None,
    "pensions.gross_income": "plan",
    "pensions.pillar_2_balance": "plan",
    # a property goal
    "property.vessel": "plan",
    "property.property-funding": None,
    "property.occupancy": "plan",
    "property.the_goal_names_no_amount": "plan",
    "property.the_goal_does_not_say_whether_the_member_will_live_in_it": "plan",
    "property.no_position_is_linked_to_this_goal": "plan",
    "property.a_funding_position_states_no_vessel": "plan",
    "property.rental_income_is_not_modelled_for_a_let_property": None,
    "property.capital_type": "plan",
    "property.no_income_is_recorded_for_the_household": "plan",
    "property.the_household_composition_is_past_its_validity_horizon": "plan",
    # a retirement goal
    "retirement.no_income_is_recorded_for_the_household": "plan",
    "retirement.the_members_age_is_not_recorded": None,
    "retirement.the_goal_names_no_yearly_amount": "plan",
    "retirement.the_ahv_table_is_not_approved": None,
    "retirement.the_pension_projection_record_is_not_approved": None,
    "retirement.the_household_composition_is_past_its_validity_horizon": "plan",
    # the risk profile
    "risk_profile.horizon_years": "intake",
    "risk_profile.vessel": "plan",
    "risk_profile.risk-profile": None,
    "risk_profile.profile": "intake",
    # the mandate proposal
    "mandate_proposal.mandate.goal_id": "plan",
    "mandate_proposal.target_amount": "plan",
    "mandate_proposal.property-funding": None,
    "mandate_proposal.target_capital": None,
    "mandate_proposal.target_date": "plan",
    "mandate_proposal.annual_contribution": "onboarding",
    "mandate_proposal.contribution_share": "plan",
    "mandate_proposal.required_return": "plan",
}

#: Where a gap about the partner (a person other than ``p1``) is supplied: the intake's partner section
#: (EIG-53), where the client's own answers are in the first conversation or come from the client record.
PARTNER_ACTIONS: dict[str, str] = {
    "human_capital.E": "intake",
    "human_capital.N": "intake",
    "human_capital.H": "intake",
    "pensions.age": "intake",
}

#: Gap kinds with nothing for the client to do.
NOT_YOURS = ("record_not_approved", "owned_by_another_engine", "needs_an_unpublished_assumption")


def key_of(section: str, input_: str, ids: set[str]) -> str:
    """The gap's kind: the section's first part and the input with a leading id taken off."""
    head = section.split(".", 1)[0]
    first, _, rest = input_.partition(".")
    if rest and first in ids:
        input_ = rest
    return f"{head}.{input_}"


def describe(gaps: list[dict[str, Any]], *, goals: dict[str, str], positions: dict[str, str],
             persons: dict[str, str], mandate_goal: Optional[str] = None) -> list[dict[str, Any]]:
    """Each gap as ``{key, kind, name, action, group}``, in lbs's order, one line per distinct key and name.
    ``goals``, ``positions``, ``persons`` map ids to the names the client gave them."""
    ids = set(goals) | set(positions) | set(persons)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for g in gaps:
        section, input_ = str(g.get("section") or ""), str(g.get("input") or "")
        key = key_of(section, input_, ids)
        _, _, sid = section.partition(".")
        first = input_.partition(".")[0]
        name = goals.get(sid) or persons.get(sid) or positions.get(first) or persons.get(first)
        if key.startswith("mandate_proposal.") and name is None and mandate_goal:
            name = goals.get(mandate_goal)
        if (key, name) in seen:
            continue
        seen.add((key, name))
        kind = str(g.get("kind") or "")
        action = KNOWN.get(key)
        person = sid if sid in persons else first if first in persons else None
        if person is not None and person != "p1" and key in PARTNER_ACTIONS:
            action = PARTNER_ACTIONS[key]
        group = "us" if kind in NOT_YOURS or (key in KNOWN and action is None) else "you"
        out.append({"key": key, "kind": kind, "name": name, "action": action if group == "you" else None,
                    "group": group, "known": key in KNOWN})
    return out
