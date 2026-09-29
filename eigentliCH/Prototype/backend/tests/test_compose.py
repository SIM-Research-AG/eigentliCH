"""The composing contract: what an answer written by the model must and must not do.

**The counterpart to `test_know.py`, which tests the quoting contract this replaced.** C-11 was reversed
on 21 September 2026 by the owner, with the trade stated; `services/compose.py` carries the reasoning and
what it costs. What is tested here is everything that did NOT become negotiable in that reversal:

- the member's own record reaches the answer, and only on the branch that permits it;
- the model is asked in German and the answer comes back in German;
- a computation's figures are handed over as settled, and its service is cited;
- the two C-11 checks still run, as an audit on the record rather than as a gate;
- an unreachable model is still reported as unreachable rather than guessed around.

The model is stubbed throughout, as it is next door, so these pass with nothing running.
"""

from __future__ import annotations

import pytest

from eigentlich import llm
from eigentlich.services import compose
from eigentlich.services.know import Passage


# ---------------------------------------------------------------- the German the member reads


def test_the_du_forms_a_word_swap_can_repair_are_repaired():
    """Every measured local model siezt for two sentences and then slips.

    A slip is not worth refusing an otherwise sound answer over, and it is also not something a member of
    a Swiss financial application should read — so it is repaired, and counted.
    """
    text, repaired, unrepaired = compose.siezen("Dein Kapital und deine Ziele. Ich helfe dir dabei.")
    assert text == "Ihr Kapital und Ihre Ziele. Ich helfe Ihnen dabei."
    assert repaired == 3
    assert unrepaired == 0


def test_the_polite_forms_are_capitalised_wherever_they_stand():
    """`Ihre` is the polite possessive and `ihre` means "their". Mid-sentence is where it matters."""
    text, _, _ = compose.siezen("Das betrifft deine Ziele und deinem Plan.")
    assert "Ihre Ziele" in text and "Ihrem Plan" in text
    assert "ihre" not in text


def test_du_is_left_alone_and_counted_because_a_swap_cannot_conjugate():
    """Planted violation: adding `("du", "Sie")` to `_SIEZEN` turns this green and produces «Sie hast».

    The verb agrees with the pronoun. A substitution that cannot conjugate makes German that is worse
    than what it replaced, so the honest move is to leave it and report it.
    """
    text, repaired, unrepaired = compose.siezen("Du hast das gut gemacht.")
    assert text == "Du hast das gut gemacht."
    assert repaired == 0
    assert unrepaired == 1


def test_words_that_merely_begin_like_a_du_form_are_untouched():
    text, repaired, _ = compose.siezen("Dadurch, dies und der Dirigent bleiben.")
    assert repaired == 0
    assert text == "Dadurch, dies und der Dirigent bleiben."


def test_an_answer_that_leaves_german_is_detected():
    """The measured failure: `qwen2.5:14b` wrote two sentences of German and then switched to Chinese.

    Detected on script rather than on a language model, because the drift is not subtle and a detector
    that needs a model to run cannot run when the model is the thing that failed.
    """
    assert compose.drifted("Ihre Vorsorge beträgt CHF 90'000.") == 0
    assert compose.drifted("Ihre Vorsorge 您的养老金缺口是多少") > 0


def test_a_model_that_leaves_german_twice_yields_no_answer_rather_than_the_drift(monkeypatch):
    """One retry, then nothing. A member is not shown half a page in a script they did not ask in."""
    calls = []

    def _always_chinese(prompt, **kwargs):
        calls.append(prompt)
        return llm.Reply(text="您的养老金缺口是多少", model="stub")

    monkeypatch.setattr(llm, "chat", _always_chinese)
    written = compose.answer([_passage()], question="Wie hoch ist meine Rente?")
    assert written.text == ""
    assert written.audit["left_german_after_retry"] > 0
    assert len(calls) == 2, "one retry, not a loop: drift is a property of the model, not of the draw"


def test_the_retry_carries_an_instruction_the_first_call_did_not(monkeypatch):
    replies = iter([
        llm.Reply(text="Ihre Rente 您的养老金", model="stub"),
        llm.Reply(text="Ihre Rente beträgt laut den Unterlagen nichts Bekanntes.", model="stub"),
    ])
    seen = []

    def _drift_then_recover(prompt, **kwargs):
        seen.append(prompt)
        return next(replies)

    monkeypatch.setattr(llm, "chat", _drift_then_recover)
    written = compose.answer([_passage()], question="Wie hoch ist meine Rente?")
    assert written.text.startswith("Ihre Rente beträgt")
    assert "vollständig auf Deutsch" in seen[1]
    assert written.audit["left_german_then_retried"] > 0


