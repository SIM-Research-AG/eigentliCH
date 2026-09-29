"""The submissions and the engines use the same letters for different quantities. Written down, once.

`client/submissions/*.json` each carry a `state` block of single-letter symbols — `W_L`, `W_R`, `D`, `H`,
`N`, `E` — which look exactly like the Life Balance Sheet's input names and are the obvious thing to wire
together. **Two of them mean the opposite of what the engine means.**

    W_L   engine: human capital as a stock in francs
          submission: LIQUID FINANCIAL WEALTH — cash plus securities, verified arithmetically below

    E     engine: a state variable of personal_alm's own model, with no counterpart in Position or Goal
          submission: the EXPERTISE SCALE, 0..1, which services/identities.learning_commitment_scale
          reproduces

Nothing in this build maps the two, which is the only reason it has not bitten. A member's savings
arriving in an engine as their human capital would not fail: it would produce a plausible number that is
wrong, for every member at once, and the first sign of it would be a household being told its goal is
unreachable.

This file is the guard. It is a test rather than a comment because a comment does not run.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

SUBMISSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "client", "submissions", "*.json",
)

#: Every symbol the submissions' `state` block and the engines both use, with what each side means by it.
#:
#: **A registry rather than a fix**, and the distinction is deliberate. The engine contract may not be
#: renamed — §9 of the build manual says wrap the engine, do not reinterpret it — and the submissions are
#: source data written by somebody else. So the collision cannot be removed; it can only be known about.
#: A new collision fails `test_no_undocumented_collision` rather than sitting in a file nobody re-reads.
KNOWN_COLLISIONS = {
    "W_L": {
        "engine": "human capital as a stock in francs",
        "submission": "the member's liquid financial wealth — cash plus securities in nine of the ten submissions, and in the tenth those plus a stated gold holding. Not perfectly consistent between files about what counts as liquid; consistently NOT human capital",
        "same_thing": False,
    },
    "D": {
        "engine": "debt",
        "submission": "debt",
        # The one that agrees. Kept in the registry precisely because "they all disagree" would be the
        # wrong lesson: a reader has to check each, and this is the evidence that checking was done.
        "same_thing": True,
    },
    "E": {
        "engine": "a state variable of personal_alm with no counterpart in Position or Goal",
        "submission": "the expertise scale, 0..1",
        "same_thing": False,
    },
    # **Found by this guard rather than by reading**, which is the argument for having it. The engine's
    # subject for W_R is the member's financial capital. The submissions' W_R is 0 for a member holding
    # 101'500 of securities, so it is certainly NOT financial capital — a strong negative.
    #
    # What it IS cannot be established from these six: every value is 0 or null. It tracks
    # `property_total` exactly, which is consistent with real-estate wealth and equally consistent with
    # anything else that happens to be zero everywhere. Recorded as undetermined rather than guessed,
    # because a registry whose purpose is to stop a wrong mapping must not contain one.
    "W_R": {
        "engine": "the member's financial capital as an amount",
        "submission": "not financial capital; undetermined beyond that — every value in the six is 0 or "
                      "null, and it is 0 where securities are 101'500",
        "same_thing": False,
    },
}


def _submissions():
    found = sorted(glob.glob(SUBMISSIONS))
    if not found:
        pytest.skip("client/submissions is gitignored and empty in this checkout")
    return [json.load(open(path, encoding="utf-8")) for path in found]


def _engine_input_names() -> set[str]:
    """Every engine input name this build has a member-facing subject for.

    `befund.GAP_SUBJECTS` is the right source and not a convenient one: it is the table the Befund raises
    on when an engine declares a plan-blocking input nobody has written a subject for, so it is kept
    complete by a guard of its own. Walking `engine_inputs` for dicts with a `declared_as` key was the
    first attempt and it found nothing — the names are built inside the per-engine builder functions, so
    a structural scan comes back empty and the guard passes vacuously, which is the failure mode this
    whole file is about.
    """
    from eigentlich.services.befund import GAP_SUBJECTS

    return set(GAP_SUBJECTS)


#: Other franc assets a submission can state. A `W_L` above cash and securities has to be explained by
#: one of these to count as liquid wealth rather than as something else.
_OTHER_LIQUID = ("gold_value", "crypto_value", "collectibles_value")


def test_the_submission_state_block_means_liquid_wealth_by_W_L():
    """The claim the registry rests on, checked arithmetically rather than asserted.

    **Cash plus securities is the usual composition and not the definition.** Nine of the ten submissions
    match it exactly. One — `onb@0.1.2`, the member with 30'000 in cash and no securities — reports
    `W_L: 130'000`, and the difference is precisely their stated `gold_value` of 100'000. Another file
    states gold and crypto and does *not* fold them in. So the submissions are not perfectly consistent
    with each other about what counts as liquid, and the honest test is that every franc of `W_L` is
    accounted for by franc assets the member stated — not that the arithmetic is always the same two
    fields.

    What this still catches is the thing that matters: a `W_L` that is not the member's liquid financial
    wealth at all. The engine's `W_L` is human capital, and if the submissions ever meant that, the
    figure would bear no relation to anything on this list.
    """
    checked, explained = 0, []
    for document in _submissions():
        state = document.get("state") or {}
        raw = document.get("raw") or {}
        if state.get("W_L") is None:
            continue
        checked += 1

        base = (raw.get("cash") or 0) + (raw.get("securities") or 0)
        if state["W_L"] == base:
            continue

        remainder = state["W_L"] - base
        available = {name: (raw.get(name) or 0) for name in _OTHER_LIQUID}
        match = next((name for name, value in available.items() if value == remainder), None)
        assert match, (
            f"W_L is {state['W_L']}, cash + securities is {base}, and the remaining {remainder} matches "
            f"none of the member's other stated franc assets {available}. The submissions' W_L is no "
            f"longer their liquid financial wealth, and KNOWN_COLLISIONS says it is."
        )
        explained.append((state["W_L"], match))

    assert checked >= 6
    # Stated rather than asserted away: if the submissions start folding other assets in routinely, this
    # is where the registry's wording needs revisiting.
    assert len(explained) <= 1, (
        f"{len(explained)} submissions now fold other assets into W_L: {explained}. The entry in "
        f"KNOWN_COLLISIONS describes it as cash plus securities and should be reworded."
    )


def test_the_submission_state_block_means_the_expertise_scale_by_E():
    """Checked where it is checkable, which is not everywhere — and the exception is itself worth knowing.

    `learning_commitment_scale` — called `expertise_scale` until 6 September 2026 — reads the four
    STRUCTURED education answers and returns `None` when a submission
    carries none of them. Two of the six carry none: Elio states no `E` either, which is consistent, but
    **Yasmin's submission states `E: 0.7` that her own answers cannot produce**. Her file is marked
    `source: profile-document-reconstruction`, so that figure was set by whoever reconstructed the profile
    rather than derived from anything she answered. It is not a defect in the scale; it is a reminder that
    two of these six are reconstructions and one of them carries a number with no working behind it.
    """
    from eigentlich.services.identities import learning_commitment_scale

    checked = 0
    unreproducible = []
    for document in _submissions():
        state = document.get("state") or {}
        raw = document.get("raw") or {}
        if state.get("E") is None:
            continue
        computed = learning_commitment_scale(raw)
        if computed is None:
            unreproducible.append(state["E"])
            continue
        assert state["E"] == computed, (
            "the submissions' E is no longer the learning-commitment scale, and KNOWN_COLLISIONS "
            "says it is"
        )
        checked += 1

    assert checked >= 4, f"only {checked} submissions could be checked; the claim rested on four"
    # Stated, not asserted away: if a third reconstruction appears this is where it shows up.
    assert len(unreproducible) <= 1, (
        f"{len(unreproducible)} submissions state an E their own answers cannot produce: {unreproducible}"
    )


def test_the_submissions_W_R_is_not_the_engines_financial_capital():
    """The negative that the registry entry rests on, which is the only half that is establishable.

    A member holding securities and reporting `W_R: 0` settles that the two are different quantities. It
    does not settle what the submissions mean by it, and this test deliberately does not claim to.
    """
    contradicted = False
    for document in _submissions():
        state = document.get("state") or {}
        raw = document.get("raw") or {}
        financial = (raw.get("cash") or 0) + (raw.get("securities") or 0)
        if state.get("W_R") == 0 and financial > 0:
            contradicted = True
    assert contradicted, (
        "no submission any longer contradicts W_R meaning financial capital. The registry entry says one "
        "does; re-establish what the submissions mean by W_R before anything maps it."
    )


def test_no_undocumented_collision():
    """A symbol used by both sides and named in neither the registry nor the engine's own reason."""
    engine_names = _engine_input_names()
    if not engine_names:
        pytest.skip("no engine input declarations found to compare against")

    state_keys: set[str] = set()
    for document in _submissions():
        state_keys |= set(document.get("state") or {})

    overlapping = state_keys & engine_names
    undocumented = overlapping - set(KNOWN_COLLISIONS)
    assert not undocumented, (
        f"{sorted(undocumented)} appear in both a submission's `state` block and the engine inputs, and "
        f"are not in KNOWN_COLLISIONS. Establish what each side means before anything maps them: two of "
        f"the three documented ones mean opposite quantities."
    )


