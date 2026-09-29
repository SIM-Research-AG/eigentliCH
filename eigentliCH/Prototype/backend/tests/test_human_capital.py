"""E, N and H — what derives, what does not, and what happens when health is taken away.

**The reconstruction is the load-bearing test.** The network formula was recovered by fitting values
someone set by hand in August, so the thing that must not silently change is those six people's numbers.
If a future edit to the record moves them, that is a decision and it should fail here first.
"""
from __future__ import annotations

import json
import math

import pytest

from eigentlich.services import human_capital as hc


def _answers(**kwargs):
    return kwargs


# ============================================================ the gate


def test_the_record_is_signed():
    """Signed on 6 September 2026. Four figures were accepted as working assumptions rather than as
    measurements, and the record says which four and in whose words."""
    about = hc.parameters()["_about"]
    assert about["provisional"] is False
    assert about["published_by"]
    assert about["published_on"] == "2026-09-06"
    assert len(about["accepted_as_working_assumptions"]) == 2
    # Two of the four presented for signature turned out to be `identities`' published conventions
    # rather than judgements of this house, and the sign-off note says so rather than quietly dropping
    # them.
    assert len(about["not_ours_after_all"]) == 2
    assert "Two of those four turned out not to need signing" in about["sign_off"]


def test_signing_did_not_erase_the_warnings_on_what_was_signed():
    """**The point of an accepted assumption is that it is still an assumption.**

    Each of the four keeps its own caveat where a reader of that section will meet it, not only in the
    sign-off note. A signature that quietly deleted them would be the worst outcome of asking for one.
    """
    record = hc._record()
    for warning in (record["network"]["reach"]["no_source"],
                    record["health"]["eingeschraenkt_why"]):
        assert "guess" in warning.lower(), warning[:60]
    # and the correction that removed the other two is stated, not silently applied
    assert "was wrong" in record["network"]["correction"]
    assert "identities.net_scale" in record["network"]["owned_by"]


def test_an_unsigned_record_still_refuses(monkeypatch):
    """The gate is not decoration: strip the publisher and nothing may be computed."""
    record = hc._record()
    record = {**record, "_about": {**record["_about"], "provisional": True, "published_by": None}}
    monkeypatch.setattr(hc, "_record", lambda: record)
    with pytest.raises(hc.HumanCapitalNotApproved):
        hc.parameters()


def test_a_record_that_is_not_provisional_but_unsigned_also_refuses(monkeypatch):
    record = hc._record()
    record = {**record, "_about": {**record["_about"], "provisional": False, "published_by": None}}
    monkeypatch.setattr(hc, "_record", lambda: record)
    with pytest.raises(hc.HumanCapitalNotApproved):
        hc.parameters()


# ============================================================ health


@pytest.mark.parametrize("stated,expected", [
    ("1", 1.0), ("1 — sehr gut", 1.0), ("0.85", 0.85), ("0.7", 0.7), ("0.5", 0.5),
    ("eingeschränkt", 0.35), (0.9, 0.9),
])
def test_health_is_read_directly(stated, expected):
    """The intake question already asks for the number the engine wants."""
    assert hc.health(_answers(health=stated)).value == pytest.approx(expected)


def test_the_ten_members_health_values_all_map():
    """Checked against the real ten on 6 September 2026 and matched every one."""
    for stated in ("0.95", "1", "0.7", "0.9", "0.85", "1.0"):
        assert hc.health(_answers(health=stated)).known


def test_health_withheld_returns_none_and_names_the_direction_of_the_error():
    """**The K3 condition, asserted rather than documented.**

    A caller that loses H must survive it, and must know which way the resulting error points.
    """
    got = hc.health(_answers(health="0.7"), k3_permitted=False)
    assert got.value is None
    assert got.absent_because == hc.WITHHELD
    assert "OVERSTATES" in got.note


def test_an_unpublished_health_level_is_absent_rather_than_guessed():
    got = hc.health(_answers(health="mittelmässig"))
    assert got.value is None and got.absent_because == hc.NOT_ANSWERED


# ============================================================ network — the reconstruction


@pytest.mark.parametrize("name,people,mandates,recorded", [
    ("Levin", 18, 0, 0.89),
    ("Marvin", 20, 0, 0.92),
    ("Renzo", 10, 0, 0.71),
    ("Elia", 5, 0, 0.46),
    ("Reto", 5, 5, 0.64),
])
def test_the_recovered_formula_reproduces_the_hand_set_values(name, people, mandates, recorded):
    """**The six numbers someone set in August, and the rule fitted to them.**

    Tolerance is 0.01 — the fit is that good on four of the five. Reto is the only member carrying
    mandates and therefore determines the mandate weight entirely, which is why the record calls that
    figure a guess wearing a decimal point.
    """
    got = hc.network(_answers(network_people=people, mandates=mandates))
    assert got.value == pytest.approx(recorded, abs=0.01), name