# ---------------------------------------------------------------- the grounding the model is given


def _passage(title="Merkblatt 2.03", text="Der Bezug kann um ein bis fünf Jahre aufgeschoben werden."):
    return Passage(kind="book_passage", source_id="x#1", title=title, text=text, score=700)


class _Computed:
    determined = True
    key = "retirement_provision"
    text = "Ihr Guthaben beträgt 500'000 und ergibt eine Rente von 34'200 im Jahr."
    inputs = {"pillar2": 500000}
    sources = ["services/pension_projection"]
    caveats = ["Nur das Obligatorium."]


def test_a_computation_is_given_to_the_model_as_settled_and_first(monkeypatch):
    """The arithmetic is not the model's, and a constraint stated after nine paragraphs is not a constraint.

    Both halves matter: the figures appear, and they appear before the prose the model might reason from.
    """
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda prompt, **k: (seen.update(prompt=prompt), llm.Reply("Ihre Rente.", "s"))[1])
    compose.answer([_passage()], question="Wie hoch ist meine Rente?", computed=_Computed())

    prompt = seen["prompt"]
    assert "BERECHNET" in prompt
    assert "34'200" in prompt
    assert "Nur das Obligatorium." in prompt
    assert prompt.index("BERECHNET") < prompt.index("UNTERLAGEN"), (
        "the settled arithmetic must lead; a model that has read six passages first has already started "
        "reasoning about them"
    )


def test_the_system_prompt_forbids_the_arithmetic_that_went_wrong(monkeypatch):
    """Both measured errors, pinned: summing a salary into a balance, and duzen.

    Planted violation: dropping rule 4 from `SYSTEM_DE` and re-running the fifty questions reproduced
    «Ihr Vermögen beträgt CHF 840'000» on a member whose balances are 560'000 and whose salary is 280'000.
    """
    assert "RECHNEN SIE NICHT" in compose.SYSTEM_DE
    assert "Bestände" in compose.SYSTEM_DE and "Flüsse" in compose.SYSTEM_DE
    assert "SIEZEN" in compose.SYSTEM_DE


def test_the_passages_are_numbered_so_a_marker_can_name_one(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda prompt, **k: (seen.update(p=prompt), llm.Reply("Antwort [1].", "s"))[1])
    written = compose.answer([_passage(), _passage(title="Zweites")],
                             question="Was gilt?")
    assert "[1] Merkblatt 2.03" in seen["p"]
    assert "[2] Zweites" in seen["p"]
    assert written.used == (1,)


def test_a_marker_the_grounding_does_not_have_is_not_reported_as_used(monkeypatch):
    """A model that writes [7] over two passages has cited nothing, and must not appear to have cited."""
    monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply("Antwort [7] und [2].", "s"))
    written = compose.answer([_passage(), _passage(title="Zweites")], question="Was gilt?")
    assert written.used == (2,)


# ---------------------------------------------------------------- the audit that used to be a gate


def test_the_two_c11_checks_still_run_and_are_recorded_rather_than_enforced(monkeypatch):
    """The honest measure of what the reversal costs, per answer.

    Under C-11 either of these refused the answer outright. The answer is now returned and the numbers
    are written into its record, so a curator can see how far from the sources it went.
    """
    monkeypatch.setattr(llm, "chat",
                        lambda *a, **k: llm.Reply("Ihre Rente beträgt CHF 123'456 im Jahr.", "s"))
    written = compose.answer([_passage()], question="Wie hoch ist meine Rente?")

    assert written.text, "the answer is returned, not refused"
    assert "123'456" in written.audit["unverifiable_figures"], (
        "a figure in no source must be recorded as such — this is the whole of what replaced the gate"
    )
    assert written.audit["unquoted"] >= 1


def test_an_unreachable_model_raises_rather_than_returning_something(monkeypatch):
    """Not available is never a guess, on this path exactly as on the quoting one."""
    def _down(*a, **k):
        raise llm.LocalModelUnavailable("daemon is not running")

    monkeypatch.setattr(llm, "chat", _down)
    with pytest.raises(llm.LocalModelUnavailable):
        compose.answer([_passage()], question="Was gilt?")


