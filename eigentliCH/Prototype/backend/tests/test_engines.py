"""§7 — the engine manifests and the wired `call_engine`. R-300 to R-305, C-03.

The manifest tests pass because the owner was declared (A10). They were failing by design before that,
which is what "an engine without a manifest is not callable" is supposed to feel like.

The wiring tests are new. Two kinds, kept apart deliberately:

  * the **refusals** — R-300, R-301, R-302, R-303 — run with no estate at all. A constraint that only holds
    when seven engines happen to be installed is not a constraint, and these are the tests that would catch
    the wiring being loosened on a machine where nothing can run anyway.
  * the **integration** tests actually start the estate under its own interpreter and read a Regime back.
    They are skipped, loudly, when the estate is not reachable — see `test_the_estate_survey_is_recorded`
    for what was found on 30 August 2026.
"""

from __future__ import annotations

import logging

import pytest

from eigentlich import engines as engine_module
from eigentlich.engines import (
    DEFAULT_MARKET_SCOPE,
    EngineNotAvailable,
    EngineOnRequestThread,
    MEMBER_REFERENCE_REDACTION,
    ManifestMissing,
    UndeclaredInput,
    attempt,
    call_engine,
    estate_available,
    known_engines,
    load_manifest,
    mark_request_thread,
    redacted,
)

#: R-305: the inventory found in the estate, reported before wiring any of them.
ESTATE_ENGINES = (
    "life_balance_sheet",
    "market_signal",
    "portfolio_optimiser",
    "s_curve_trajectory",
    "scenario_generator",
    "score_engine",
    "return_estimation",
)

#: R-305, the second half: what each one *did* when it was run, on 30 August 2026, before anything was
#: wired. All seven have a venv, all seven respond, all seven produced a schema-valid contract. Recorded
#: here rather than only in a report, because the July 2026 directory move left stale absolute paths
#: elsewhere in the estate (PHASE-0-SURVEY.md) and this is the assertion that would notice the next one.
SURVEY_2026_08_30 = {
    "market_signal": "RegimeRef REG-38d91c1a0da0ef1e, 177 months 2010-01 to 2024-12, blended over 7 economies",
    "return_estimation": "ReturnSetRef RS-874b03c95f8f77a8 under that Regime, 8 blocks, coverage seed",
    "portfolio_optimiser": "Recommendation against mandate fixture_balanced, conditions met",
    "life_balance_sheet": "Trajectory over 121 monthly steps, deterministic, no confidence band",
    "s_curve_trajectory": "Trajectory over 25 macro states with a weighted-quantile band",
    "scenario_generator": "Scenario comparing a raised contribution against its base",
    "score_engine": "Score 75.75 of 100 over 14 events, tier Optimisation",
}


needs_estate = pytest.mark.skipif(
    not estate_available(),
    reason=f"the estate at {engine_module.ESTATE_ROOT} is not reachable from this machine",
)


# ============================================================ R-300, R-305: the inventory


def test_every_estate_engine_has_a_manifest():
    """R-300 / R-305. The seven found in `engines/base.py::ENGINE_HOMES`, none missing."""
    assert set(known_engines()) == set(ESTATE_ENGINES)


@pytest.mark.parametrize("name", ESTATE_ENGINES)
def test_manifest_declares_an_ip_owner(name):
    """R-300. A10: SIM Research owns all seven, declared 2026-08-30."""
    manifest = load_manifest(name)
    assert manifest.ip_owner == "SIM Research"
    assert manifest.timeout_s > 0
    assert manifest.outputs["contract"]
    assert manifest.inputs


def test_unknown_engine_is_not_callable():
    with pytest.raises(ManifestMissing):
        load_manifest("does_not_exist")


def test_the_estate_survey_is_recorded():
    """R-305: report the inventory found in the estate before wiring any of them.

    A record rather than a check of behaviour. It exists so that "all seven ran" is a claim with a date and
    a result against it, and so the next person can diff their own survey against this one.
    """
    assert set(SURVEY_2026_08_30) == set(ESTATE_ENGINES)
    assert all(SURVEY_2026_08_30[name] for name in ESTATE_ENGINES)


def test_portfolio_optimiser_output_is_flagged_for_c01():
    """C-01. The optimiser produces a Recommendation — ranked instruments — so its call sites are gated."""
    manifest = load_manifest("portfolio_optimiser")
    assert manifest.outputs["contract"] == "Recommendation"
    assert "C-01" in manifest.notes


def test_score_engine_is_marked_as_not_a_game_mechanic():
    """A6. The name collides with C-07; the manifest is where a reader finds out why it is allowed."""
    manifest = load_manifest("score_engine")
    assert "C-07" in manifest.notes


