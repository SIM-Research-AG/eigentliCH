"""A35 and C-02 — the first AssumptionSet, seeded from the estate's own engines.

Two halves, deliberately separable:

  * `compose` is pure. Given two engine replies it produces the fields of an AssumptionSet and computes
    nothing, so the tests that matter most — no invented number, inflation left NULL, both ids stamped —
    run on a machine with no engines at all.
  * the integration tests run `market_signal` and `return_estimation` for real and check that what was
    written is byte-identical to what the engines published. They are skipped, loudly, when the estate is
    not reachable.

**What is NOT tested here, and why.** `test_illustration_response_always_carries_assumption_set` in
tests/test_constraints.py stays xfail: illustrations live in `services/goals.py`, which returns
`illustration: None` with a reason and is not this change's to edit. The assumption set it will need now
exists, which was the blocker A35 names.
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from eigentlich import engines as engine_module
from eigentlich.engines import DEFAULT_MARKET_SCOPE, call_engine, estate_available
from eigentlich.models import AssumptionSet, NoAssumptionSet
from eigentlich.services.assumptions import (
    OWNER,
    NothingToPublish,
    compose,
    current,
    describe,
    publish,
)

RUN_DATE = date(2026, 8, 30)

needs_estate = pytest.mark.skipif(
    not estate_available(),
    reason=f"the estate at {engine_module.ESTATE_ROOT} is not reachable from this machine",
)


# ---------------------------------------------------------------------------
# A recorded pair of replies, so `compose` can be tested with no estate present.
# Shapes and values are from the real 30 August 2026 run; the arrays are trimmed to what compose reads.
# ---------------------------------------------------------------------------

REGIME_REPLY = {
    "ok": True,
    "engine": "market_signal",
    "contract_type": "RegimeRef",
    "contract": {
        "regime_id": "REG-38d91c1a0da0ef1e",
        "regime_timeline_id": "RTL-38d91c1a0da0ef1e",
        "scope": "Global",
        "as_of": "2024-12-31",
        "model_version": "ms@0.1.0",
        "crisis_tail": 0.28067653638195406,
    },
    "notes": ["blended over: br 5%, ch 5%, cn 25%"],
    "raw": {"months": 177, "first": "2010-01", "last": "2024-12"},
    "idempotency_key": "a08acce35dcb6f96",
    "trace_id": "TR-a08acce35dcb6f96",
    "replay": "cd Macro_Model && <read> output/regime/Global.json",
    "artefact": {"current": {"state": 9, "crisis_tail": 0.28067653638195406, "bimodal": True}},
}

RETURNSET_REPLY = {
    "ok": True,
    "engine": "return_estimation",
    "contract_type": "ReturnSetRef",
    "contract": {
        "return_set_id": "RS-874b03c95f8f77a8",
        "regime_id": "REG-38d91c1a0da0ef1e",
        "scope": "Global",
        "horizon_years": 1.0,
        "as_of": "2024-12-31",
        "model_version": "re@0.2.0",
        "universe_version": "fm@0.2.0",
        "values_unit": "annualised_decimal",
    },
    "notes": [],
    "raw": {"blocks": 8, "coverage": {"seed": 8}},
    "idempotency_key": "874b03c95f8f77a8",
    "trace_id": "TR-874b03c95f8f77a8",
    "replay": "cd Fund_Map && <read> artifacts/rs.json",
    "artefact": {
        "scenarios": ["crisis", "contraction", "stagnation", "expansion", "boom"],
        "role_profiles": {"gain": {"crisis": -0.35813067508492946, "boom": 0.09666666666666666}},
        "house_view": {"crisis": 0.20957597100996284, "boom": 0.1228892482466044},
        "state_grid": 25,
        "state_to_scenario": {"0": "crisis", "24": "boom"},
        "state_to_scenario_version": "sts@0.1.0",
        "provenance": {"series_sources": ["BIS 2026-07-27", "Penn World Table 10.01"]},
    },
}


@pytest.fixture()
def runs():
    return {
        "market_signal": copy.deepcopy(REGIME_REPLY),
        "return_estimation": copy.deepcopy(RETURNSET_REPLY),
    }


# ============================================================ compose: invent no number


def test_the_set_is_stamped_with_both_run_ids(runs):
    """A35. "Stamped with the REG-/RS- ids it came from", so an illustration traces back to a run."""
    fields = compose(runs, run_date=RUN_DATE)
    source = fields["rates"]["source"]

    assert source["market_signal"]["regime_id"] == "REG-38d91c1a0da0ef1e"
    assert source["return_estimation"]["return_set_id"] == "RS-874b03c95f8f77a8"
    assert "REG-38d91c1a" in fields["version"]
    assert "RS-874b03c9" in fields["version"]
    # The crudest and most reliable form of reproducibility: the command, written down.
    assert source["market_signal"]["replay"]
    assert source["return_estimation"]["replay"]


def test_published_by_names_sim_research_and_the_run_date(runs):
    """A35 and C-02. `published_by` is non-nullable: a set with no author is one nobody can be asked about."""
    fields = compose(runs, run_date=RUN_DATE)
    assert fields["published_by"] == f"{OWNER}, run 2026-08-30"


def test_the_version_fits_the_column(runs):
    """`AssumptionSet.version` is String(40) and unique. A version that overflowed would truncate silently."""
    version = compose(runs, run_date=RUN_DATE)["version"]
    assert len(version) <= 40


def test_effective_from_is_the_data_vintage_not_the_day_it_was_read(runs):
    """Stamping the read date would make every rerun a different set for the same numbers."""
    fields = compose(runs, run_date=RUN_DATE)
    assert fields["effective_from"] == date(2024, 12, 31)


def test_inflation_is_published_as_null(runs):
    """§12 / C-02. Neither engine emits an inflation figure, so there is nothing to read and none is invented.

    The field is the one this whole constraint was written about: a plausible Swiss number typed in here
    would look exactly like a measurement and could never be traced to anything.
    """
    fields = compose(runs, run_date=RUN_DATE)
    assert fields["inflation"] is None
    assert "inflation is NULL" in fields["notes"]


def test_every_rate_is_copied_and_not_computed(runs):
    """The A35 promise, asserted by identity rather than by reading the code.

    Each published block must be the engine's own object unchanged. A blend, a rounding or a unit
    conversion anywhere in `compose` would break one of these.
    """
    fields = compose(runs, run_date=RUN_DATE)
    rates = fields["rates"]
    artefact = RETURNSET_REPLY["artefact"]

    assert rates["role_profiles_by_scenario"] == artefact["role_profiles"]
    assert rates["scenario_probabilities"] == artefact["house_view"]
    assert rates["state_to_scenario"] == artefact["state_to_scenario"]
    assert rates["values_unit"] == RETURNSET_REPLY["contract"]["values_unit"]
    assert rates["regime_current"] == REGIME_REPLY["artefact"]["current"]


def test_no_blended_rate_is_published(runs):
    """The deliberate omission. Which probabilities weight which horizon is a decision with an owner.

    Both halves are published side by side and nothing multiplies them, so a reader who wants one number
    has to do the arithmetic and say so. This test is what stops a convenience field creeping in later.
    """
    rates = compose(runs, run_date=RUN_DATE)["rates"]
    forbidden = [key for key in rates if "expected" in key or "blended" in key or key == "rate"]
    assert not forbidden, f"C-02: a composed rate appeared in the set: {forbidden}"
    assert "No blended rate is published" in compose(runs, run_date=RUN_DATE)["notes"]


def test_the_role_naming_mismatch_is_recorded_rather_than_renamed(runs):
    """The estate calls the first role `gain`; §4 and models.plan.ROLES call it `growth`.

    Left as the engine wrote it. A silent rename inside a provenance record is worse than a mismatch
    anyone can see, and the note is where the next reader finds out.
    """
    fields = compose(runs, run_date=RUN_DATE)
    assert "gain" in fields["rates"]["role_profiles_by_scenario"]
    assert "growth" in fields["notes"]


def test_the_horizon_is_recorded_because_the_rates_only_hold_at_it(runs):
    """ReturnSets are keyed on (scope, horizon): a ten-year return is not a one-year return compounded."""
    horizons = compose(runs, run_date=RUN_DATE)["horizons"]
    assert horizons["return_estimation_years"] == RETURNSET_REPLY["contract"]["horizon_years"]
    assert horizons["scope"] == DEFAULT_MARKET_SCOPE
    assert horizons["regime_window"]["months"] == 177


def test_the_engines_own_caveats_survive_into_the_notes(runs):
    """Dropping them would leave the numbers looking better sourced than they are."""
    notes = compose(runs, run_date=RUN_DATE)["notes"]
    assert "blended over: br 5%" in notes


def test_two_vintages_cannot_be_stamped_on_one_set(runs):
    """A ReturnSet estimated under another Regime traces to neither. Refused rather than published."""
    runs["return_estimation"]["contract"]["regime_id"] = "REG-somethingelse"
    with pytest.raises(NothingToPublish) as raised:
        compose(runs, run_date=RUN_DATE)
    assert "REG-somethingelse" in str(raised.value)


# ============================================================ publishing, and refusing to


def test_no_assumption_set_refuses_rather_than_defaulting(session):
    """C-02. An empty table is the honest state, and it must refuse rather than fall back on a rate."""
    with pytest.raises(NoAssumptionSet) as raised:
        current(session)
    assert "publish" in str(raised.value).lower()


def test_nothing_is_published_when_an_engine_will_not_run(session, monkeypatch):
    """A35 and R-302. "If an engine will not run, publish nothing and say so."

    The table must still be empty afterwards. A partly-filled set would be worse than none, because it
    would look complete.
    """
    monkeypatch.setattr(engine_module, "ESTATE_ROOT", engine_module.ESTATE_ROOT / "nowhere")

    with pytest.raises(NothingToPublish) as raised:
        publish(session, run_date=RUN_DATE)
    assert "market_signal" in str(raised.value)

    assert session.query(AssumptionSet).count() == 0
    with pytest.raises(NoAssumptionSet):
        current(session)


def test_describe_carries_the_assumption_set_id(session, runs):
    """C-02. "Every illustration response returns the assumption_set_id used"."""
    fields = compose(runs, run_date=RUN_DATE)
    assumption_set = AssumptionSet(**fields)
    session.add(assumption_set)
    session.commit()

    payload = describe(assumption_set)
    assert payload["assumption_set_id"] == assumption_set.id
    assert payload["version"] == fields["version"]
    assert payload["inflation"] is None


def test_the_published_set_carries_no_engine_artefact(session, runs):
    """R-304 / C-03. The ids travel; the Regime timeline and the ReturnSet payload never do.

    `compose` is handed both artefacts in full. What it writes must be the readings, not the artefact —
    otherwise the first API response that returned an assumption set would serve one.
    """
    fields = compose(runs, run_date=RUN_DATE)
    rates = fields["rates"]

    assert "distributions" not in rates
    assert "path" not in rates
    assert "building_blocks" not in rates
    assert describe(AssumptionSet(**fields))["artefacts_served"] is False


def test_a_second_publication_of_the_same_vintage_is_the_same_row(session, runs, monkeypatch):
    """Idempotent by construction: `version` is derived from the two run ids and is unique on the table."""
    monkeypatch.setattr(
        "eigentlich.services.assumptions._run_world_engines",
        lambda **_: copy.deepcopy(runs),
    )

    first = publish(session, run_date=RUN_DATE)
    session.commit()
    second = publish(session, run_date=date(2026, 9, 1))
    session.commit()

    assert first.id == second.id
    assert session.query(AssumptionSet).count() == 1
    # The run date of the first publication stands. It is a record of when these numbers were taken, and a
    # later read does not re-date them.
    assert second.published_by == f"{OWNER}, run 2026-08-30"


def test_current_returns_the_set_in_effect(session, runs, monkeypatch):
    """C-02's read path. An illustration asks for one and is given the vintage in effect on its date."""
    monkeypatch.setattr(
        "eigentlich.services.assumptions._run_world_engines",
        lambda **_: copy.deepcopy(runs),
    )
    published = publish(session, run_date=RUN_DATE)
    session.commit()

    assert current(session, on=date(2026, 8, 30)).id == published.id
    # Before it was effective, there is nothing — and that refuses rather than reaching backwards.
    with pytest.raises(NoAssumptionSet):
        current(session, on=date(2020, 1, 1))


