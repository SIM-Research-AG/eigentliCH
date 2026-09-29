"""The constraint tests from build-spec §11. These fail the build; they do not warn.

Phase 1's gate is C-04, C-06, C-07 and C-09. The others in §11 are written where the spine already carries
them (R-040, R-100, R-030) and are marked `xfail` where the phase that implements them has not run yet, so
the list is honest about what is checked rather than quietly short.
"""

from __future__ import annotations

import ast
import contextlib
import json
import io
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from eigentlich import log_filter
from eigentlich.db import PlanMutationWithoutDecision
from eigentlich.log_filter import REDACTION, TopClassRedactingFilter
from eigentlich.models import (
    ActionItem,
    AssumptionSet,
    DataClass,
    Decision,
    DecisionImmutable,
    Goal,
    Position,
    TOP_CLASS,
    VaultItem,
    top_class_field_names,
    utcnow,
)
from eigentlich.services import BelowAgeFloor, mutate_plan, record_correction, register_member

MODEL_LAYER = Path(__file__).resolve().parent.parent / "eigentlich" / "models"


# ============================================================ C-07

#: Re-exported so `test_befund.py`, `test_learning.py` and `test_position_edit_api.py` keep importing it
#: from here. **The set itself now lives in `vocabulary.py`** with the rest of C-07's and R-143's words,
#: for the reason that module exists: four files read this set, and a set four files share belongs to none
#: of them. See `vocabulary.GAMIFICATION_IDENTIFIERS` for why membership is no longer how it is matched.
from vocabulary import GAMIFICATION_IDENTIFIERS  # noqa: E402,F401

#: The AST walk that reads it lives in `test_content.py` for the same reason. There were three near-copies
#: of it — here, in `test_befund.py`, in `test_learning.py` — and only the third looked at `ast.Constant`,
#: so a column named by a string literal was invisible to this one. See `c07_identifier_offences`.
from test_content import c07_identifier_offences  # noqa: E402


def test_no_gamification_identifiers_in_model_layer():
    """C-07: no gamification primitives, enforced by absence.

    **Scope, which is a recorded decision and not an oversight** (A6 in DECISIONS.md). This walks the member
    application's model layer only. It deliberately does not cover `andersCH/engines/score/` or the shared
    contracts layer: their `Score` is an analytical household-standing measure — decomposable, weights
    summing to one, labelled an editorial judgement — and renaming it was weighed and declined. A game
    mechanic entering *this* package is what the constraint is about.

    **This test reported 66 passed with a column called `points` in the schema.** The walk it used to carry
    read `ast.Name`, `ast.Attribute`, `ast.arg` and `ast.keyword` and never `ast.Constant`, so
    `tally: Mapped[int] = mapped_column("points", Integer, ...)` was a string it never looked at. It was
    also exact-set membership, so `grid_completion_score`, `points_earned`, `streak_days` and `xp_total`
    were four more primitives it could not see. Both holes are closed in `c07_identifier_offences`, which
    is now the only copy of this walk in the suite.

    **Planted:** `tally: Mapped[int] = mapped_column("points", Integer, nullable=True)` on `Position` in
    `models/plan.py`. Failed naming `plan.py:… 'points' ['points']`. Restored.
    """
    offences: list[str] = []
    for path in sorted(MODEL_LAYER.glob("*.py")):
        offences.extend(c07_identifier_offences(path))
    assert not offences, (
        "C-07 forbids gamification primitives in the member application's model layer. Found: "
        + "; ".join(offences)
    )


# ============================================================ C-04


def test_every_model_declares_a_data_class():
    """C-04: classification is a column on the model, not a convention."""
    from eigentlich.models import Base, Classified

    for mapper in Base.registry.mappers:
        model = mapper.class_
        assert issubclass(model, Classified), f"{model.__name__} stores rows without a data class"
        assert isinstance(model.__data_class__, DataClass)
        assert "data_class" in model.__table__.columns


def test_top_data_class_never_appears_in_logs(caplog):
    """C-04: a logging filter drops the top class by field name."""
    names = top_class_field_names()
    assert names, "no top-class fields found — the filter would be vacuously correct"
    assert "title" in names, "VaultItem.title is K3 and should be protected"

    logger = logging.getLogger("eigentlich.test.c04")
    logger.propagate = True
    filt = TopClassRedactingFilter()
    logger.addFilter(filt)

    secret = "Pensionskassenausweis Helvetia 2026"
    with caplog.at_level(logging.INFO, logger="eigentlich.test.c04"):
        logger.info("stored vault item title=%s for member", secret)
        logger.info("payload %s", {"title": secret, "kind": "policy"})
        logger.info("vault write", extra={"title": secret})

    logger.removeFilter(filt)

    joined = "\n".join(record.getMessage() for record in caplog.records)
    for record in caplog.records:
        joined += "\n" + str(getattr(record, "title", ""))

    assert secret not in joined, f"a K3 value reached a log line:\n{joined}"
    assert REDACTION in joined


def test_data_class_assignment_matches_the_spec():
    """A5: the build spec's §4 assignment is authoritative where it differs from the estate's."""
    from eigentlich.models import ActionItem, Member

    assert AssumptionSet.__data_class__ is DataClass.K0
    assert Member.__data_class__ is DataClass.K1
    assert Position.__data_class__ is DataClass.K2
    assert Goal.__data_class__ is DataClass.K2
    assert Decision.__data_class__ is DataClass.K2
    assert ActionItem.__data_class__ is DataClass.K2
    assert VaultItem.__data_class__ is DataClass.K3
    assert VaultItem.__data_class__ is TOP_CLASS


# ============================================================ what an action item still carries
#
# **C-06 was dropped on 20 September 2026 (A168).** Three tests stood here: an empty array, a single
# option, and an option with no consequence, each asserting `PreparedOptionsTooFew` from the `@validates`
# hook. The hook, the CHECK and the two A75 triggers are all gone, so all three now persist. The one
# below stays, because "a well-formed item can be written and read back" is still worth holding.
def test_action_item_with_two_prepared_options_persists(session, member):
    item = ActionItem(
        member_id=member.id,
        trigger_kind="policy_expiry",
        prepared_options=[
            {"label": "Renew", "consequence": "Cover continues at the current premium"},
            {"label": "Let it lapse", "consequence": "Cover ends on the expiry date"},
        ],
    )
    session.add(item)
    session.commit()
    assert item.id
# ============================================================ C-09


def test_plan_mutation_without_decision_raises(session, member):
    """C-09: a plan mutation without a linked decision is a constraint violation, not a warning."""
    session.add(
        Position(
            member_id=member.id,
            role="income",
            capital_type="human",
            label="Employment",
            magnitude=92000.0,
            magnitude_unit="chf_per_year",
        )
    )
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()


def test_goal_mutation_without_decision_raises(session, member):
    session.add(Goal(member_id=member.id, name="Courage money", template="courage_money"))
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()


def test_plan_mutation_with_decision_commits(session, member):
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
            label="Employment",
            magnitude=92000.0,
            magnitude_unit="chf_per_year",
            time_basis="42h/week",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    assert position.id
    assert decision.linked_position_ids == [position.id]


def test_decision_covering_a_different_object_does_not_launder_the_mutation(session, member):
    """A Decision in the flush is not enough — it has to cover the object that changed."""
    with mutate_plan(
        session, member_id=member.id, question="Add a savings goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="House deposit")
        session.add(goal)
        decision.linked_goals.append(goal)

        unrelated = Position(
            member_id=member.id, role="growth", capital_type="financial", label="Smuggled in"
        )
        session.add(unrelated)

    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()


# ============================================================ R-040 / R-162


def test_decision_correction_creates_new_record(session, member):
    with mutate_plan(session, member_id=member.id, question="Magnitude?", choice="92,000") as decision:
        position = Position(member_id=member.id, role="income", capital_type="human", label="Employment")
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    original_id = decision.id

    correction = record_correction(session, prior=decision, choice="96,400", reasoning="Payslip corrected")
    session.commit()

    assert correction.id != original_id
    assert correction.corrects_id == original_id
    assert decision.choice == "92,000", "the prior record must be untouched"


def test_decision_cannot_be_edited(session, member):
    with mutate_plan(session, member_id=member.id, question="Q", choice="A") as decision:
        goal = Goal(member_id=member.id, name="G")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    decision.choice = "something else"
    with pytest.raises(DecisionImmutable):
        session.commit()


def test_decision_cannot_be_deleted(session, member):
    with mutate_plan(session, member_id=member.id, question="Q", choice="A") as decision:
        goal = Goal(member_id=member.id, name="G")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    session.delete(decision)
    with pytest.raises(DecisionImmutable):
        session.commit()


def test_decisions_table_rejects_update_at_the_database(engine, session, member):
    """Past the ORM entirely — the trigger is what makes append-only a fact about the store."""
    from sqlalchemy import text

    with mutate_plan(session, member_id=member.id, question="Q", choice="A") as decision:
        goal = Goal(member_id=member.id, name="G")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE decisions SET choice='tampered' WHERE id=:i"), {"i": decision.id})


# ============================================================ C-10 (table only; phase 5 verifies the rest)


def test_curator_audit_table_rejects_update_and_delete(engine, session, member):
    from sqlalchemy import text

    from eigentlich.models import Curator, CuratorSession, CuratorSessionEvent

    # `CuratorSession.curator_id` is a foreign key since 31 August 2026 — A40 claimed it was one, A67
    # recorded that it was not. So the identified curator has to be a row before a session can name them,
    # and the placeholder string this test used to pass is now precisely what the column refuses.
    kuratorin = Curator(display_name="Eine Kuratorin", email="kuratorin@example.ch", role_label="Kurator")
    session.add(kuratorin)
    session.flush()

    cs = CuratorSession(member_id=member.id, curator_id=kuratorin.id, opened_from="know_panel")
    session.add(cs)
    session.flush()
    event = CuratorSessionEvent(session_id=cs.id, kind="opened", actor=kuratorin.id)
    session.add(event)
    session.commit()

    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE curator_session_events SET actor='x' WHERE id=:i"), {"i": event.id}
            )
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM curator_session_events WHERE id=:i"), {"i": event.id})