def test_the_knee_the_record_describes_is_the_knee_the_formula_has():
    """The record tells a member «the first eight people bring two thirds». It must be true."""
    record = hc._record()
    knee = record["network"]["knee"]
    for people, expected in ((8, knee["at_8_people"]), (16, knee["at_16_people"]),
                             (24, knee["at_24_people"])):
        got = hc.network(_answers(network_people=people)).value
        assert got == pytest.approx(expected, abs=0.01), f"{people} people"


def test_mandates_alone_are_computed_and_flagged():
    """0.06 a mandate to a ceiling of 0.18, which is `identities`' published convention."""
    got = hc.network(_answers(mandates=4))
    assert got.known
    assert got.value == pytest.approx(0.18, abs=0.005), "the mandate ceiling"
    assert "0.06" in got.note


def test_no_network_answer_at_all_is_absent_not_zero():
    """A110 — a person nobody asked is not a person with no network."""
    got = hc.network(_answers())
    assert got.value is None and got.absent_because == hc.NOT_ANSWERED


# ============================================================ expertise — the honest refusal


def test_free_text_education_alone_is_still_absent():
    """**The method never changed; the source did.**

    A free-text education answer cannot be mapped, and «Maschinenbauingenieur, MBA» is the member the
    hand-scoring skipped. What closes this is the structured question, not a cleverer reading.
    """
    got = hc.expertise(_answers(education="Maschinenbauingenieur, MBA"))
    assert got.value is None
    assert got.absent_because == hc.NOT_ASKED
    assert "free text" in got.note


@pytest.mark.parametrize("category,expected", [
    ("Universitäre Hochschule", 1.0),
    ("Fachhochschule FH", 0.9571),
    ("Höhere Berufsausbildung", 0.8861),
    ("Berufsausbildung (EFZ)", 0.6309),
    ("Unternehmensinterne Ausbildung", 0.519),
])
def test_the_ladder_is_the_bfs_ladder(category, expected):
    """Each rung is the E that reproduces that qualification's published median. Bare, with no
    recency or experience modifier, the rung is the anchor itself."""
    got = hc.expertise(_answers(qualification_highest=category))
    assert got.known
    assert got.value == pytest.approx(expected, abs=0.001)


def test_the_rungs_are_ordered_the_way_the_published_medians_are():
    record = hc._record()["expertise"]["anchors"]
    medians = record["bfs_monthly_median_ohne_kader"]
    rungs = record["by_qualification"]
    by_median = sorted(medians, key=lambda k: medians[k])
    by_rung = sorted(rungs, key=lambda k: rungs[k])
    assert by_median == by_rung


def test_an_old_qualification_decays_and_ongoing_training_clears_it():
    """The one modifier the BFS table cannot support, kept small and marked as ours."""
    rung = "Höhere Berufsausbildung"
    old = hc.expertise(_answers(qualification_highest=rung, qualification_year=1990,
                                _today_year=2026))
    fresh = hc.expertise(_answers(qualification_highest=rung, qualification_year=1990,
                                  education_recent="CAS Data Engineering", _today_year=2026))
    assert old.value < fresh.value
    anchors = hc._record()["expertise"]["anchors"]["by_qualification"]
    assert fresh.value == pytest.approx(anchors[rung])


def test_nein_does_not_count_as_ongoing_training():
    """Two members answered «nein» to the training question, and «nein» is not a course."""
    rung = "Höhere Berufsausbildung"
    said_no = hc.expertise(_answers(qualification_highest=rung, qualification_year=1990,
                                    education_recent="nein", _today_year=2026))
    blank = hc.expertise(_answers(qualification_highest=rung, qualification_year=1990,
                                  _today_year=2026))
    assert said_no.value == blank.value


@pytest.mark.parametrize("answer", ["Zauberlehrling", "Maturität", "Doktorat",
                                    "obligatorische Schule"])
def test_a_qualification_with_no_published_median_is_absent(answer):
    """**Including three that an earlier draft of this record invented rungs for.**

    Maturität, Doktorat and obligatorische Schule have no separate median in the BFS table. Placing
    them on a neighbouring rung is exactly the guessing the source removed.
    """
    got = hc.expertise(_answers(qualification_highest=answer))
    assert got.value is None
    assert "no published median" in got.note


# ============================================================ all three together