def test_composing_uses_its_own_model_and_not_the_one_chosen_for_reading(monkeypatch):
    """`qwen2.5:14b` was chosen for returning three integers and writes Chinese when asked for prose.

    Pinned because the defect it guards was exactly a default leaking across: `know.ask` passed
    `model or llm.DEFAULT_MODEL` and silently overrode the model this module measured and chose.
    """
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda p, **k: (seen.update(k), llm.Reply("Antwort.", "s"))[1])
    compose.answer([_passage()], question="Was gilt?")
    assert seen["model"] == compose.MODEL
    assert compose.MODEL != llm.DEFAULT_MODEL, (
        "if these ever become the same model, it must be because one was measured to do both jobs"
    )


# ---------------------------------------------------------------- the boundary, which did not move
#
# `member_ground` is new grounding and therefore a new way for a member's figures to reach a prompt. The
# permission is on the route, exactly as the vault's is. These are the tests that say so mechanically
# rather than in the module docstring, because a docstring is not a guard.


def _positions_for(session, member, *, amount=500000):
    """One recorded balance, with the Decision C-09 requires. A bare `session.add` is refused."""
    from eigentlich.models import STOCK_UNIT, Position
    from eigentlich.services.plan import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Position erfassen?",
                     choice="Ja") as decision:
        position = Position(member_id=member.id, role="growth", capital_type="financial",
                            label="Pensionskasse", magnitude=amount,
                            magnitude_unit=STOCK_UNIT, stock_kind="asset", active=True)
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    return position


def test_the_members_own_figures_reach_a_question_about_themselves(session, member, monkeypatch):
    from eigentlich.services import know, member_ground

    _positions_for(session, member)
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda p, **k: (seen.update(prompt=p), llm.Reply("Ihre Vorsorge.", "s"))[1])
    know.ask(session, member_id=member.id, question="Wie hoch ist mein Vorsorgekapital?")

    assert "Pensionskasse" in seen["prompt"], (
        "the whole point: a question about this member is answered with this member's record in front of "
        "the model, and before this change it never was"
    )
    assert member_ground.KIND == "member_record"


def test_a_question_about_the_world_never_sees_them(session, member, monkeypatch):
    """Planted violation: calling `member_ground.passages` unconditionally in `ask` turns this red.

    The failure this guards is not a leak to a stranger — it is the product reading somebody's balance
    sheet to answer a question about how a rule works, which crosses the first boundary to answer
    something that sits below it.
    """
    from eigentlich.services import know

    _positions_for(session, member)
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda p, **k: (seen.update(prompt=p), llm.Reply("Die AHV.", "s"))[1])
    know.ask(session, member_id=member.id,
             question="Wie funktioniert die Plafonierung der AHV-Renten für Ehepaare?")

    prompt = seen.get("prompt", "")
    assert "Pensionskasse" not in prompt
    assert "500'000" not in prompt


def test_the_quoting_path_is_given_no_member_record_either(session, member, monkeypatch):
    """C-11's shape has nowhere to put a table of francs: a quoted answer can only quote a sentence.

    So the record is retrieved only while composing. Stated as a test because "it would not have helped
    anyway" is an argument about today's renderer, and this is an argument about the code.
    """
    from eigentlich.services import know

    monkeypatch.setattr(know, "ANSWER_MODE", "quote")
    _positions_for(session, member)
    passages = know.retrieve(session, member_id=member.id, question="Wie hoch ist mein Vorsorgekapital?")
    assert all(p.kind != "member_record" for p in passages)


def test_goals_with_and_without_a_target_date_sort_together(session, member):
    """Planted violation: `key=lambda g: (g.target_date or g.created_at, ...)` — which is what it was.

    `target_date` is a `date` and `created_at` is a `datetime`, and Python refuses to order the two. So a
    member holding one dated goal and one undated goal raised `TypeError` out of `member_ground.sections`,
    which `know.ask` does not catch — the question would have 500'd rather than been answered.

    Every unit test gave its goals the same shape, so nothing here saw it. It was found by building the
    sections for all 83 members of the development database, where it failed on the fourth.
    """
    from datetime import date

    from eigentlich.models import Goal
    from eigentlich.services import member_ground
    from eigentlich.services.plan import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Ziele erfassen?", choice="Ja") as decision:
        dated = Goal(member_id=member.id, name="Eigenheim", target_date=date(2033, 12, 31))
        undated = Goal(member_id=member.id, name="Reserve")
        session.add_all([dated, undated])
        decision.linked_goals.extend([dated, undated])
    session.commit()

    sections = member_ground.sections(session, member_id=member.id)
    goals = next(s for s in sections if s.key == "goals")
    assert len(goals.lines) == 2
    assert goals.lines[0].startswith("Eigenheim"), "the dated goal leads; the undated one follows"
    assert goals.lines[1].startswith("Reserve")