def test_the_curator_audit_refuses_the_orm_with_the_triggers_dropped(engine, session, member):
    """C-10's second enforcement point, and it did not exist until this test was written.

    **The finding.** `AuditImmutable` was defined in `models/curator.py` and raised nowhere in the
    codebase. With the triggers dropped — which R-231's erasure does, deliberately, every time it runs —
    rewriting a `CuratorSessionEvent` through the ORM *succeeded*, while the identical experiment on
    `decisions` was refused by `DecisionImmutable`. R-040 has a `before_flush` guard and a trigger; C-10
    had a trigger and an unused exception class, which reads exactly like a guard until somebody greps
    for the raise.

    **Dropping the triggers is the point of this test, not a shortcut.** With them installed, a refusal
    proves nothing about the ORM: the storage layer would have refused anyway, and that is what makes an
    unraised exception invisible. The window this opens is real — `services/erasure.py` runs inside it.

    **Planted:** commented out the `before_flush` listener in `models/curator.py`. `session.commit()`
    returned normally and the reload asserted `actor == 'tampered'`; this test failed on
    `DID NOT RAISE AuditImmutable`, and `test_curator_audit_table_rejects_update_and_delete` above stayed
    green throughout — the two halves demonstrably independent. Restored.
    """
    from sqlalchemy import text

    from eigentlich.models import AuditImmutable, Curator, CuratorSession, CuratorSessionEvent

    kuratorin = Curator(display_name="Eine Kuratorin", email="k2@example.ch", role_label="Kurator")
    session.add(kuratorin)
    session.flush()
    cs = CuratorSession(member_id=member.id, curator_id=kuratorin.id, opened_from="know_panel")
    session.add(cs)
    session.flush()
    record = CuratorSessionEvent(session_id=cs.id, kind="opened", actor=kuratorin.id)
    session.add(record)
    session.commit()

    with engine.begin() as connection:
        for verb in ("update", "delete"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_curator_session_events_no_{verb}"))
    try:
        record.actor = "tampered"
        with pytest.raises(AuditImmutable, match="C-10"):
            session.commit()
        session.rollback()

        session.delete(session.get(CuratorSessionEvent, record.id))
        with pytest.raises(AuditImmutable, match="C-10"):
            session.commit()
        session.rollback()

        assert session.get(CuratorSessionEvent, record.id).actor == kuratorin.id
    finally:
        from eigentlich.db import install_append_only_triggers

        install_append_only_triggers(engine)


def test_the_curator_session_row_itself_stays_mutable(session, member):
    """The other half of the split this module's docstring records, so the guard above cannot overreach.

    `curator_sessions` is NOT append-only: R-231's erasure nulls `member_id` on it, and §4 wants a
    `closed_at`. A guard that refused writes to the parent row would break erasure, and erasure failing
    closed is not obviously worse than erasure failing open only until it is the thing that fails.
    """
    from eigentlich.models import Curator, CuratorSession

    kuratorin = Curator(display_name="Eine Kuratorin", email="k3@example.ch", role_label="Kurator")
    session.add(kuratorin)
    session.flush()
    cs = CuratorSession(member_id=member.id, curator_id=kuratorin.id, opened_from="know_panel")
    session.add(cs)
    session.commit()

    cs.member_id = None
    session.commit()
    assert session.get(CuratorSession, cs.id).member_id is None


# ============================================================ R-100 / NG-05


def test_registration_below_age_floor_refused_server_side(session):
    """R-100. One below whatever the floor is, not a literal 24 — the floor moved once (A50) and the
    mechanism is what the requirement is about."""
    from eigentlich.models import MINIMUM_AGE

    with pytest.raises(BelowAgeFloor):
        register_member(session, age_at_registration=MINIMUM_AGE - 1, display_name="Too young")


def test_registration_at_the_floor_is_accepted(session):
    from eigentlich.models import MINIMUM_AGE

    member = register_member(session, age_at_registration=MINIMUM_AGE, display_name="Just old enough")
    session.commit()
    assert member.id


def test_the_floor_is_at_or_above_adulthood(session):
    """A50. Below 18, parental or guardian consent becomes a real requirement and those flows do not
    exist. This test is the tripwire on lowering it further without building them."""
    from eigentlich.models import MINIMUM_AGE

    assert MINIMUM_AGE >= 18, (
        "a floor below 18 admits minors, and NG-05's stated reason was 'no minor-consent flows'. "
        "Build the consent flow before lowering this."
    )


def test_age_floor_is_also_a_database_constraint(engine):
    from eigentlich.models import MINIMUM_AGE

    """"Refused by the API even if the client is bypassed" — and by the store if the API is bypassed."""
    from sqlalchemy import text

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, "
                    f"created_at) VALUES ('y', {MINIMUM_AGE - 1}, 'Bypassed', 'de-CH', 1, '2026-01-01')"
                )
            )


# ============================================================ R-030


def test_two_goals_may_share_funding_positions(session, member):
    """R-030: goals never partition holdings. No uniqueness constraint forces a holding into one goal."""
    with mutate_plan(session, member_id=member.id, question="Set up two goals?", choice="Yes") as decision:
        position = Position(
            member_id=member.id, role="growth", capital_type="financial", label="Securities account"
        )
        house = Goal(member_id=member.id, name="House deposit")
        courage = Goal(member_id=member.id, name="Courage money", template="courage_money")
        house.funded_by.append(position)
        courage.funded_by.append(position)
        session.add_all([position, house, courage])
        decision.linked_positions.append(position)
        decision.linked_goals.extend([house, courage])
    session.commit()

    assert position in house.funded_by
    assert position in courage.funded_by


# ============================================================ R-020 / principle 3


def test_position_is_valid_with_one_row_filled(session, member):
    """R-020: a Position is valid with only one row filled; the grid must be useful at n=1."""
    with mutate_plan(session, member_id=member.id, question="First position?", choice="Employment") as d:
        position = Position(member_id=member.id, role="income", capital_type="human", label="Employment")
        session.add(position)
        d.linked_positions.append(position)
    session.commit()

    assert session.query(Position).filter_by(member_id=member.id).count() == 1
    assert position.magnitude is None, "a position without a magnitude is still a position"


# ============================================================ C-02


#: C-02's three permitted floats, each named with the reason it is not a rate.
#:
#: A list rather than a rule, because every rule that would let these three through — "floats in `llm/`
#: are fine", "floats over 100 are fine" — would let the next one through too, and the next one is the
#: one nobody looked at. `test_every_permitted_float_is_still_there` fails if one of these is removed, so
#: an entry cannot outlive the line it excuses and the list cannot quietly become a place to put things.
PERMITTED_FLOATS = {
    ("engines/__init__.py", 365.2425): (
        "days per Gregorian year. A calendar fact — 400 years hold 97 leap days — used to turn a member's "
        "own target date into an engine's horizon. Nobody published it and nobody can revise it."
    ),
    ("llm/__init__.py", 0.0): (
        "the local model's sampling temperature. A property of how the model is called, not a figure any "
        "member sees or any illustration is derived from."
    ),
    ("llm/__init__.py", 2.0): (
        "the reachability probe's timeout, in seconds. Used to grey out a screen, never to decide policy "
        "— `available()` says so in its own docstring."
    ),
    # ------------------------------------------------------------------ services/identities.py
    #
    # The four below are ARITHMETIC, not quantities. Everything in that module that is a quantity — the
    # network scale, the expertise credits, the confidence table — was moved to
    # `client/content/intake-scales.json` precisely so it would not need excusing here: the port's first
    # version kept them in code and this guard refused it, correctly. What is left is the language's own
    # semantics and two unit multipliers.
    ("services/identities.py", 0.0): (
        "the floor of `_number_or_zero`, which reproduces JavaScript's `Number(x) || 0`. A coercion's "
        "fallback, not a figure: it is what an unparseable answer becomes before anything is computed."
    ),
    ("services/identities.py", 0.5): (
        "the half in `_js_round`'s `floor(x + 0.5)`. That IS the rounding rule — `Math.round` rounds half "
        "toward positive infinity — and it is arithmetic in the same sense 365.2425 is a calendar fact."
    ),
    ("services/identities.py", 1000000.0): (
        "the multiplier behind a goal written as \"1 Mio\". A unit conversion stated by the member's own "
        "wording, not a rate anybody published or could revise."
    ),
    ("services/identities.py", 1000.0): (
        "the multiplier behind a goal written as \"500 tsd\" or \"80k\". Same as 1e6 above."
    ),
}