def test_capitals_reports_what_is_missing_and_why():
    got = hc.capitals(_answers(network_people=10, mandates=0, health="0.85"))
    assert got.missing == ["E"]
    assert not got.complete
    assert got.as_kwargs()["N"] == pytest.approx(0.71, abs=0.01)
    assert any("expertise is unknown" in c for c in got.caveats)


def test_the_kwargs_are_exactly_what_the_engine_takes():
    """A drift between these names and `HouseholdPosition` would be found at runtime, not here."""
    got = hc.capitals(_answers(health="1"))
    assert set(got.as_kwargs()) == {"E", "N", "H"}


def test_withholding_health_leaves_the_other_two_intact():
    """**The condition the record sets: a consumer must survive H's removal.**"""
    with_h = hc.capitals(_answers(network_people=10, health="0.7"))
    without = hc.capitals(_answers(network_people=10, health="0.7"), k3_permitted=False)
    assert without.N.value == with_h.N.value
    assert without.H.value is None
    assert any("overstated" in c for c in without.caveats)


# ============================================================ the time budget


def test_working_hours_become_a_share_of_the_productive_week():
    """100 hours, decided 3 August 2026 — at 50 the overwork threshold would land at 25 a week."""
    got = hc.time_budget(_answers(hours_per_week=41))
    assert got.productive_week_hours == 100
    assert got.tau_Y == pytest.approx(0.41)
    assert got.hours(got.tau_Y) == pytest.approx(41)


def test_a_rest_band_is_read_at_its_convention_and_says_so():
    got = hc.time_budget(_answers(hours_per_week=40, rest_hours="10–20"))
    assert got.tau_H == pytest.approx(0.15)
    assert any("band" in c for c in got.caveats)


def test_learning_and_networking_hours_are_absent_rather_than_residual():
    """**Splitting the leftover would invent the number the whole model turns on.**"""
    got = hc.time_budget(_answers(hours_per_week=40, rest_hours="10–20"))
    assert got.tau_E is None and got.tau_N is None
    assert got.sources["tau_E"] == hc.ABSENT
    assert got.leisure is None, "a residual computed over holes is a lie"


def test_reto_trips_both_the_ceiling_and_the_overwork_threshold():
    """He states 75 hours a week against a hard ceiling of 70 and a threshold of 50."""
    got = hc.time_budget(_answers(hours_per_week=75, rest_hours="10–20"))
    assert any("hard ceiling" in c for c in got.caveats)
    assert any("accelerates health decay" in c for c in got.caveats)


def test_levin_trips_the_recovery_floor():
    """«kaum welche» reads as 3 hours against a floor of 5."""
    got = hc.time_budget(_answers(hours_per_week=41, rest_hours="kaum welche"))
    assert got.tau_H == pytest.approx(0.03)
    assert any("below the model's floor" in c for c in got.caveats)


# ============================================================ the record itself


def test_the_record_does_not_restate_the_engines_dynamics():
    """One constant written twice is a divergence waiting to happen.

    The mapping belongs here; `alpha_E`, `alpha_N`, `alpha_H`, the decay and the income equation belong
    to `personal_alm.model.params` and must not be duplicated into content.

    **Keys and not substrings.** The record NAMES these constants in prose, twice on purpose: once to say
    it does not hold them, and once to carry the `alpha_H` re-normalisation condition the calibration
    register calls not optional. A substring test fails on the documentation that makes the rule true,
    which is the wrong thing to break. What must not exist is a key that assigns one a value.
    """
    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    record = json.loads(json.dumps(hc._record()))
    # The one deliberate exception, removed before the walk: `calibration.unchanged` records the engine
    # values this calibration RELIES on rather than replaces. That is a copy, so it could drift -- and
    # `test_the_record_agrees_with_the_engine_about_what_it_did_not_change` is what makes drift loud.
    record["earning_power"]["calibration"].pop("unchanged")

    present = set(keys(record))
    for owned_by_the_engine in ("alpha_E", "alpha_N", "alpha_H", "delta_H", "earning_power_min",
                                "earning_power_max", "K_E", "K_N", "K_H", "a", "b", "c"):
        assert owned_by_the_engine not in present, owned_by_the_engine


def test_the_record_agrees_with_the_engine_about_what_it_did_not_change():
    """**The copy is permitted only because this test exists.**

    `calibration.unchanged` names the engine constants the BFS derivation relied on. If the engine moves
    one of them, every rung on the ladder is wrong and nothing else would say so.
    """
    _, Params = hc._engine()
    if Params is None:
        pytest.skip("the Life Balance Sheet engine is not reachable from this build")
    engine = Params()
    for name, value in hc._record()["earning_power"]["calibration"]["unchanged"].items():
        assert getattr(engine, name) == pytest.approx(value), name