def test_an_undeclared_input_is_refused(monkeypatch):
    """R-300. The manifest is the statement of what an engine takes, and nothing travels past it.

    Checked before the estate is touched, so it holds on a machine with no engines installed.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    with pytest.raises(UndeclaredInput) as raised:
        call_engine("market_signal", {"scope": "Global", "annual_return": 0.05})
    assert "annual_return" in str(raised.value)


# ============================================================ R-301: never on a request thread


@pytest.mark.parametrize("name", ESTATE_ENGINES)
def test_no_engine_may_run_on_a_request_thread(name):
    """R-301. Every engine in the estate is over the two-second budget, so this holds for all seven."""
    manifest = load_manifest(name)
    assert not manifest.callable_on_request_thread, (
        f"{name} declares {manifest.timeout_s}s — if an engine ever drops under the budget, this test "
        f"should be the thing that makes someone think about it rather than a silent fast path"
    )

    mark_request_thread(True)
    try:
        with pytest.raises(EngineOnRequestThread):
            call_engine(name, {})
    finally:
        mark_request_thread(False)


def test_the_request_thread_refusal_survives_the_wiring(monkeypatch):
    """R-301, restated against the wired path rather than against the stub it replaced.

    The refusal must come *before* anything is launched. Asserted by pointing the estate at a directory
    that does not exist: if the subprocess were reached first, this would raise `EngineNotAvailable`
    instead, and the request thread would already have paid for a process start.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")
    mark_request_thread(True)
    try:
        with pytest.raises(EngineOnRequestThread):
            call_engine("market_signal", {"scope": DEFAULT_MARKET_SCOPE})
    finally:
        mark_request_thread(False)


def test_a_worker_thread_is_not_a_request_thread():
    """The flag is thread-local, so a queued worker is not caught by a request that set it elsewhere."""
    import threading

    seen: list[bool] = []
    mark_request_thread(True)
    try:
        worker = threading.Thread(target=lambda: seen.append(engine_module.on_request_thread()))
        worker.start()
        worker.join()
    finally:
        mark_request_thread(False)
    assert seen == [False]


# ============================================================ R-302: degrade the screen, never the session


def _unreachable(monkeypatch):
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")


def test_a_missing_estate_raises_rather_than_returning_a_number(monkeypatch):
    """R-302. The failure is an exception, not a result — there is no zero to mistake for a measurement."""
    _unreachable(monkeypatch)
    with pytest.raises(EngineNotAvailable) as raised:
        call_engine("market_signal", {"scope": DEFAULT_MARKET_SCOPE})
    assert "no estate interpreter" in str(raised.value)


def test_attempt_renders_as_not_available_and_never_as_a_zero(monkeypatch):
    """R-302. "A failed engine renders as 'not available', not as a zero."

    Asserted literally: the failure payload is scanned for any numeric value at all. A screen that reads a
    `0` out of an engine response cannot tell it apart from a measurement, so there must be nothing there
    to read.
    """
    _unreachable(monkeypatch)
    outcome = attempt("market_signal", {"scope": DEFAULT_MARKET_SCOPE})

    assert outcome["available"] is False
    assert outcome["reason"]
    assert "result" not in outcome
    numeric = [key for key, value in outcome.items() if isinstance(value, (int, float)) and not isinstance(value, bool)]
    assert not numeric, f"R-302: a failed engine returned numbers a screen could render: {numeric}"


def test_a_failed_engine_does_not_end_the_session(monkeypatch):
    """R-302's second half. The next call still works — nothing was left in a broken state."""
    _unreachable(monkeypatch)
    assert attempt("market_signal", {"scope": DEFAULT_MARKET_SCOPE})["available"] is False
    assert attempt("return_estimation", {"scope": DEFAULT_MARKET_SCOPE})["available"] is False
    assert load_manifest("market_signal").ip_owner == "SIM Research"


def test_attempt_does_not_swallow_a_defect_in_this_codebase(monkeypatch):
    """R-301 and R-300 are not degradable. Catching them would hide a broken constraint behind a message."""
    _unreachable(monkeypatch)
    with pytest.raises(UndeclaredInput):
        attempt("market_signal", {"not_an_input": 1})

    mark_request_thread(True)
    try:
        with pytest.raises(EngineOnRequestThread):
            attempt("market_signal", {"scope": DEFAULT_MARKET_SCOPE})
    finally:
        mark_request_thread(False)


# ============================================================ R-303: logged without the member reference