def test_no_literal_rate_in_application_code():
    """C-02: rates, horizons and inflation live in a versioned AssumptionSet, not in code.

    Checked structurally: the application declares no float literal that could be a rate. A crude test,
    and deliberately so — it cannot tell a rate from any other number, so it forbids the whole shape
    rather than trying to be clever about intent.

    **It used to glob two directories, non-recursively.** `models/*.py` and `services/*.py` and nothing
    else: not `api/`, not `engines/`, not `llm/`, not the modules at the top of the package. An audit put
    `ASSUMED_RATE = 0.045` in `api/befund.py` and watched it pass while `/api/health` went on claiming
    "no literal rate in application code" — a claim the product makes to anyone who asks it, backed by a
    test that had never read the file. The scan now walks the whole package.

    **Planted:** `ASSUMED_RATE = 0.045` at module level in `eigentlich/api/befund.py`. Failed naming
    `api/befund.py:… 0.045`. Restored.
    """
    package = MODEL_LAYER.parent
    offences: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, float)):
                continue
            if (relative, node.value) in PERMITTED_FLOATS:
                continue
            offences.append(f"{relative}:{node.lineno} {node.value}")
    assert not offences, "C-02: no literal rate in application code. Found floats: " + "; ".join(offences)


def test_every_permitted_float_is_still_there():
    """The allowlist above cannot outlive what it excuses, and cannot be padded with entries for nothing.

    An allowlist nobody checks is how a scan stops covering the file it was widened to reach: delete the
    line, the entry stays, and the next float at that value in that file is waved through.
    """
    package = MODEL_LAYER.parent
    seen: set[tuple[str, float]] = set()
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                seen.add((relative, node.value))
    assert seen == set(PERMITTED_FLOATS), (
        f"the C-02 allowlist and the package disagree. Excused but absent: {set(PERMITTED_FLOATS) - seen}; "
        f"present but not excused: {seen - set(PERMITTED_FLOATS)}"
    )


def test_the_float_scan_reaches_past_the_two_directories_it_used_to_glob():
    """A guard on the widening, because the widening is the whole repair.

    `rglob` over a path that has been renamed finds nothing and reports no offences, which is the same
    green as a clean package. So: assert the scan actually opens the files the audit's plant went into.
    """
    package = MODEL_LAYER.parent
    walked = {p.relative_to(package).as_posix() for p in package.rglob("*.py") if "__pycache__" not in p.parts}
    for required in ("api/befund.py", "engines/__init__.py", "llm/__init__.py", "boundary.py",
                     "models/plan.py", "services/goals.py", "interpret.py"):
        assert required in walked, f"C-02's scan never opens {required}"


def test_assumption_set_requires_a_publisher(session):
    """An assumption set with no author is one nobody can be asked about."""
    import datetime as dt

    from sqlalchemy.exc import IntegrityError as IE

    session.add(AssumptionSet(version="v0", effective_from=dt.date(2026, 1, 1), published_by=None))
    with pytest.raises(IE):
        session.commit()


# ============================================================ not yet — phases 3 to 7


# C-01 moved to tests/test_boundary.py and tests/test_know.py in phase 4. It is checked by 74 tests
# that run with no model installed, which is what 'provably not by prompt alone' means.


def test_illustration_response_always_carries_assumption_set(session):
    """C-02: "every illustration response returns the assumption_set_id used".

    **This was an `xfail(strict=True)` placeholder reading "phase 2: illustrations do not exist yet".** It
    stayed that way after A69 published a real AssumptionSet, while `services/goals.py` returned
    `illustration: None` with the reason `no_assumption_set_published` — so the constraint was untested and
    the application was telling every member something false. Both are closed here.

    Asserted over the **API payload**, not over the illustration builder, because C-02 says *response*: the
    stamp has to survive `goal_payload` and `list_goals`, which is where it would be dropped by an edit
    that reorganised the payload.

    **Both directions.** With no set published the reason is present and no illustration is offered; with
    one published every illustration carries its id and version. A test that only checked the first half
    would pass on the bug this replaces.
    """
    import datetime as dt

    from eigentlich.services.goals import list_goals

    member = register_member(session, age_at_registration=41, display_name="C-02")
    with mutate_plan(session, member_id=member.id, question="Ziel?", choice="Ja") as decision:
        position = Position(
            member_id=member.id, role="growth", capital_type="financial", label="Depot", active=True
        )
        goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=250_000)
        session.add_all([position, goal])
        goal.funded_by.append(position)
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    session.commit()

    # -- no set published: refused, with the one reason that may say the table is empty ------------
    before = list_goals(session, member_id=member.id)["goals"][0]
    assert before["illustration"] is None
    assert before["illustration_unavailable_reason"] == "no_assumption_set_published"

    session.add(
        AssumptionSet(
            version="c02-test",
            effective_from=dt.date(2024, 12, 31),
            published_by="SIM Research, run 2026-08-31",
            rates={
                "values_unit": "annualised_decimal",
                "scenarios": ["crisis", "boom"],
                "role_profiles_by_scenario": {"gain": {"crisis": -0.3, "boom": 0.09}},
                "scenario_probabilities": {"crisis": 0.2, "boom": 0.12},
            },
            horizons={"return_estimation_years": 1},
        )
    )
    session.commit()

    # -- published: every illustration carries the id it used -------------------------------------
    after = list_goals(session, member_id=member.id)["goals"][0]
    assert after["illustration_unavailable_reason"] is None
    illustration = after["illustration"]
    assert illustration is not None, "C-02: a published set and a funded, priced goal produced nothing"
    assert illustration["assumption_set_id"], "C-02: no assumption_set_id on the illustration"
    assert illustration["assumption_set_version"] == "c02-test"
    assert illustration["by_role"], "an illustration with no figures is not an illustration"


# C-08 moved to tests/test_marketplace.py in phase 7, where there is a real ranking to check.
#
# **This was a stub asserting the Market Place did not exist**, carrying `xfail(strict=True)` and the reason
# "phase 7: the Market Place does not exist yet". Phase 7 was built, and the stub kept passing — because a
# strict xfail passes by *failing*, and `raise AssertionError` is a reliable way to fail. So the suite
# reported it as an expected failure long after the thing it described had shipped, and §11's checklist read
# by name found this stub before it found the real test. A90's audit caught it; the real
# `test_listing_ranking_cannot_read_fee_fields` in `test_marketplace.py` is thorough, plants a fee both
# ways, and computes the order a fee-reading ranking *would* have produced.
#
# Removed rather than repointed: two tests of one name in one suite is how the wrong one gets read.


# C-05 moved to tests/test_client_bundle.py in phase 2: there is a real bundle to scan now.


def test_no_engine_artefact_served_over_http():
    """C-03 / R-304. No engine, weight file or model artefact is reachable from the browser.

    A real test now that the engines are wired. It was xfail while `call_engine` raised
    `NotImplementedError`, which made the constraint vacuously true and therefore untested.

    Checked in four layers, because a live request only proves that *this* URL was refused:

      1. every static mount points inside `client/`. Nothing under the estate is mounted, so no engine
         artefact has a URL at all;
      2. no served file carries the marker keys of a Regime timeline or a ReturnSet. That catches an
         artefact copied into the bundle, which is how one would actually escape — by hand, once;
      3. no module under `eigentlich/api/` *imports* the engine façade. A route cannot invoke an engine
         (R-301) and cannot serialise its output, because the module is not there to call;
      4. every runtime payload that carries engine output to a member goes through
         `services/served.py`, and that guard is exercised **in both directions** here.

    **Layer 3 changed shape on 31 August 2026 and the claim it makes is now narrower — read this.** It used
    to say "the API package never imports the engine façade", and it checked that by looking for the
    strings `eigentlich.engines` and `from ..engines` anywhere in the file. Two things were wrong with it.

    It matched **prose**: a docstring explaining why a module must not import `eigentlich.engines` failed the
    test that the module must not import `eigentlich.engines`. So it is an AST check now — actual `import`
    statements, nothing else.

    And the old wording was about to become false. R-301 says "queue and poll", and the queue has to reach
    an engine from *somewhere* the application can start: `services/runs.py` imports `call_engine`, and
    `api/main.py` imports `services.runs` to start the worker. So the API package now reaches the façade
    **transitively**, and no test could honestly say otherwise. What layer 3 still holds, and what is worth
    holding, is that no API module can *name* `call_engine`: the only way from a route to an engine is
    `submit`, which writes a row and returns, and the only synchronous engine call in the application is
    inside the worker thread. Layer 4 is what covers the part layer 3 gave up — the payload itself.
    """
    from starlette.staticfiles import StaticFiles

    from eigentlich.api.main import PROJECT, app
    from eigentlich.engines import ESTATE_ROOT

    client_dir = (PROJECT / "client").resolve()
    mounts = [
        (route.path, Path(route.app.directory).resolve())
        for route in app.routes
        if isinstance(getattr(route, "app", None), StaticFiles)
    ]
    assert mounts, "no static mount was found, so this test proves nothing — see A20 on vacuous checks"

    for path, directory in mounts:
        assert directory == client_dir or client_dir in directory.parents, (
            f"C-03: {path} serves {directory}, which is outside the client bundle"
        )
        assert ESTATE_ROOT.resolve() not in [directory, *directory.parents] or client_dir in directory.parents

    #: Keys that only ever occur inside a published engine contract. `regime_timeline_id` and
    #: `return_set_id` name the artefact; `building_blocks` and `state_grid` are its payload.
    artefact_markers = ("regime_timeline_id", "return_set_id", "building_blocks", "state_grid")
    served = [p for _, directory in mounts for p in directory.rglob("*") if p.is_file()]
    assert served, "the mounted directories are empty, so this test proves nothing"
    for path in served:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary asset carries no JSON contract
        found = [marker for marker in artefact_markers if marker in text]
        assert not found, f"C-03: {path} carries engine artefact keys {found}"

    api_layer = Path(__file__).resolve().parent.parent / "eigentlich" / "api"
    api_modules = sorted(api_layer.glob("*.py"))
    assert api_modules, "no API modules were found, so layer 3 proves nothing"

    importers = sorted(
        path.name for path in api_modules if _imports_the_engine_facade(path, package="eigentlich.api")
    )
    assert not importers, (
        f"C-03 / R-301: the API layer imports the engine façade in {importers}. A module that can name "
        f"`call_engine` can invoke it on a request thread and can serialise its output into a response. "
        f"The queue is the route from HTTP to an engine: `services/runs.submit` writes a row and returns, "
        f"and the only synchronous engine call in the application is inside the worker thread."
    )

    # -- layer 4: the runtime guard, exercised in both directions -----------------------------------
    #
    # Layer 3 is a statement about imports and cannot see a payload assembled at request time. These two
    # are the surfaces that carry engine output to a member, and both build their payload by copying
    # fields out of something bigger, which is exactly how an artefact escapes.
    from eigentlich.services.runs import _member_facing_result
    from eigentlich.services.served import (
        ARTEFACT_MARKERS,
        EngineArtefactWouldBeServed,
        artefact_markers_in,
        assert_no_engine_artefact,
    )

    # The guard reports a marker when there is one. Without this the three assertions below would pass on
    # a function that returned an empty list unconditionally — A20's exact shape.
    assert artefact_markers_in({"contract": {"regime_timeline_id": "RTL-1"}}) == ["regime_timeline_id"]
    with pytest.raises(EngineArtefactWouldBeServed):
        assert_no_engine_artefact({"state_grid": 25}, where="a planted violation")
    # And it looks all the way down, not just at the top level.
    with pytest.raises(EngineArtefactWouldBeServed):
        assert_no_engine_artefact({"a": [{"b": {"building_blocks": []}}]}, where="a nested violation")

    # A whole `call_engine` reply, in the shape the estate really returns one, reduced for a member.
    reply = {
        "engine": "market_signal",
        "contract_type": "RegimeRef",
        "contract": {
            "regime_id": "REG-38d91c1a0da0ef1e",
            "regime_timeline_id": "RTL-38d91c1a0da0ef1e",
            "scope": "Global",
        },
        "model_version": "ms@0.1.0",
        "notes": ["blended over: br 5%, ch 5%"],
        "trace_id": "TR-a08acce35dcb6f96",
        "raw": {"months": 177},
        "replay": "cd Macro_Model && <read> output/regime/Global.json",
        "artefact": {"current": {"state": 9}},
    }
    reduced = _member_facing_result(reply)
    rendered = json.dumps(reduced)
    for marker in ARTEFACT_MARKERS:
        assert marker not in rendered, f"C-03: a run result served {marker!r}"
    for dropped in ("raw", "artefact", "replay"):
        assert dropped not in reduced, f"C-03: a run result served {dropped!r}"
    # Non-vacuous the other way: the reading itself survives, so this is a filter and not a wall.
    assert reduced["contract"]["regime_id"] == "REG-38d91c1a0da0ef1e"
    assert reduced["model_version"] == "ms@0.1.0"