def test_the_alpha_h_renormalisation_condition_is_carried_not_lost():
    """The calibration register calls it «not optional», so it travels with the record."""
    note = hc._record()["time"]["returns"]["tau_H"]["implementation_condition"]
    assert "alpha_H" in note and "not optional" in note.lower()


# ============================================================ earning power — the calibration


def _engine_or_skip():
    engine, _ = hc._engine()
    if engine is None:
        pytest.skip("the Life Balance Sheet engine is not reachable from this build")


#: The published table, both columns. Source: BFS, Schweizerische Lohnstrukturerhebung — Löhne 2024,
#: BFS-Pressekonferenz Bern 25.11.2025, reproduced in knowledge/BFS_Lohnstrukturerhebung.md.
BFS_TABLE = [
    ("Universitäre Hochschule", 8645, 14409),
    ("Fachhochschule FH", 8342, 11701),
    ("Höhere Berufsausbildung", 7849, 10489),
    ("Berufsausbildung (EFZ)", 6162, 8252),
    ("Unternehmensinterne Ausbildung", 5456, 6989),
]


@pytest.mark.parametrize("qualification,ohne_kader,mit_kader", BFS_TABLE)
def test_the_calibration_reproduces_the_published_table(qualification, ohne_kader, mit_kader):
    """**The whole point of the BFS source, asserted against both of its columns.**

    Ten published cells, reproduced to within five francs a month. A fully developed network is passed
    because the ladder is anchored at N = 1; the BFS table has no network dimension, so that is the
    only honest place to anchor it.
    """
    _engine_or_skip()
    # A network at the application's own ceiling of 0.98, which is what the ladder is anchored to.
    base = {"network_people": 1000, "health": "1", "age": 40,
            "qualification_highest": qualification}
    plain = hc.earning_power(base)
    kader = hc.earning_power({**base, "kader": "Oberes oder mittleres Kader"})
    assert plain.monthly_standardised == pytest.approx(ohne_kader, abs=5), "ohne Kaderfunktion"
    assert kader.monthly_standardised == pytest.approx(mit_kader, abs=5), "oberes/mittleres Kader"


def test_the_conversion_between_the_two_working_time_conventions():
    """**The easiest thing in this record to get wrong.**

    BFS full time is 40 hours a week; the engine's tau_Y = 1 is 100. And the monthly figure already
    contains 1/12 of the 13th month, so a year is twelve of them and not thirteen.
    """
    _engine_or_skip()
    working = hc._record()["earning_power"]["working_time"]
    assert working["factor"] == working["months_per_year"] / (
        working["bfs_full_time_hours_per_week"] / working["model_productive_week_hours"])
    got = hc.earning_power({"qualification_highest": "Universitäre Hochschule",
                            "network_people": 1000, "health": "1", "age": 40})
    assert got.annual_at_forty_hours == pytest.approx(got.monthly_standardised * 12, rel=1e-6)
    assert got.at_full_productive_week == pytest.approx(
        got.annual_at_forty_hours / 0.4, rel=1e-6)


def test_a_missing_capital_refuses_rather_than_guesses():
    """E or N unknown means no earning power at all. Health is different — it multiplies income
    rather than earning power, so its absence is a caveat and not a refusal."""
    _engine_or_skip()
    assert hc.earning_power({"network_people": 10, "health": "1", "age": 40}) is None, "no E"
    assert hc.earning_power({"qualification_highest": "Fachhochschule FH", "health": "1",
                             "age": 40}) is None, "no N"
    without_health = hc.earning_power({"qualification_highest": "Fachhochschule FH",
                                       "network_people": 10, "age": 40})
    assert without_health is not None
    assert any("overstated" in c for c in without_health.caveats)


def test_an_unstated_management_function_is_not_assumed():
    """The modest reading, and it is named as a caveat because the BFS table shows the function is
    worth more than the qualification."""
    _engine_or_skip()
    got = hc.earning_power({"qualification_highest": "Universitäre Hochschule",
                            "network_people": 1000, "health": "1", "age": 40})
    assert got.multiplier == 1
    assert got.responsibility == "ohne Kaderfunktion"
    assert any("no management function was stated" in c for c in got.caveats)