def test_the_composing_call_asks_the_model_not_to_think(monkeypatch):
    """A latency decision, and the one that made 50 of 60 real questions fail.

    `qwen3:8b` spends its budget on a hidden chain before it writes. Measured on one prompt: 52.7 seconds
    and 1'164 characters of reasoning for a 452-character answer, against 18.1 seconds and 458 characters
    with thinking off — three times the wall clock for an answer the same length, and the reasoning is
    thrown away.

    It went unnoticed until the grounding got richer and the whole run stopped coming back inside the
    timeout. Fifty of sixty members were told «Das lokale Modell läuft gerade nicht», which was true as
    far as the code could see and false as a description of what had happened.
    """
    seen = {}
    monkeypatch.setattr(llm, "chat",
                        lambda p, **k: (seen.update(k), llm.Reply("Antwort.", "s"))[1])
    compose.answer([_passage()], question="Was gilt?")
    assert seen.get("think") is False


def test_the_timeout_leaves_room_for_the_grounding_that_is_now_sent(monkeypatch):
    """90 seconds was set when the prompt was six passages of prose and no member record.

    It now carries the member's own record and their stated plan as well, and a timeout is reported to the
    member as an unavailable model — which reads as an installation problem rather than as a budget that
    is too small. Pinned so that lowering it is a decision rather than a leftover.
    """
    assert compose.TIMEOUT_S >= 150


def test_the_audit_counts_the_computed_block_as_a_source(monkeypatch):
    """Otherwise it accuses the one part of the answer that is fully derived.

    Measured on the run of 60: the answer with the most "unverifiable" figures was a property
    affordability case whose eight flagged numbers — the deposit, the carrying cost, the multiple of
    income — were every one of them produced by `services/property` through `computations`. They are the
    most traceable figures in the answer, and the audit was calling them inventions because it looked
    only at retrieved prose.

    Planted violation: dropping the computed block from `checked` puts `34'200` back in the list.
    """
    monkeypatch.setattr(llm, "chat",
                        lambda *a, **k: llm.Reply("Ihre Rente beträgt 34'200 im Jahr.", "s"))
    written = compose.answer([_passage()], question="Wie hoch ist meine Rente?", computed=_Computed())
    assert written.audit["unverifiable_figures"] == [], (
        "34'200 is in the computed block that was handed to the model; it is not an invention"
    )


def test_a_figure_in_neither_the_passages_nor_the_computation_is_still_caught(monkeypatch):
    """The other half, so the test above is not just a weaker check wearing a docstring."""
    monkeypatch.setattr(llm, "chat",
                        lambda *a, **k: llm.Reply("Ihre Rente beträgt 99'999 im Jahr.", "s"))
    written = compose.answer([_passage()], question="Wie hoch ist meine Rente?", computed=_Computed())
    assert "99'999" in written.audit["unverifiable_figures"]


def test_a_model_that_is_slow_is_not_reported_as_a_model_that_is_absent(session, member, monkeypatch):
    """Two states that were one sentence, and the sentence named the wrong one.

    Fifty of sixty members were told «Das lokale Modell läuft gerade nicht» on 21 September 2026. It was
    running the whole time; it was reasoning past a budget set when the prompt was half the size. That
    sentence sends whoever reads it to check an installation that is fine, and never mentions the thing
    to change.
    """
    from eigentlich.services import know

    def _slow(*a, **k):
        raise llm.LocalModelTooSlow("did not finish within 180s")

    monkeypatch.setattr(llm, "chat", _slow)
    answer = know.ask(session, member_id=member.id, question="Wie hoch ist mein Vorsorgekapital?")
    assert "länger gebraucht" in answer.text
    assert "läuft gerade nicht" not in answer.text
    assert answer.unavailable is True, "it is still a non-answer, and still says so"


def test_a_daemon_that_is_absent_still_says_so(session, member, monkeypatch):
    """The other half. Planted violation: raising `LocalModelTooSlow` here turns this red."""
    from eigentlich.services import know

    def _down(*a, **k):
        raise llm.LocalModelUnavailable("connection refused")

    monkeypatch.setattr(llm, "chat", _down)
    answer = know.ask(session, member_id=member.id, question="Wie hoch ist mein Vorsorgekapital?")
    assert "läuft gerade nicht" in answer.text