def test_nothing_maps_a_submission_state_block_to_an_engine():
    """The mapping this file exists to prevent, asserted over the source.

    Reads the AST rather than the text, because a guard that greps for a word matches its own docstring —
    three did exactly that this week (A120).
    """
    import ast

    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eigentlich"
    )
    tools = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools"
    )

    offences = []
    for base in (root, tools):
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                tree = ast.parse(open(path, encoding="utf-8").read())
                for node in ast.walk(tree):
                    # `something["state"]` followed anywhere by a subscript with a colliding symbol is
                    # the shape. Checked as: any string constant that is a known collision key, used as
                    # a subscript index, in a file that also subscripts "state".
                    if not isinstance(node, ast.Subscript):
                        continue
                    index = node.slice
                    if not isinstance(index, ast.Constant) or index.value not in KNOWN_COLLISIONS:
                        continue
                    if KNOWN_COLLISIONS[index.value]["same_thing"]:
                        continue
                    offences.append(f"{os.path.relpath(path, base)}:{node.lineno} [{index.value!r}]")

    assert not offences, (
        "a colliding symbol is being read by subscript: " + "; ".join(offences) + ". Two of the three "
        "mean opposite quantities on the two sides, so a mapping by name feeds a member's savings to an "
        "engine as their human capital."
    )