def test_the_set_is_k0(session, runs):
    """§4 / C-04. An assumption set is published and impersonal: no member's data touched it."""
    from eigentlich.models import DataClass

    assumption_set = AssumptionSet(**compose(runs, run_date=RUN_DATE))
    session.add(assumption_set)
    session.commit()
    assert assumption_set.data_class == int(DataClass.K0)


# ============================================================ against the real engines


@needs_estate
def test_a_set_published_from_the_real_engines_matches_what_they_produced(session):
    """A35 end to end: two engines run, one set written, every number traceable to a `REG-`/`RS-` id.

    The equality checks are the point. They re-read the artefacts through `call_engine` and compare, so a
    transformation introduced into `compose` later fails here rather than shipping as a plausible number.
    """
    assumption_set = publish(session, run_date=RUN_DATE)
    session.commit()

    source = assumption_set.rates["source"]
    assert source["market_signal"]["regime_id"].startswith("REG-")
    assert source["return_estimation"]["return_set_id"].startswith("RS-")
    assert assumption_set.published_by == f"{OWNER}, run 2026-08-30"
    assert assumption_set.inflation is None

    returnset = call_engine(
        "return_estimation",
        {
            "scope": DEFAULT_MARKET_SCOPE,
            "horizon_years": engine_module.DEFAULT_RETURNSET_HORIZON_YEARS,
            "publish": False,
            "regime_id": source["market_signal"]["regime_id"],
        },
        include_artefact=True,
    )
    assert assumption_set.rates["role_profiles_by_scenario"] == returnset["artefact"]["role_profiles"]
    assert assumption_set.rates["scenario_probabilities"] == returnset["artefact"]["house_view"]
    assert assumption_set.rates["values_unit"] == returnset["contract"]["values_unit"]


@needs_estate
def test_the_published_rates_are_all_real_numbers_from_the_engine(session):
    """No placeholder survived into the set: every published profile is a float the Fund Map computed."""
    assumption_set = publish(session, run_date=RUN_DATE)
    session.commit()

    profiles = assumption_set.rates["role_profiles_by_scenario"]
    assert profiles, "nothing was published, so this test proves nothing — see A20"
    for role, by_scenario in profiles.items():
        assert by_scenario, f"{role} carries no profile"
        for scenario, value in by_scenario.items():
            assert isinstance(value, float), f"{role}/{scenario} is {value!r}"

    probabilities = assumption_set.rates["scenario_probabilities"]
    assert set(probabilities) <= set(assumption_set.rates["scenarios"])
