"""S-02, the role grid. The gate for phase 2: useful at n=1, and no completion meter anywhere."""

from __future__ import annotations

import json

import pytest

from eigentlich.models import CAPITAL_TYPES, Position, ROLES
from eigentlich.services import mutate_plan, role_grid


@pytest.fixture()
def one_position(session, member):
    """Principle 3: design for one position, not four."""
    with mutate_plan(
        session,
        member_id=member.id,
        question="Record employment as a human-capital income position?",
        choice="Yes, at 92,000 CHF per year",
    ) as decision:
        position = Position(
            member_id=member.id,
            role="income",
            capital_type="human",
            label="Anstellung",
            magnitude=92000.0,
            magnitude_unit="chf_per_year",
            time_basis="42h/Woche",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    return position


def test_role_grid_renders_with_one_position(session, member, one_position):
    """R-110. The grid must render and be useful at n=1."""
    grid = role_grid(session, member_id=member.id)

    assert len(grid["cells"]) == len(ROLES) * len(CAPITAL_TYPES) == 8
    filled = [c for c in grid["cells"] if c["positions"]]
    assert len(filled) == 1
    assert filled[0]["positions"][0]["label"] == "Anstellung"


def test_grid_renders_with_no_positions_at_all(session, member):
    """A member who has just registered still gets eight cells that say something."""
    grid = role_grid(session, member_id=member.id)
    assert len(grid["cells"]) == 8
    assert all(c["prompt"] for c in grid["cells"]), "R-110: an empty cell states what would go there"
    assert not any(c["positions"] for c in grid["cells"])


def test_every_empty_cell_states_what_would_go_there(session, member, one_position):
    """R-110. Not "no data" — the role's own definition."""
    grid = role_grid(session, member_id=member.id)
    for cell in grid["cells"]:
        assert cell["prompt"], f"{cell['role']}/{cell['capital_type']} has no prompt"
        assert "no data" not in cell["prompt"].lower()
        assert cell["definition"], "R-111: each role shows its definition on demand"


def test_adding_a_position_is_reachable_from_every_cell(session, member):
    """R-112. In one action, from any empty cell."""
    grid = role_grid(session, member_id=member.id)
    for cell in grid["cells"]:
        action = cell["add_action"]
        assert action["href"] == "/api/positions"
        assert action["role"] == cell["role"]
        assert action["capital_type"] == cell["capital_type"]


#: R-113 and R-006. A payload carrying these is a completion meter that has not been drawn yet.
FORBIDDEN_KEYS = (
    "filled",
    "filled_count",
    "total",
    "completed",
    "completion",
    "progress",
    "percent",
    "percentage",
    "ratio",
    "remaining",
    "score",
    "of_eight",
)


def _all_keys(node) -> set[str]:
    if isinstance(node, dict):
        keys = set(node.keys())
        for v in node.values():
            keys |= _all_keys(v)
        return keys
    if isinstance(node, list):
        keys: set[str] = set()
        for v in node:
            keys |= _all_keys(v)
        return keys
    return set()


def test_grid_payload_carries_no_completion_meter(session, member, one_position):
    """R-113. No completion meter, no "3 of 8 filled", no progress ring.

    Checked on the payload rather than on the rendered screen, because the client cannot draw a meter it
    was never given the numbers for. The absence in the payload IS the enforcement — this is the constraint
    the previous client failed, with an altitude ring reading "n of m answered" on its landing screen.
    """
    grid = role_grid(session, member_id=member.id)
    present = sorted(_all_keys(grid) & set(FORBIDDEN_KEYS))
    assert not present, f"R-113: the grid payload carries completion-meter fields: {present}"


def test_grid_payload_states_no_target_number_of_positions(session, member, one_position):
    """No element may imply that eight positions is the goal."""
    blob = json.dumps(role_grid(session, member_id=member.id), ensure_ascii=False).lower()
    for phrase in ("of 8", "of eight", "von 8", "von acht", "8 cells", "complete your"):
        assert phrase not in blob, f"R-113: payload implies a target: {phrase!r}"


def test_both_kinds_of_capital_are_always_present(session, member, one_position):
    """R-114 / principle 9. A summary that accepts only financial inputs cannot be built from this."""
    grid = role_grid(session, member_id=member.id)
    for role_key in ROLES:
        types = {c["capital_type"] for c in grid["cells"] if c["role"] == role_key}
        assert types == set(CAPITAL_TYPES)


def test_grid_is_german_by_default(session, member, one_position):
    """A12. de-CH is the default, so the default payload is German."""
    grid = role_grid(session, member_id=member.id)
    protection = next(c for c in grid["cells"] if c["role"] == "protection")
    assert protection["display"] == "Absicherung"


def test_inactive_positions_stay_in_the_grid(session, member, one_position):
    """R-122. Inactive positions remain in history; the grid does not silently drop them."""
    from eigentlich.services import mutate_plan as mutate

    with mutate(session, member_id=member.id, question="Employment ended?", choice="Mark inactive") as d:
        one_position.active = False
        d.linked_positions.append(one_position)
    session.commit()

    grid = role_grid(session, member_id=member.id)
    filled = [c for c in grid["cells"] if c["positions"]]
    assert len(filled) == 1
    assert filled[0]["positions"][0]["active"] is False


def test_correlation_tags_are_returned_but_not_interpreted(session, member):
    """R-021 / D-02. Store the tags; do not ship the inference."""
    with mutate_plan(session, member_id=member.id, question="Add?", choice="Yes") as d:
        p = Position(
            member_id=member.id,
            role="growth",
            capital_type="human",
            label="MBA",
            tags={"skill": "finance", "sector": "banking"},
        )
        session.add(p)
        d.linked_positions.append(p)
    session.commit()

    grid = role_grid(session, member_id=member.id)
    cell = next(c for c in grid["cells"] if c["role"] == "growth" and c["capital_type"] == "human")
    assert cell["positions"][0]["tags"] == {"skill": "finance", "sector": "banking"}
    # No derived field: nothing in the payload says two positions are "really one".
    assert "correlated_with" not in json.dumps(grid)
    assert "duplicate_of" not in json.dumps(grid)


# ============================================================ R-031 — the band the edit form has to show


def test_the_grid_shows_a_positions_liquidity_band(session, member, one_position):
    """R-031. The band a member has stated comes back, and null comes back as null.

    **Why this test exists.** `GET /api/positions` carried every other revisable field and not `liquidity`,
    so the position edit form could not show a member which band their own position holds and had to render
    an additive "leave unchanged" selector instead. At the same time `services/goals.py` reports
    `liquidity_not_stated` about that position under R-031 — the product naming a gap and hiding the field
    that fills it.

    The unset case is asserted first and deliberately: `None` and `"immediate"` are different facts, and a
    payload that turned an unanswered field into a default would have satisfied a check for the key alone.
    """
    from eigentlich.models import LIQUIDITY

    def band_of(grid):
        filled = [c for c in grid["cells"] if c["positions"]]
        return filled[0]["positions"][0]["liquidity"]

    assert band_of(role_grid(session, member_id=member.id)) is None, (
        "an unanswered band must read as unanswered, not as a default"
    )

    for band in LIQUIDITY:
        with mutate_plan(session, member_id=member.id, question="Wie schnell verfügbar?",
                         choice=band) as decision:
            one_position.liquidity = band
            decision.linked_positions.append(one_position)
        session.commit()
        assert band_of(role_grid(session, member_id=member.id)) == band


def test_every_field_the_edit_route_can_change_is_readable_from_the_grid(session, member, one_position):
    """The rule `liquidity` was missing from, stated as a rule rather than as one more field name.

    A member cannot be shown a form for a field they cannot read the current value of. So every entry in
    `POSITION_REVISABLE_FIELDS` — the list `PATCH /api/positions/{id}` derives its accepted fields from —
    has to appear in the grid payload, and this derives the expectation from that list so the next field
    added to it is covered without anyone remembering this test.

    `role` and `capital_type` are the two exceptions and they are named: they are properties of the *cell*
    a position sits in, carried once per cell rather than repeated on every position in it, and a client
    rendering a position necessarily knows which cell it drew.

    **Planted violation:** removed `"liquidity"` from `_position_payload` in `services/grid.py`. This test
    failed naming that field. Restored. Planted a second time by removing `"time_basis"` instead, to check
    the test is not keyed to one name — it failed naming `time_basis`. Restored.
    """
    from eigentlich.services.plan import POSITION_REVISABLE_FIELDS

    on_the_cell = {"role", "capital_type"}
    grid = role_grid(session, member_id=member.id)
    payload = next(c for c in grid["cells"] if c["positions"])["positions"][0]

    missing = [
        field
        for field in POSITION_REVISABLE_FIELDS
        if field not in on_the_cell and field not in payload
    ]
    assert not missing, (
        f"PATCH /api/positions/{{id}} can change {missing} and GET /api/positions does not report it. A "
        f"member cannot be shown a form for a field whose current value they cannot read — that is what "
        f"made the liquidity selector additive, and it is the defect this asserts against."
    )

    for field in on_the_cell:
        cell = next(c for c in grid["cells"] if c["positions"])
        assert field in cell, f"{field} is meant to be carried on the cell and is not there either"