def _imports_the_engine_facade(path: Path, *, package: str) -> bool:
    """Whether `path` contains an actual import of `eigentlich.engines`. AST, not text.

    A relative import is resolved against `package` the way Python resolves it, so `from ..engines import
    call_engine` inside `eigentlich/api/` is caught and a docstring mentioning the module is not.
    """
    target = "eigentlich.engines"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == target or alias.name.startswith(target + ".") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - (node.level - 1)]
                resolved = ".".join([*base, *([node.module] if node.module else [])])
            else:
                resolved = node.module or ""
            if resolved == target or resolved.startswith(target + "."):
                return True
    return False


def test_no_model_column_uses_the_raw_datetime_type():
    """A57. `DateTime(timezone=True)` is a promise SQLite cannot keep.

    It stores the instant and drops the offset, so a row written aware returns naive and any
    `stored > utcnow()` comparison raises TypeError — but only when the row is loaded from disk rather
    than served from the identity map, which is why a 450-test suite missed it in two files.

    `models.base.DateTime` coerces on bind and on result. This asserts nothing bypasses it, so the next
    datetime column cannot reintroduce the bug.
    """
    from eigentlich.models import Base
    from eigentlich.models.base import DateTime as AwareDateTime

    offenders = [
        f"{mapper.class_.__tablename__}.{column.key}"
        for mapper in Base.registry.mappers
        for column in mapper.class_.__table__.columns
        if "DateTime" in type(column.type).__name__ and not isinstance(column.type, AwareDateTime)
    ]
    assert not offenders, f"these columns bypass the timezone-aware type: {offenders}"


def test_a_datetime_survives_a_round_trip_to_disk(tmp_path):
    """The regression test for A57, written as the reproduction that found it."""
    from eigentlich.db import create_all, make_engine, make_session_factory
    from eigentlich.services.auth import login, member_for_token, register_with_credentials

    engine = make_engine(f"sqlite:///{tmp_path / 'tz.db'}")
    create_all(engine)
    factory = make_session_factory(engine)

    with factory() as db:
        register_with_credentials(
            db, email="tz@example.ch", password="ein langes passwort hier",
            age_at_registration=40, display_name="TZ",
        )
        db.commit()
        _row, token = login(db, email="tz@example.ch", password="ein langes passwort hier")
        db.commit()

    # A DIFFERENT session: the row is loaded from disk, not served from the identity map.
    with factory() as fresh:
        assert member_for_token(fresh, token) is not None


def test_every_append_only_trigger_survives_a_full_migration(tmp_path):
    """R-040 and C-10, checked after migrating from nothing rather than after `create_all`.

    **This exists because a migration switched them off and nothing noticed.** SQLite cannot alter a
    column in place, so alembic's batch mode copies the table and renames it — and everything attached to
    the old table, triggers included, goes with it. The ORM guard in `db.py` still held, so the suite
    stayed green while raw SQL could have rewritten a Decision.

    **And then this test failed to catch the recurrence, because it was vacuous.** It used to run alembic
    in a subprocess and point it at a temporary database by setting `ANDERSCH_DB_URL` — a variable nothing
    reads. So the temporary file was never created, a fallback branch ran `create_all()` plus
    `install_append_only_triggers()`, and the test asserted that the triggers it had just installed by hand
    were installed. It had never once run a migration; meanwhile the subprocess migrated the developer's
    real database as a side effect.

    Driving alembic through its Python API with an explicit url removes both problems: the url is set on
    the object that actually reads it, and there is no branch that can quietly substitute `create_all`.
    """
    import sqlite3
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parent.parent
    database = tmp_path / "migrated.db"

    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    assert database.exists(), "the migration did not produce a database; the url was not honoured"

    connection = sqlite3.connect(database)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        for expected in (
            "trg_decisions_no_update",
            "trg_decisions_no_delete",
            "trg_curator_session_events_no_update",
            "trg_curator_session_events_no_delete",
        ):
            assert expected in names, (
                f"{expected} is missing after migrating. A batch_alter_table on that table recreates it "
                f"and drops its triggers — the migration that does so must re-create them ON ITS OWN "
                f"CONNECTION, via append_only_trigger_statements(). Reaching for `.engine` opens a second "
                f"connection outside the migration's transaction and the CREATEs become no-ops."
            )
    finally:
        connection.close()