def test_the_member_reference_is_stripped_from_a_nested_payload():
    """R-303. Recursive, because engine payloads nest — `control` for the Life Balance Sheet."""
    payload = {
        "household_id": "M-42",
        "scope": "Global",
        "regime_id": "REG-abc",
        "control": {"member_id": "M-42", "theta": 0.45},
        "goals": [{"goal_id": "G-1", "target": 100}],
    }
    clean = redacted(payload)

    assert clean["household_id"] == MEMBER_REFERENCE_REDACTION
    assert clean["control"]["member_id"] == MEMBER_REFERENCE_REDACTION
    assert clean["goals"][0]["goal_id"] == MEMBER_REFERENCE_REDACTION
    # The world's own identifiers stay: they name a vintage, not a person, and they are what makes a run
    # reproducible without exposure.
    assert clean["regime_id"] == "REG-abc"
    assert clean["scope"] == "Global"
    assert clean["control"]["theta"] == payload["control"]["theta"]


def test_engine_inputs_are_logged_without_the_member_reference(monkeypatch, caplog):
    """R-303, at the call site rather than on the helper.

    The input line is written before the estate is reached, so this holds on a machine with no engines:
    the engine fails, and the log line that was already emitted still carries no member reference.
    """
    _unreachable(monkeypatch)
    caplog.set_level(logging.INFO, logger="eigentlich.engines")

    attempt("life_balance_sheet", {"household_id": "M-secret-42", "W_L": 1})

    written = "\n".join(record.getMessage() for record in caplog.records)
    assert written, "nothing was logged, so this test proves nothing — see A20 on vacuous checks"
    assert "M-secret-42" not in written
    assert MEMBER_REFERENCE_REDACTION in written
    # Reproducibility without exposure: the engine and its version are still there to look up.
    assert "life_balance_sheet" in written


# ============================================================ the wired path, against the real estate


@needs_estate
def test_market_signal_returns_a_real_regime():
    """§7 wired. The estate runs under its own interpreter and a typed Regime comes back.

    Asserts the shape and the `REG-` prefix rather than a value: the value is a vintage and will change the
    next time the Regime is republished, and a test that pinned it would fail for the right reason at the
    wrong time.
    """
    reply = call_engine("market_signal", {"scope": DEFAULT_MARKET_SCOPE, "publish": False})

    assert reply["contract_type"] == "RegimeRef"
    assert reply["contract"]["regime_id"].startswith("REG-")
    assert reply["contract"]["regime_timeline_id"].startswith("RTL-")
    assert reply["contract"]["scope"] == DEFAULT_MARKET_SCOPE
    assert reply["model_version"] == load_manifest("market_signal").model_version
    # The crudest and most reliable form of reproducibility: the command, written down.
    assert reply["replay"]
    assert reply["trace_id"].startswith("TR-")


@needs_estate
def test_return_estimation_is_checked_against_the_regime_it_was_estimated_under():
    """The invariant the estate enforces, asserted here because C-02 stamps both ids on an AssumptionSet."""
    regime = call_engine("market_signal", {"scope": DEFAULT_MARKET_SCOPE, "publish": False})
    returnset = call_engine(
        "return_estimation",
        {
            "scope": DEFAULT_MARKET_SCOPE,
            "horizon_years": engine_module.DEFAULT_RETURNSET_HORIZON_YEARS,
            "publish": False,
            "regime_id": regime["contract"]["regime_id"],
        },
    )

    assert returnset["contract"]["return_set_id"].startswith("RS-")
    assert returnset["contract"]["regime_id"] == regime["contract"]["regime_id"]


@needs_estate
def test_a_returnset_estimated_under_another_regime_is_refused():
    """A mismatch surfaces at the engine boundary rather than deep inside a consumer.

    This is the one test that proves the refusal reaches back across the bridge: the estate raises, and
    this side turns it into `EngineNotAvailable` rather than into a plausible-looking result.
    """
    with pytest.raises(EngineNotAvailable) as raised:
        call_engine(
            "return_estimation",
            {
                "scope": DEFAULT_MARKET_SCOPE,
                "horizon_years": engine_module.DEFAULT_RETURNSET_HORIZON_YEARS,
                "publish": False,
                "regime_id": "REG-0000000000000000",
            },
        )
    assert "REG-0000000000000000" in str(raised.value) + raised.value.detail


@needs_estate
def test_the_world_engines_read_no_member_data():
    """A35's premise, checked rather than assumed.

    A Regime and a ReturnSet are properties of the world. If either took a household reference this would
    not be a legitimate seed for an assumption set, because the numbers would be somebody's.
    """
    for name in ("market_signal", "return_estimation"):
        declared = set(load_manifest(name).inputs)
        assert not declared & engine_module.MEMBER_REFERENCE_KEYS, (
            f"{name} declares a member reference among its inputs, so it is not household-independent "
            f"and A35 does not apply to it"
        )