def test_reach_lifts_a_small_but_far_reaching_network_and_never_lowers_one():
    """**The fix for the member the count could not read.**

    Ueli names three contacts and earns 280'000. Three names from someone who runs a company is not
    the same network as three from someone starting out, and unanswered must leave N exactly where the
    reconstruction put it.
    """
    counted = hc.network(_answers(network_people=3))
    for reach in hc._record()["network"]["reach"]["multipliers"]:
        lifted = hc.network(_answers(network_people=3, network_reach=reach))
        assert lifted.value >= counted.value, reach
    far = hc.network(_answers(network_people=3, network_reach="über die Branche hinaus"))
    assert far.value > counted.value
    assert hc.network(_answers(network_people=3, network_reach="etwas anderes")).value ==         pytest.approx(counted.value), "an unpublished reach must not silently change N"


def test_unanswered_reach_leaves_the_reconstruction_untouched():
    """Every one of the six hand-set values was fitted against the count alone."""
    for people, mandates, recorded in ((18, 0, 0.89), (20, 0, 0.92), (10, 0, 0.71),
                                       (5, 0, 0.46), (5, 5, 0.64)):
        got = hc.network(_answers(network_people=people, mandates=mandates))
        assert got.value == pytest.approx(recorded, abs=0.01)


# ============================================================ top management, by sector


#: BFS, LSE 2024 — «Topmanager/-innen», the 10 % of upper Kader who earn most, per sector.
TOPMANAGER = [
    ("Banken", 59332), ("Pharmaindustrie", 51571), ("Versicherungen", 35832),
    ("Informationstechnologie", 30060), ("Maschinenbau", 24134), ("Beherbergung", 11487),
    ("Gastronomie", 9960),
]


@pytest.mark.parametrize("sector,published", TOPMANAGER)
def test_top_management_reproduces_the_published_sector_figure(sector, published):
    """**Why the sector is asked at all.** Between Gastronomie and Banken lies a factor of six, and a
    single whole-economy number hid all of it. A university graduate in each sector lands exactly on
    that sector's published figure."""
    _engine_or_skip()
    got = hc.earning_power({"qualification_highest": "Universitäre Hochschule",
                            "network_people": 1000, "health": "1", "age": 45,
                            "kader": "Oberste Führung", "sector": sector})
    assert got.monthly_standardised == pytest.approx(published, abs=15)


def test_top_management_without_a_sector_falls_back_and_says_it_is_not_a_middle_value():
    """24'000 for the whole economy sits next to Maschinenbau, not between the extremes."""
    _engine_or_skip()
    got = hc.earning_power({"qualification_highest": "Universitäre Hochschule",
                            "network_people": 1000, "health": "1", "age": 45,
                            "kader": "Oberste Führung"})
    assert got.monthly_standardised == pytest.approx(24000, abs=15)
    assert any("not a middle value" in c for c in got.caveats)


def test_an_unpublished_sector_falls_back_rather_than_guessing():
    _engine_or_skip()
    got = hc.earning_power({"qualification_highest": "Universitäre Hochschule",
                            "network_people": 1000, "health": "1", "age": 45,
                            "kader": "Oberste Führung", "sector": "Zirkus"})
    assert got.monthly_standardised == pytest.approx(24000, abs=15)
    assert any("no published figure" in c for c in got.caveats)


def test_the_extrapolation_down_the_ladder_is_named():
    """The BFS publishes top management by sector and NOT by education, so every qualification other
    than «Universitäre Hochschule» is an extrapolation and must say so."""
    _engine_or_skip()
    got = hc.earning_power({"qualification_highest": "Berufsausbildung (EFZ)",
                            "network_people": 1000, "health": "1", "age": 45,
                            "kader": "Oberste Führung", "sector": "Banken"})
    assert any("extrapolation" in c.lower() for c in got.caveats)


def test_the_sector_does_nothing_at_the_other_two_tiers():
    """**Sector and education are not independent, so applying both would double-count.**

    A sector's median already contains that sector's education mix. The sector is therefore used in the
    one place the education table is silent, and nowhere else.
    """
    _engine_or_skip()
    base = {"qualification_highest": "Universitäre Hochschule", "network_people": 1000,
            "health": "1", "age": 45}
    for tier in (None, "Oberes oder mittleres Kader"):
        answers = dict(base) if tier is None else {**base, "kader": tier}
        plain = hc.earning_power(answers)
        with_sector = hc.earning_power({**answers, "sector": "Banken"})
        assert plain.monthly_standardised == pytest.approx(with_sector.monthly_standardised)


def test_the_multipliers_are_ordered_the_way_the_published_figures_are():
    tier = hc._record()["responsibility"]["tiers"]["topmanagement"]
    published, multipliers = tier["bfs_monthly_by_sector"], tier["multiplier_by_sector"]
    assert sorted(published, key=lambda k: published[k]) == \
        sorted(multipliers, key=lambda k: multipliers[k])