def test_a_migrated_database_actually_refuses_to_rewrite_a_decision(tmp_path):
    """The trigger exists *and* fires. Presence is what the previous test can see; refusal is the point.

    A trigger that is present but somehow inert would satisfy every name check above. This writes a
    Decision through raw SQL — the exact path the ORM guard cannot see — and requires both verbs to be
    refused on a database built the way a real deployment builds one.
    """
    import sqlite3
    from pathlib import Path

    import pytest
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parent.parent
    database = tmp_path / "migrated.db"
    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES ('m-trig', 40, 'x', 'de-CH', 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO decisions (id, member_id, author, question, choice, options_considered, "
            "data_class, created_at) VALUES ('d-trig', 'm-trig', 'member', 'q', 'original', '[]', 2, "
            "'2026-01-01')"
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE decisions SET choice = 'rewritten' WHERE id = 'd-trig'")
        connection.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM decisions WHERE id = 'd-trig'")
        connection.rollback()

        assert connection.execute("SELECT choice FROM decisions WHERE id = 'd-trig'").fetchone()[0] == (
            "original"
        )
    finally:
        connection.close()


def _migrated(tmp_path, name="migrated.db"):
    """A database built the way a deployment builds one, and the config object that built it.

    Factored out because four tests below need one and the A68 lesson is that the *way* it is built is the
    whole point: alembic through its Python API, with the url set on the object that actually reads it, and
    no branch anywhere that could substitute `create_all`.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parent.parent
    database = tmp_path / name
    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    assert database.exists(), "the migration did not produce a database; the url was not honoured"
    return database, config


def test_a_migrated_database_refuses_a_curator_session_naming_nobody(tmp_path):
    """C-10 / A67. `curator_sessions.curator_id` is a foreign key, and it fires on a migrated database.

    **This is the constraint A40 claimed and did not have.** It was a plain `String(120)` for the whole of
    the build, so any string at all could be written as the identified curator on the parent row of an
    append-only audit — a row whose `opened` event cannot afterwards be rewritten or removed, which is why
    a wrong value here is not correctable by the means everything else is.

    Written through raw SQL on purpose. The service layer resolves the curator and the route resolved it
    before that, and neither of those is the property being checked: what is checked is that the store
    refuses, for a caller that went round both.

    **Planted violation:** dropped `create_foreign_key` from the migration's batch block. This test failed
    on the first insert, which succeeded. Restored.
    """
    import sqlite3

    import pytest

    database, _ = _migrated(tmp_path)

    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES ('m-fk', 40, 'x', 'de-CH', 1, '2026-01-01')"
        )
        connection.commit()

        # Every one of these was writable before 31 August 2026, and `"curator:nb"` is the exact string
        # three rows in the development database held.
        for invented in ("curator:nb", "curator:demo", "unassigned", ""):
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                connection.execute(
                    "INSERT INTO curator_sessions (id, member_id, curator_id, opened_from, opened_at, "
                    "data_class, created_at) VALUES (?, 'm-fk', ?, 'know_panel', '2026-01-01', 2, "
                    "'2026-01-01')",
                    (f"cs-{invented}", invented),
                )
            connection.rollback()

        assert connection.execute("SELECT count(*) FROM curator_sessions").fetchone()[0] == 0

        # And the same insert naming a real row is accepted, so the refusal above is about the constraint
        # and not about the statement being malformed.
        connection.execute(
            "INSERT INTO curators (id, display_name, email, active, fictional, must_change, data_class, "
            "created_at) VALUES ('cur-real', 'Eine Kuratorin', 'k@example.ch', 1, 0, 0, 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curator_sessions (id, member_id, curator_id, opened_from, opened_at, "
            "data_class, created_at) VALUES ('cs-real', 'm-fk', 'cur-real', 'know_panel', '2026-01-01', "
            "2, '2026-01-01')"
        )
        connection.commit()
        assert connection.execute("SELECT count(*) FROM curator_sessions").fetchone()[0] == 1
    finally:
        connection.close()


def test_a_migrated_database_actually_refuses_to_rewrite_a_curator_session_event(tmp_path):
    """C-10 / R-040 on the append-only table itself, after a migration that rebuilt its parent.

    The existing pair above proves the `decisions` triggers are present and firing on a migrated database.
    This is the `curator_session_events` half, and it is here because the A67 migration batch-alters
    `curator_sessions` — the table every one of these events points at. A63 is what happens when a rebuild
    takes triggers with it and only a count on a migrated database would have shown it; presence is what a
    count can see, and refusal is the property, so this writes an event through raw SQL and requires both
    verbs to be refused.

    **Planted violation:** removed the `_restore_triggers()` call from the migration's `upgrade()`. This
    test still passed, which is the honest result and worth recording: `curator_sessions` carries no
    trigger of its own, so rebuilding it does not disturb the ones on `curator_session_events`. The call
    stays because "does not disturb them today" is a fact about today's schema, and this test is what will
    notice when it changes.
    """
    import sqlite3

    import pytest

    database, _ = _migrated(tmp_path)

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES ('m-ev', 40, 'x', 'de-CH', 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curators (id, display_name, email, active, fictional, must_change, data_class, "
            "created_at) VALUES ('cur-ev', 'Eine Kuratorin', 'k@example.ch', 1, 0, 0, 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curator_sessions (id, member_id, curator_id, opened_from, opened_at, "
            "data_class, created_at) VALUES ('cs-ev', 'm-ev', 'cur-ev', 'know_panel', '2026-01-01', 2, "
            "'2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curator_session_events (id, session_id, kind, at, actor, data_class, created_at) "
            "VALUES ('ev-1', 'cs-ev', 'opened', '2026-01-01', 'cur-ev', 2, '2026-01-01')"
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE curator_session_events SET actor = 'someone else' WHERE id = 'ev-1'")
        connection.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM curator_session_events WHERE id = 'ev-1'")
        connection.rollback()

        assert connection.execute(
            "SELECT actor FROM curator_session_events WHERE id = 'ev-1'"
        ).fetchone()[0] == "cur-ev"
    finally:
        connection.close()


def test_the_migration_refuses_a_database_whose_sessions_name_nobody(tmp_path):
    """The A67 migration will not repair audit rows by guessing, and this is that refusal firing.

    A session whose `curator_id` names nobody cannot be repaired by any rule: it cannot be deleted (its
    `opened` event is in a table that refuses DELETE, and the event references the session), and pointing
    it at *some* curator would write a new false statement into an audit in order to satisfy a constraint
    whose only purpose is that the audit be true. So the migration stops and names the rows.

    Built by migrating to the revision *before* the foreign key, planting the row a caller could have
    written on that schema, and then migrating to head.

    **Planted violation:** made `_refuse_sessions_naming_nobody` return without checking. The upgrade then
    failed on `PRAGMA foreign_key_check` in `env.py` instead — the second net catching it, with a message
    about a rowid rather than about a curator — and this test failed on the `match`. Restored, and worth
    recording that the two guards are independent.
    """
    import sqlite3

    import pytest
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    database = tmp_path / "dirty.db"
    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    #: The revision that made `member_id` nullable — the last one before `curator_id` became a key.
    command.upgrade(config, "f4b1c07ad9e2")

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES ('m-dirty', 40, 'x', 'de-CH', 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curator_sessions (id, member_id, curator_id, opened_from, opened_at, "
            "data_class, created_at) VALUES ('cs-dirty', 'm-dirty', 'curator:nb', 'know_panel', "
            "'2026-01-01', 2, '2026-01-01')"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="will not repair the rows itself"):
        command.upgrade(config, "head")

    # And the schema is untouched, because the check runs before anything is altered.
    connection = sqlite3.connect(database)
    try:
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'curator_sessions'"
        ).fetchone()[0]
        assert "REFERENCES curators" not in ddl, "the migration must not half-apply"
        assert connection.execute("SELECT count(*) FROM curator_sessions").fetchone()[0] == 1
    finally:
        connection.close()


def test_the_migration_run_checks_its_own_foreign_keys_at_the_end(tmp_path):
    """`env.py` turns foreign key enforcement off for a migration run, and this is what replaces it.

    **Why enforcement has to be off.** SQLite cannot alter a column in place, so alembic's batch mode
    rebuilds the table — copy out, DROP the original, rename back. `DROP TABLE` with foreign keys enforced
    performs an implicit `DELETE FROM`, and `curator_session_events` points at every row of
    `curator_sessions`, so the drop fails on any database that has ever recorded a consultation. It
    succeeded on a fresh file and in the suite only because those tables were empty — A68's shape exactly,
    the path with real rows in it being the path nothing took.

    **So the enforcement is replaced rather than removed**, by `PRAGMA foreign_key_check` on the finished
    result, inside the migration transaction, so a failure rolls the whole upgrade back. This exercises
    that function against a connection that really does hold a violating row, because a check nobody has
    seen fail is not a check.

    **Planted violation:** made `refuse_broken_foreign_keys` return unconditionally. This test failed on
    the `pytest.raises`. Restored.
    """
    import sqlite3
    from pathlib import Path

    import pytest
    import sqlalchemy

    backend = Path(__file__).resolve().parent.parent
    database, _ = _migrated(tmp_path, "fkcheck.db")

    # A violating row, inserted with enforcement off, which is the state a migration runs in.
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES ('m-chk', 40, 'x', 'de-CH', 1, '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO curator_sessions (id, member_id, curator_id, opened_from, opened_at, "
            "data_class, created_at) VALUES ('cs-chk', 'm-chk', 'nobody-at-all', 'know_panel', "
            "'2026-01-01', 2, '2026-01-01')"
        )
        connection.commit()
    finally:
        connection.close()

    # **`env.py` runs migrations at import time**, so the function is compiled out of its source rather
    # than imported: importing that module would migrate whatever database its config resolves to, which
    # is the A68 side effect — a test quietly writing to the developer's own file — and this test exists to
    # check a guard, not to acquire one.
    source = (backend / "migrations" / "env.py").read_text(encoding="utf-8")
    assert source.count("def refuse_broken_foreign_keys(") == 1, "the function was renamed; this is stale"
    namespace: dict = {}
    start = source.index("def refuse_broken_foreign_keys(")
    end = source.index("def run_migrations_online(")
    exec(compile(source[start:end], "env.py", "exec"), namespace)
    refuse = namespace["refuse_broken_foreign_keys"]

    engine = sqlalchemy.create_engine(f"sqlite:///{database}")
    with engine.connect() as live:
        with pytest.raises(RuntimeError, match="violate a foreign key"):
            refuse(live)
    engine.dispose()


def test_the_live_database_has_all_four_triggers():
    """The development database itself, which is what the desktop icon opens onto.

    It used to assert `len(names) == 4`. That was the right check while the append-only triggers were the
    only ones in the system; C-06's two content triggers on `action_items` are legitimate and would have
    broken it for the wrong reason. So the two halves are now said separately: **every append-only trigger
    is present** — which is the guarantee, and the thing A63 and A66 lost — and **every trigger present is
    one this codebase declares**, which is what a bare count was standing in for.
    """
    from pathlib import Path

    import sqlalchemy

    database = Path(__file__).resolve().parent.parent / "eigentlich.db"
    if not database.exists():
        import pytest

        pytest.skip("no development database on this machine")

    engine = sqlalchemy.create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='trigger'")
            )
        }

    append_only = {
        "trg_decisions_no_update",
        "trg_decisions_no_delete",
        "trg_curator_session_events_no_update",
        "trg_curator_session_events_no_delete",
    }
    missing = sorted(append_only - names)
    assert not missing, f"append-only triggers missing from the development database: {missing}"

    # Since A168 the append-only four are the ONLY triggers this codebase declares. C-06's two content
    # triggers on `action_items` used to be the legitimate remainder; `e7b3a95d612f` dropped them.
    unknown = sorted(names - append_only)
    assert not unknown, f"the development database carries triggers this codebase does not declare: {unknown}"


# ============================================================ C-04, the INSTALLATION
#
# The test above builds a `TopClassRedactingFilter` and attaches it by hand, so it never exercises
# `install()` at all — which is why it stayed green while `install()` was inert in the running server.
# Everything below runs the REAL `install_log_filter()` against the arrangements the application actually
# has: a handler added after installation (uvicorn's order), a record arriving by propagation from an
# `eigentlich.*` child logger, and the deployed process itself.


K3_VALUE = "Pensionskassenausweis Helvetia 2026"


@contextlib.contextmanager
def _isolated_logger(name: str):
    """A logger that does not touch the rest of the suite, restored afterwards.

    `propagate = False` so a leak cannot be hidden by some other handler higher up, and so a redaction
    cannot be borrowed from one either — this has to be measuring the handlers attached here.
    """
    logger = logging.getLogger(name)
    saved = (list(logger.handlers), list(logger.filters), logger.propagate, logger.level)
    logger.handlers = []
    logger.filters = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.handlers, logger.filters, logger.propagate, logger.level = saved


@contextlib.contextmanager
def _without_the_global_filter():
    """Take the process-wide filter off, and put it back.

    Needed by the control test below: with the filter installed, `logging.Logger.addHandler` attaches it
    to every new handler, which is the whole fix — and would make a test that is supposed to observe a
    leak observe a redaction instead.
    """
    was_installed = log_filter._installed is not None
    log_filter.uninstall()
    try:
        yield
    finally:
        if was_installed:
            log_filter.install()


def test_install_covers_a_handler_added_after_installation():
    """C-04, the defect. `install()` runs at import; uvicorn adds its handlers afterwards.

    The old `install()` attached the filter to the logger and to `target.handlers`, which at import time
    is an empty list. Every record emitted by the running server then reached a handler carrying no
    filter, and a filter attached at *logger* level does not run for records that arrive by propagation.
    """
    with _isolated_logger("c04.install.late") as logger:
        log_filter.install(logger)  # import time: no handlers exist yet
        buffer = io.StringIO()
        logger.addHandler(logging.StreamHandler(buffer))  # uvicorn, afterwards

        logging.getLogger("c04.install.late.child").info("stored vault item title=%s", K3_VALUE)

        written = buffer.getvalue()
        assert K3_VALUE not in written, f"a K3 value reached a log line: {written!r}"
        assert REDACTION in written


def test_install_covers_a_record_that_arrives_by_propagation():
    """The handler exists first; the record comes from an `eigentlich.*` child.

    A K3 field disclosed by a child logger is disclosed. This is the arrangement the whole application
    runs in — every module logs through `eigentlich.<something>` and nothing has its own handler.
    """
    with _isolated_logger("eigentlich.c04.propagation") as logger:
        buffer = io.StringIO()
        logger.addHandler(logging.StreamHandler(buffer))
        log_filter.install(logger)

        child = logging.getLogger("eigentlich.c04.propagation.vault")
        child.info("stored vault item title=%s for member", K3_VALUE)
        child.info("payload %s", {"title": K3_VALUE, "kind": "policy"})
        child.info("vault write", extra={"title": K3_VALUE})

        written = buffer.getvalue()
        assert K3_VALUE not in written, f"a K3 value reached a log line: {written!r}"
        assert REDACTION in written


def test_install_covers_the_last_resort_handler():
    """Under uvicorn the root logger has NO handlers — uvicorn configures its own and leaves root alone.

    An `eigentlich.*` warning therefore goes to `logging.lastResort`, which is a handler nobody attached to
    anything and which a sweep of `logger.handlers` would never find. If it is not covered, C-04 does not
    hold on the one path the deployed process actually uses.
    """
    log_filter.install()
    assert logging.lastResort in log_filter.covered_handlers(), (
        "logging.lastResort carries no redacting filter; under uvicorn's logging configuration that is "
        "the handler an eigentlich.* record is emitted by."
    )


def test_the_redaction_marker_is_written_once_and_not_grown():
    """The filter now runs more than once per record, so it has to be idempotent.

    It is attached to handlers as well as to loggers, and `_scrub_placeholders` and the rendered-text
    backstop both run inside a single pass. The rendered-text pattern stops a value at `]`, so before this
    was fixed it re-matched its own output: the real server emitted `title=[K3 redacted]]`. Nothing leaked
    — but a marker that gains a bracket every pass is one a reader learns to skim past, and skimming past
    the redaction marker is how the next unredacted line goes unnoticed.
    """
    with _isolated_logger("c04.install.idempotent") as logger:
        buffer = io.StringIO()
        logger.addHandler(logging.StreamHandler(buffer))
        log_filter.install(logger)

        logging.getLogger("c04.install.idempotent.child").info(
            "stored vault item title=%s for member", K3_VALUE
        )

        written = buffer.getvalue().strip()
        assert K3_VALUE not in written
        assert written == f"stored vault item title={REDACTION} for member", (
            f"the redaction marker was not written cleanly: {written!r}"
        )


def test_the_leak_detection_in_these_tests_actually_detects_a_leak():
    """Guard on the guard — A20's rule, applied to C-04's installation.

    A test that asserts a value is absent is green when it is broken. This builds the arrangement the fix
    was made for, with the filter attached the way `install()` used to attach it — to the logger only,
    before the handler exists — and requires the K3 value to appear. If this ever stops leaking, the
    three tests above have stopped measuring anything and must be re-derived.
    """
    with _without_the_global_filter():
        with _isolated_logger("c04.install.control") as logger:
            logger.addFilter(TopClassRedactingFilter())  # the pre-fix shape, by hand
            buffer = io.StringIO()
            logger.addHandler(logging.StreamHandler(buffer))

            logging.getLogger("c04.install.control.child").info(
                "stored vault item title=%s", K3_VALUE
            )

            written = buffer.getvalue()
            assert K3_VALUE in written, (
                "the pre-fix arrangement no longer leaks, so the tests above prove nothing about "
                "install(). Find out what changed before trusting them."
            )


def test_the_real_application_redacts_a_k3_field_under_the_servers_logging(tmp_path):
    """C-04 in the deployed process, not in a fixture.

    Runs in a subprocess because it reconfigures the logging module for the whole interpreter, which is
    what `uvicorn` does to it before importing the application — and doing that in-process would take
    pytest's own capture with it. The subprocess:

      1. applies `uvicorn.config.LOGGING_CONFIG` exactly as `desktop/run.py` -> `uvicorn.run` does;
      2. imports `eigentlich.api.main`, whose module body calls `install_log_filter()`;
      3. logs a K3 field by name through an `eigentlich.*` child logger, in both arrangements a real
         deployment produces — no root handler at all (uvicorn's default, so `lastResort` emits it) and a
         root handler added after import (what a `--log-config` with a root logger produces).

    Then it requires the value to be absent from everything the process wrote.
    """
    backend = Path(__file__).resolve().parent.parent
    script = tmp_path / "run_like_the_server.py"
    script.write_text(
        "import logging, logging.config, sys\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        "from uvicorn.config import LOGGING_CONFIG\n"
        "logging.config.dictConfig(LOGGING_CONFIG)\n"
        "import eigentlich.api.main\n"
        f"SECRET = {K3_VALUE!r}\n"
        "logging.getLogger('eigentlich.vault').warning("
        "'stored vault item title=%s for member', SECRET)\n"
        "logging.getLogger('eigentlich.vault').warning('vault write', extra={'title': SECRET})\n"
        "root_stream = logging.StreamHandler(sys.stdout)\n"
        "root_stream.setLevel(logging.INFO)\n"
        "logging.getLogger().addHandler(root_stream)\n"
        "logging.getLogger().setLevel(logging.INFO)\n"
        "logging.getLogger('eigentlich.know.panel').info("
        "'answering with kind=%s title=%s', 'policy', SECRET)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(backend),
    )
    written = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, f"the server-shaped process failed:\n{written}"
    assert K3_VALUE not in written, f"a K3 value reached the real application's log:\n{written}"
    assert REDACTION in written, (
        "nothing was redacted and nothing leaked, which means nothing was logged — this test would then "
        "be vacuous. Check that the record is still emitted:\n" + written
    )


# ============================================================ C-09, below the unit of work
#
# `before_flush` sees the ORM unit of work and nothing else. Three writes that never enter it were
# demonstrated against this build: a Core insert, a Core update of a magnitude (R-123's own case) and
# `bulk_save_objects`, which is an ORM call. `positions` and `goals` carry no append-only trigger, so
# there was no second enforcement point to catch what the first one missed. `_refuse_unvetted_plan_dml`
# is that second point; these are the tests that it fires.


def test_the_plan_tables_are_actually_known_to_the_statement_guard():
    """Guard on the guard. An empty `plan_table_names()` would make every test below vacuously green."""
    from eigentlich.db import plan_table_names

    names = plan_table_names()
    assert {"positions", "goals"} <= names, (
        f"the statement-level C-09 guard is watching {sorted(names)}; a plan table missing from this set "
        f"is a plan table with no guard at all."
    )


def test_a_core_insert_cannot_create_a_position_without_a_decision(session, member):
    """The narrowest bypass: the same Session, one layer down."""
    from sqlalchemy import insert

    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(
            insert(Position.__table__).values(
                id="c09-core-insert",
                member_id=member.id,
                role="growth",
                capital_type="financial",
                label="Smuggled in",
                magnitude=250000.0,
                magnitude_unit="chf_per_year",
                active=True,
                tags={},
                data_class=2,
                created_at=utcnow(),
            )
        )
    session.rollback()
    assert session.query(Position).filter_by(id="c09-core-insert").count() == 0


def test_a_core_update_cannot_change_a_magnitude_without_a_decision(session, member):
    """R-123's exact case: editing a position writes a Decision in the same transaction."""
    from sqlalchemy import update

    with mutate_plan(session, member_id=member.id, question="Record it?", choice="Yes") as decision:
        position = Position(
            member_id=member.id,
            role="growth",
            capital_type="financial",
            label="Securities",
            magnitude=1000.0,
            magnitude_unit="chf_per_year",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(
            update(Position.__table__)
            .where(Position.__table__.c.id == position.id)
            .values(magnitude=999999.0)
        )
    session.rollback()
    assert session.get(Position, position.id).magnitude == 1000.0


def test_bulk_save_objects_cannot_write_a_goal_without_a_decision(session, member):
    """An ORM call, not raw SQL — and it skips the unit of work the `before_flush` guard listens to."""
    with pytest.raises(PlanMutationWithoutDecision):
        session.bulk_save_objects([Goal(member_id=member.id, name="Imported goal")])
    session.rollback()
    assert session.query(Goal).filter_by(name="Imported goal").count() == 0


def test_bulk_insert_mappings_cannot_write_a_goal_without_a_decision(session, member):
    """The dict-shaped sibling of the above, which is what a spreadsheet import actually reaches for."""
    with pytest.raises(PlanMutationWithoutDecision):
        session.bulk_insert_mappings(
            Goal,
            [{"id": "c09-bulk", "member_id": member.id, "name": "Imported", "data_class": 2,
              "created_at": utcnow()}],
        )
    session.rollback()


def test_raw_sql_cannot_write_a_plan_table_without_a_decision(session, member):
    """The one-line fix in a REPL, which is the case `db.py`'s docstring names."""
    from sqlalchemy import text

    for statement in (
        "UPDATE positions SET magnitude = 7 WHERE id = 'anything'",
        "INSERT INTO goals (id, member_id, name, data_class, created_at) "
        "VALUES ('c09-raw', 'x', 'Raw goal', 2, '2026-01-01')",
        "DELETE FROM positions WHERE id = 'anything'",
    ):
        with pytest.raises(PlanMutationWithoutDecision):
            session.execute(text(statement))
        session.rollback()


def test_a_query_level_update_cannot_change_a_plan_row(session, member):
    """`session.query(Position).update(...)` — an ORM API that compiles straight to a statement."""
    with pytest.raises(PlanMutationWithoutDecision):
        session.query(Position).update({"magnitude": 5.0})
    session.rollback()


def test_the_text_dml_parser_resolves_the_shapes_it_claims_to():
    """Guard on the guard, again. If this parser silently resolved nothing, the raw-SQL test above would
    still pass — because the *structural* branch would not fire either and `pytest.raises` would see a
    different error. Positives and negatives, both asserted."""
    from eigentlich.db import _text_dml_target

    assert _text_dml_target("UPDATE positions SET magnitude = 7") == "positions"
    assert _text_dml_target("update  positions  set magnitude = 7") == "positions"
    assert _text_dml_target('UPDATE "positions" SET magnitude = 7') == "positions"
    assert _text_dml_target("UPDATE OR IGNORE positions SET magnitude = 7") == "positions"
    assert _text_dml_target("INSERT INTO goals (id) VALUES ('x')") == "goals"
    assert _text_dml_target("INSERT OR REPLACE INTO goals (id) VALUES ('x')") == "goals"
    assert _text_dml_target("DELETE FROM goals WHERE id = 'x'") == "goals"
    assert _text_dml_target("DELETE FROM main.goals WHERE id = 'x'") == "goals"

    # Negatives: a SELECT, and a statement that only mentions a plan table. Over-matching here would
    # refuse alembic's batch-mode table copy, which reads FROM positions into a temporary table.
    assert _text_dml_target("SELECT * FROM positions") is None
    assert _text_dml_target(
        "INSERT INTO _alembic_tmp_positions (id) SELECT id FROM positions"
    ) == "_alembic_tmp_positions"
    assert _text_dml_target("") is None
    assert _text_dml_target("PRAGMA foreign_keys=ON") is None


def test_the_statement_guard_lets_the_ordinary_plan_path_through(session, member):
    """The other half of every guard: it must not refuse the thing it exists to protect.

    A statement-level guard that blocked the flush as well would be removed within a week, and C-09 with
    it. This is the same write as `test_plan_mutation_with_decision_commits`, kept separate because what
    it proves here is that the flush bracket releases the guard for exactly one flush.
    """
    with mutate_plan(session, member_id=member.id, question="Add?", choice="Yes") as decision:
        goal = Goal(member_id=member.id, name="House deposit")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    assert session.get(Goal, goal.id) is not None

    # And the guard is armed again immediately afterwards.
    with pytest.raises(PlanMutationWithoutDecision):
        session.bulk_save_objects([Goal(member_id=member.id, name="Straight after")])
    session.rollback()


def test_the_statement_guard_survives_a_flush_that_failed(session, member):
    """A63 and A66 were both guards that switched themselves off quietly. This is that failure mode.

    The flush bracket marks the thread as vetted so the unit of work's own SQL can proceed. If a flush
    raises after that mark is set — an IntegrityError from a CHECK constraint, say — and the mark is not
    cleared, every subsequent raw write in that thread walks straight through.
    """
    from sqlalchemy import insert

    with pytest.raises(IntegrityError):
        with mutate_plan(session, member_id=member.id, question="?", choice="!") as decision:
            broken = Position(
                member_id=member.id,
                role="growth",
                capital_type="financial",
                label="No unit",
                magnitude=5.0,  # ck_positions_magnitude_has_unit fires during the flush
            )
            session.add(broken)
            decision.linked_positions.append(broken)
        session.commit()
    session.rollback()

    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(
            insert(Position.__table__).values(
                id="c09-after-failure",
                member_id=member.id,
                role="growth",
                capital_type="financial",
                label="After a failed flush",
                active=True,
                tags={},
                data_class=2,
                created_at=utcnow(),
            )
        )
    session.rollback()


# ============================================================ C-09's escape hatch


def test_a_bare_true_does_not_disable_the_c09_guard(session, member):
    """Finding 12. `session.info[ERASING] = True` was an unauthenticated opt-out of C-09.

    Anything holding the Session could set it and then write plan objects freely. The guard now compares
    against a private token object, so setting the documented key to a plain truthy value does nothing.
    """
    from eigentlich.db import ERASING

    session.info[ERASING] = True
    try:
        session.add(Goal(member_id=member.id, name="Written under a forged erasure flag"))
        with pytest.raises(PlanMutationWithoutDecision):
            session.commit()
    finally:
        session.rollback()
        session.info.pop(ERASING, None)


def test_the_erasure_token_still_stands_the_guard_down(session, member):
    """The exception has to keep working, or R-231's erasure cannot run. The other half of the above."""
    from eigentlich.db import ERASING, _ERASURE_TOKEN

    session.info[ERASING] = _ERASURE_TOKEN
    try:
        session.add(Goal(member_id=member.id, name="Erasure may write"))
        session.commit()
    finally:
        session.info.pop(ERASING, None)


def test_only_erasure_reaches_the_erasure_token():
    """"`services/erasure.py` is the only thing that sets it" — checked, rather than asserted in prose.

    A token object cannot be made unreachable in Python; what it can be made is greppable. This is the
    grep, so a second module acquiring the escape hatch fails the build instead of passing review.
    """
    package = Path(__file__).resolve().parent.parent / "eigentlich"
    users = sorted(
        str(path.relative_to(package)).replace("\\", "/")
        for path in package.rglob("*.py")
        if "_ERASURE_TOKEN" in path.read_text(encoding="utf-8")
    )
    assert users == ["db.py", "services/erasure.py"], (
        f"C-09's escape hatch is reachable from {users}. It is defined in db.py and may be set by "
        f"services/erasure.py and by nothing else; anything else standing the constraint down needs a "
        f"recorded decision, not an import."
    )


# ============================================================ C-06's storage layer, removed
#
# **Eight tests stood here and all eight are gone (A168, 20 September 2026.)** They held C-06's content
# half — that every prepared option carries a label and a consequence — through the paths that skip the
# ORM validator: `bulk_insert_mappings`, raw SQL through the engine, and a MIGRATED database rather than
# a `create_all` one. They were good tests of a real mechanism, and A75 is worth reading for why the
# mechanism had to be a trigger rather than a CHECK.
#
# The owner dropped C-06 with the compliance layer. Nothing now requires an action item to carry options
# at all, so there is nothing here for a test to go round. What the derivation writes is asserted in
# `test_derive.py` instead, as a property of the writer rather than a claim about the store — and that
# is a weaker guarantee, stated as such in both places.
#
# The append-only triggers are unaffected and their migration tests are in `test_adversarial.py`.


# ============================================================ the stock unit, on a MIGRATED database
#
# **Landmine 1 of this build's schema history, and the reason all of these run alembic.** A test-suite pass
# proves nothing about a vocabulary widening: `create_all` builds the schema from the models, so a new enum
# value is always accepted there, while a *migrated* database keeps whatever the migration left. That exact
# difference hid a broken constraint for a week (A63/A68). So the value is written through a raw `sqlite3`
# connection on a database built by `alembic upgrade head`, which is how a deployment builds one.
#
# The finding, recorded because it changes what the migration had to do: `magnitude_unit` was NEVER a CHECK
# constraint. SQLAlchemy Enum defaults to `create_constraint=False`, so it is a bare `VARCHAR(14)` in every
# database this build has produced - read off `sqlite_master` on `backend/eigentlich.db`. The widening
# therefore needed no DDL, and revision `b2c7e5a91f40` says so in its own docstring and raises if that
# premise ever stops holding. What it DID need was `stock_kind`, two new CHECK constraints, and a
# `copy_from` block to keep the existing one.


def test_a_migrated_database_accepts_a_franc_stock(tmp_path):
    """The one that would have caught a stale constraint. A `chf` magnitude, written by raw SQL, on a
    database alembic built.

    **Planted violation, and the first attempt at it is worth recording because it did NOT go red.** Setting
    `create_constraint=True` on `Position.magnitude_unit` left this test green: that flag only changes what
    `create_all` emits, and the migrated column was created by revision `bd3fedd3d5cb` with no CHECK at all.
    So the plant proved the premise rather than the guard.

    The plant that works is the one that reproduces the landmine: a stale unit CHECK in the migration's
    `copy_from` table —
    `CHECK (magnitude_unit IS NULL OR magnitude_unit IN ('chf_per_year', 'share_of_total'))`, which is what a
    database carrying the OLD vocabulary as an enforced constraint looks like. With it in place this test
    failed on `sqlite3.IntegrityError: CHECK constraint failed: ck_positions_magnitude_unit_enum` **while
    `tests/test_stock_unit.py::test_the_api_accepts_a_stock_and_a_liability_and_refuses_an_ambiguous_one`
    passed** — the API accepting a value the deployed store refuses, green suite and all. That is the
    week-long defect, reproduced and removed. Restored.
    """
    import sqlite3

    database, _ = _migrated(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES (:m, 41, :n, :l, 1, :t)",
            {"m": "m-stock", "n": "x", "l": "de-CH", "t": "2026-01-01"},
        )
        connection.execute(
            "INSERT INTO positions (id, member_id, role, capital_type, label, magnitude, "
            "magnitude_unit, stock_kind, tags, active, data_class, created_at) VALUES "
            "(:id, :m, :role, :cap, :label, :mag, :unit, :kind, :tags, 1, 2, :t)",
            {
                "id": "p-stock",
                "m": "m-stock",
                "role": "growth",
                "cap": "financial",
                "label": "Sammlung",
                "mag": 45000.0,
                "unit": "chf",
                "kind": "asset",
                "tags": "{}",
                "t": "2026-01-01",
            },
        )
        connection.commit()
        row = connection.execute(
            "SELECT magnitude, magnitude_unit, stock_kind FROM positions WHERE id = :id",
            {"id": "p-stock"},
        ).fetchone()
        assert row == (45000.0, "chf", "asset"), (
            "a migrated database will not store what the member said they have"
        )
    finally:
        connection.close()


#: The four states `positions` must refuse, and each is a way to store a liability ambiguously - or, in the
#: last case, the invariant that was already there and that a batch recreate drops silently.
AMBIGUOUS_STOCKS = {
    # A franc balance that does not say whether it is owned or owed.
    "no side": (45000.0, "chf", None),
    # A flow with a side of a balance sheet it is not on.
    "flow as a liability": (92000.0, "chf_per_year", "liability"),
    # The second encoding the field exists to remove.
    "negative stock": (-350000.0, "chf", "asset"),
    # ck_positions_magnitude_has_unit, which predates this work.
    "unit with no magnitude": (None, "chf", "asset"),
}


def test_a_migrated_database_refuses_every_ambiguous_liability(tmp_path):
    """The three rules, on the database a deployment runs. Presence of a constraint is what a DDL read can
    see; refusal is the point.

    **Planted violation:** removed the `create_check_constraint` loop from the migration's batch block. All
    four inserts succeeded - a franc balance with no side, a flow marked as a liability, a negative stock,
    and a unit with no magnitude - while the model-level constraints kept `tests/test_stock_unit.py` green.
    This failed four times. Restored.
    """
    import sqlite3

    database, _ = _migrated(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO members (id, age_at_registration, display_name, locale, data_class, created_at) "
            "VALUES (:m, 41, :n, :l, 1, :t)",
            {"m": "m-amb", "n": "x", "l": "de-CH", "t": "2026-01-01"},
        )
        connection.commit()

        for name, (magnitude, unit, kind) in AMBIGUOUS_STOCKS.items():
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                connection.execute(
                    "INSERT INTO positions (id, member_id, role, capital_type, label, magnitude, "
                    "magnitude_unit, stock_kind, tags, active, data_class, created_at) VALUES "
                    "(:id, :m, :role, :cap, :label, :mag, :unit, :kind, :tags, 1, 2, :t)",
                    {
                        "id": "p-amb",
                        "m": "m-amb",
                        "role": "growth",
                        "cap": "financial",
                        "label": name,
                        "mag": magnitude,
                        "unit": unit,
                        "kind": kind,
                        "tags": "{}",
                        "t": "2026-01-01",
                    },
                )
            connection.rollback()
    finally:
        connection.close()


def test_the_stock_unit_migration_leaves_every_append_only_trigger_standing(tmp_path):
    """A63 / A68, on the revision that recreates `positions`.

    `batch_alter_table` copies the table and drops the original, and everything attached to the original
    goes with it. The four append-only triggers are on `decisions` and `curator_session_events` rather than
    on `positions`, so they should survive - and "should" is not a property a migration may rely on, which
    is why `b2c7e5a91f40` re-asserts all four on `op.get_bind()` and why this counts them afterwards.

    **Planted violation:** changed `_restore_triggers` in the migration to
    `op.get_bind().engine.connect()`, which is A68's exact mistake. The triggers survived anyway HERE,
    because they are not on `positions` - so the plant proved this test cannot distinguish that case on this
    revision, and what does distinguish it is that the same run of the whole file keeps
    `test_a_migrated_database_actually_refuses_to_rewrite_a_decision` green. Recorded rather than dressed
    up: a plant that does not go red is a finding about the test. Restored.
    """
    import sqlite3

    database, _ = _migrated(tmp_path)
    connection = sqlite3.connect(database)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        for expected in (
            "trg_decisions_no_update",
            "trg_decisions_no_delete",
            "trg_curator_session_events_no_update",
            "trg_curator_session_events_no_delete",
        ):
            assert expected in names, (
                f"{expected} is missing after migrating to head. The revision that recreates `positions` "
                f"must re-create the triggers ON ITS OWN BIND - `op.get_bind()`, never `.engine`, which "
                f"opens a second connection outside the transaction and turns every CREATE into a no-op."
            )
    finally:
        connection.close()


def test_the_migrated_positions_table_keeps_all_three_check_constraints(tmp_path):
    """SQLite reflection does not return CHECK constraints, so a batch recreate DROPS them silently.

    That is the third landmine and the reason revision `b2c7e5a91f40` passes `copy_from` with the whole
    pre-migration table written out. Read off `sqlite_master` rather than through SQLAlchemy, because the
    reflection that cannot see these constraints is exactly what is not to be trusted here.

    **Planted violation:** removed the `CheckConstraint` and the `Index` from the migration's
    `_positions_before()` table. The migrated `positions` came back without
    `ck_positions_magnitude_has_unit` and without `ix_positions_member_id`; this failed on the first.
    Restored. Both are asserted, because the index went the same way and nothing else would have noticed.
    """
    import sqlite3

    database, _ = _migrated(tmp_path)
    connection = sqlite3.connect(database)
    try:
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'"
        ).fetchone()[0]
        for expected in (
            "ck_positions_magnitude_has_unit",
            "ck_positions_stock_kind_iff_stock",
            "ck_positions_stock_is_not_negative",
        ):
            assert expected in ddl, f"{expected} is not on the migrated table:\n{ddl}"

        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='positions'"
            )
        }
        assert "ix_positions_member_id" in indexes, (
            "the batch recreate dropped the member_id index. With `copy_from`, alembic reflects nothing: "
            "anything left out of the table definition is left out of the database."
        )
    finally:
        connection.close()


def test_the_model_and_the_migration_state_the_same_constraint():
    """The migration pins the stock-unit vocabulary at its own revision, so nothing imports the live tuple
    into it - a migration that read a constant would rewrite its own past. This is what keeps the two
    honest instead: the day a second stock unit is added, this fails until a NEW migration exists.

    **Planted violation:** added `"eur"` to `models.plan.MAGNITUDE_UNITS` and to `STOCK_UNITS`. The model's
    CHECK became `IN ('chf', 'eur')` while the migration's stayed `IN ('chf')`, and this failed - which is
    the required outcome, because a widened vocabulary with no migration behind it is landmine 1 again.

    Adding it to `STOCK_UNITS` alone did something better and worth recording: `models/plan.py` raises at
    import (`STOCK_UNITS names a unit that is not a magnitude unit`), so the whole suite fails to collect.
    The import-time contract catches the incoherent half of that edit before any test runs; this test
    catches the coherent half, which is the one that would otherwise ship. Restored.
    """
    import importlib

    from sqlalchemy import CheckConstraint

    from eigentlich.models.plan import Position

    revision = importlib.import_module(
        "migrations.versions.b2c7e5a91f40_a_stock_of_money_and_a_liability"
    )

    on_the_model = {
        constraint.name: str(constraint.sqltext)
        for constraint in Position.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert on_the_model, "no CHECK constraints were found on the model, so this proves nothing"
    for name, condition in revision.NEW_CHECKS.items():
        assert name in on_the_model, f"the migration adds {name} and the model does not declare it"
        assert on_the_model[name] == condition, (
            f"{name} differs between the model and the migration.\n"
            f"  model:     {on_the_model[name]}\n"
            f"  migration: {condition}\n"
            "A widened vocabulary needs a new migration: the store is what refuses a member's value, and "
            "a model that accepts what the database rejects is landmine 1 of this build."
        )
