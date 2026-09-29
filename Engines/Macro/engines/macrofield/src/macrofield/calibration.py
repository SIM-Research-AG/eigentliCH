"""Seed calibrations: the versioned parameter sets the store is initialised with.

A calibration is immutable once stored. Changing any value here for an existing version is
refused at start-up; a change is a new version, proposed through ``PUT /calibration`` or
added below with ``parent_version`` set.

Version 1.0.0 reproduces the ``macrofield`` build (eigentliCH/engines/Macro_Model, state of
2026-08-03) as its golden reference, fudge factors included, by decision of 2026-09-27. Every
value below says where it comes from, so a later version can replace a judgement with evidence
knowingly rather than by accident. The judgements are:

* ``credit_uplift = 1.4``. Author's assessment of 2026-07-27: BIS credit to the non-financial
  sector omits credit to the financial sector and much non-bank intermediation, so it is
  scaled until the United States reads about 3.5. Level only: it moves no growth rate, turning
  point or cross-sectional ordering. Prior range 1.25 to 1.55.
* ``capital_target = 0.9``. Penn World Table puts K_R/Y at 3 to 6, where the investment share
  r = 1 - K_R/Y is negative and the equations do not integrate. Both capital stocks are scaled
  by one common factor so the window maximum of K_R/Y is 0.9. K_R/K_I, and with it the Phase 4
  test, is unchanged; K/Y and r are not, which is the point.
* The ``*_scale`` corrections in the fit (fitting.py) measure how far the section 0.2
  definitions are from the equations of motion. They are reported, not constrained.
* ``phases.optimisation_saturation_ceiling = 3.5``, raised from the brief's 3.0 on 2026-07-27
  to coincide with the balanced band's upper bound (book section 8.5).

Economy settings for BR, CH, CN, DE, GB, IN, JP and US are the ``macrofield`` economy files.
Those for ES, ID, MY and TH are new in this engine (marked "assumed" in their notes) and are
open decisions. EU, PH, BD and VN are registered so the HoNI universe is complete, and are
reported unavailable with the missing input named: nothing is filled.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import (
    Bounds,
    Calibration,
    CrisisReset,
    DefaultsSpec,
    EconomySpec,
    InflationSpec,
    ResetSpec,
    ResolutionPolicy,
    SaturationCeiling,
    ValuationsSpec,
)

_MACROFIELD = "prototype economy file"

ECONOMIES: tuple[EconomySpec, ...] = (
    EconomySpec(code="BR", name="Brazil", world_bank="BRA", bis="BR", pwt="BRA",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06, note=_MACROFIELD),
    EconomySpec(code="CH", name="Switzerland", world_bank="CHE", bis="CH", pwt="CHE",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05, note=_MACROFIELD),
    EconomySpec(code="CN", name="China", world_bank="CHN", bis="CN", pwt="CHN",
                stimulus_proxy="net_new_credit", stimulus_reverse_sign=False,
                depreciation_prior=0.06,
                note=(f"{_MACROFIELD}. Net new credit, because local-government financing "
                      "vehicles and policy-bank lending do not appear in the fiscal balance.")),
    EconomySpec(code="EU", name="European Union", world_bank="EMU", bis="XM", pwt=None,
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05,
                note=("Penn World Table publishes no capital stock for the euro area, so K_R "
                      "has no source. The old build proxied it by DE 0.6 / FR 0.4; that proxy "
                      "is not carried over. See the data need.")),
    EconomySpec(code="IN", name="India", world_bank="IND", bis="IN", pwt="IND",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06, note=_MACROFIELD),
    EconomySpec(code="ID", name="Indonesia", world_bank="IDN", bis="ID", pwt="IDN",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="assumed: fiscal proxy and the emerging-economy prior of BR, CN and IN"),
    EconomySpec(code="MY", name="Malaysia", world_bank="MYS", bis="MY", pwt="MYS",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="assumed: fiscal proxy and the emerging-economy prior of BR, CN and IN"),
    EconomySpec(code="PH", name="Philippines", world_bank="PHL", bis=None, pwt="PHL",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="BIS publishes no total credit series, so there is no saturation axis."),
    EconomySpec(code="TH", name="Thailand", world_bank="THA", bis="TH", pwt="THA",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="assumed: fiscal proxy and the emerging-economy prior of BR, CN and IN"),
    EconomySpec(code="GB", name="United Kingdom", world_bank="GBR", bis="GB", pwt="GBR",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05, note=_MACROFIELD),
    EconomySpec(code="US", name="United States", world_bank="USA", bis="US", pwt="USA",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05, note=_MACROFIELD),
    EconomySpec(code="JP", name="Japan", world_bank="JPN", bis="JP", pwt="JPN",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=False,
                depreciation_prior=0.05,
                note=(f"{_MACROFIELD}. It names central-bank assets as the proxy, which was "
                      "never wired and fell back to the fiscal balance without the sign "
                      "reversal; that effective setting is reproduced here. The World Bank "
                      "publishes no fiscal balance for Japan, so the economy is unavailable "
                      "until a stimulus series is sourced.")),
    EconomySpec(code="BD", name="Bangladesh", world_bank="BGD", bis=None, pwt="BGD",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="BIS publishes no total credit series, so there is no saturation axis."),
    EconomySpec(code="VN", name="Vietnam", world_bank="VNM", bis=None, pwt="VNM",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.06,
                note="BIS publishes no total credit series, so there is no saturation axis."),
    EconomySpec(code="DE", name="Germany", world_bank="DEU", bis="DE", pwt="DEU",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05, note=_MACROFIELD),
    EconomySpec(code="ES", name="Spain", world_bank="ESP", bis="ES", pwt="ESP",
                stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                depreciation_prior=0.05,
                note="assumed: fiscal proxy and the advanced-economy prior of DE, FR and GB"),
)

V1_0_0 = Calibration(
    version="1.0.0",
    note=("Reproduces the eigentliCH prototype (Macro_Model, state of 2026-08-03) for golden reconciliation, including "
          "its credit uplift and capital normalisation. See calibration.py."),
    credit_uplift=1.4,
    capital_target=0.9,
    refuse_above=6.0,
    closure="as_written",
    p_b_source="population_growth",
    parameter_ranges={
        "p_p": Bounds(lower=0.005, upper=0.20),   # return on the whole capital stock
        "p_b": Bounds(lower=-0.02, upper=0.05),   # tracks population growth
        "alpha": Bounds(lower=0.0, upper=1.0),    # a share of the savings rate
        "p_s": Bounds(lower=0.02, upper=0.60),    # gross national savings over output
    },
    stimulus_scale=Bounds(lower=0.0, upper=3.0),
    initial_state_tolerance=0.10,
    weak_identification_ratio=0.5,
    identity_correction_note=0.10,
    economies=ECONOMIES,
)

V1_1_0 = V1_0_0.model_copy(update={
    "version": "1.1.0",
    "parent_version": "1.0.0",
    "note": ("1.0.0 with the Phase 4 latch run over the full published history of the saturation "
             "axis (author's rule of 2026-09-27: once an economy has hit saturation it stays "
             "there until the reset is over, wherever in its history that happened)."),
    "phases": V1_0_0.phases.model_copy(update={"latch_from_full_history": True}),
})

def _genreith_germany(spec: EconomySpec) -> EconomySpec:
    if spec.code != "DE":
        return spec
    return spec.model_copy(update={
        "saturation_source": "bank_balance_sheet",
        "bank_area": "DE",
        "gdp_splice_year": 1990,
        "jst_currency_divisor": 1.95583,
        "note": (f"{_MACROFIELD}; saturation on Genreith's measure from 1.2.0: Bundesbank "
                 "balance-sheet total of all banks (OU0308) over nominal GDP, 1950 onwards, "
                 "GDP from JST (West Germany, DM) before 1990 and the World Bank after"),
    })


V1_2_0 = V1_1_0.model_copy(update={
    "version": "1.2.0",
    "parent_version": "1.1.0",
    "note": ("1.1.0 with Germany on Genreith's saturation measure (Field Theory of Macroeconomics, "
             "2014): the balance-sheet total of all banks over GDP from 1950, no uplift, and his "
             "Phase IV test, loans below 50 per cent of the bank balance sheet, where that share "
             "is published. The 3.5 ceiling is unchanged (decision of 2026-09-27)."),
    "phases": V1_1_0.phases.model_copy(update={"commercial_bank_share_floor": 0.5}),
    "economies": tuple(_genreith_germany(e) for e in V1_1_0.economies),
})

#: The euro area at its 2023 composition (20 members), as BIS reports it (code XM).
EURO_AREA = ("AUT", "BEL", "HRV", "CYP", "EST", "FIN", "FRA", "DEU", "GRC", "IRL", "ITA", "LVA",
             "LTU", "LUX", "MLT", "NLD", "PRT", "SVK", "SVN", "ESP")

_IMF_FISCAL = ("fiscal balance from IMF WEO general government net lending (World Bank series "
               "absent or ending early)")
_IMF_DEBT = ("saturation from IMF Global Debt Database private debt plus general government debt "
             "(BIS publishes no total credit series), times the credit uplift")


def _all_projectable(spec: EconomySpec) -> EconomySpec:
    """The economy settings that close each economy's data gap (calibration 1.3.0)."""
    update: dict = {}
    if spec.code == "EU":
        update = {"pwt_members": EURO_AREA, "note": (
            "Euro area (BIS XM, World Bank EMU), 2023 composition. Real capital from the sum of "
            "the 20 members' PWT capital and output (both at PPP), 1.3.0 onwards. HoNI calls this "
            "economy EU; the aggregate here is the euro area")}
    elif spec.code == "JP":
        update = {"fiscal_source": "imf_weo", "stimulus_reverse_sign": True,
                  "note": (f"{_MACROFIELD}; {_IMF_FISCAL}. Sign reversed like every fiscal proxy: "
                           "the old unwired setting without reversal is not carried over")}
    elif spec.code == "ID":
        update = {"fiscal_source": "imf_weo", "note": f"{spec.note}; {_IMF_FISCAL}"}
    elif spec.code in ("PH", "BD", "VN"):
        update = {"saturation_source": "imf_debt", "note": _IMF_DEBT}
        if spec.code in ("BD", "VN"):
            update["fiscal_source"] = "imf_weo"
            update["note"] = f"{_IMF_DEBT}; {_IMF_FISCAL}"
        update["note"] += "; fiscal proxy and depreciation prior assumed (emerging-economy prior)"
    return spec.model_copy(update=update) if update else spec


V1_3_0 = V1_2_0.model_copy(update={
    "version": "1.3.0",
    "parent_version": "1.2.0",
    "note": ("1.2.0 with every HoNI economy projectable: IMF sources where the World Bank or BIS "
             "publish nothing (JP, ID, VN, BD fiscal; PH, BD, VN debt), the euro area built from "
             "its members' PWT capital, and projections also for economies whose fitted path does "
             "not reproduce their window, flagged as weak evidence (decision of 2026-09-27)."),
    "projection": V1_2_0.projection.model_copy(update={"require_integrable_fit": False}),
    "economies": tuple(_all_projectable(e) for e in V1_2_0.economies),
})

#: The four Phase IV resolution policies, values exactly as ``SIM_Tech/Master_Controller/
#: Scenario_SAA.m`` (v0.1, Nicolas Buerkler) sets them, frozen in ``golden/scenario_saa/scenario_saa.json``
#: and checked there by ``tests/test_resolution.py``. Engine 09 ``scenario`` uses the same ids and
#: values. Only ``turn_position`` is this engine's own (R-005: "where in the band the turn
#: happens depends on the policy, deferral late and high, depression early"), a judgement
#: seeded here and open for review.
RESOLUTION_POLICIES: dict[str, ResolutionPolicy] = {
    "depression": ResolutionPolicy(
        label="Depression", target_mix=(0.0, 0.0, 0.25, 0.75),
        inflation=InflationSpec(form="sigmoid", start=0.02, end=-0.04, midpoint=0.5,
                                steepness=20.0, reverse=True),
        defaults=DefaultsSpec(start=1.0, end=0.6, inflection=0.5, steepness=2.5,
                              first_leg_share=0.3),
        valuations=ValuationsSpec(start=1.0, end=0.5, ramp_months=30),
        turn_position=0.2,
        corrects_through="numerator: claims written down",
        mechanism=("inflation falls on a sigmoid from +2 % to -4 %, 40 % of claims default and "
                   "valuations halve within 30 months: saturation corrects through the numerator"),
        asset_implication=("financial claims fall in nominal terms; cash and high-quality "
                           "sovereign debt hold value best, real assets fall less than financial "
                           "ones")),
    "hyperinflation": ResolutionPolicy(
        label="Hyperinflation", target_mix=(1.0, 0.0, 0.0, 0.0),
        inflation=InflationSpec(form="exponential", start=0.2, end=1.0, power=4.0),
        defaults=DefaultsSpec(start=1.0, end=1.0, inflection=0.5, steepness=2.5,
                              first_leg_share=0.3),
        valuations=ValuationsSpec(start=1.0, end=1.0, ramp_months=60),
        turn_position=0.6,
        corrects_through="denominator: nominal output inflated",
        mechanism=("inflation rises exponentially from 20 % to 100 % a year while claims are "
                   "honoured in nominal terms: saturation corrects through the denominator"),
        asset_implication=("financial claims are destroyed in real terms; value-preserving real "
                           "assets outperform")),
    "stagflation": ResolutionPolicy(
        label="Stagflation", target_mix=(0.5, 0.25, 0.25, 0.0),
        inflation=InflationSpec(form="sigmoid", start=0.02, end=0.10, midpoint=0.3,
                                steepness=15.0),
        defaults=DefaultsSpec(start=1.0, end=0.8, inflection=0.5, steepness=2.5,
                              first_leg_share=0.3),
        valuations=ValuationsSpec(start=1.0, end=0.7, ramp_months=20),
        turn_position=0.4,
        corrects_through="both, moderately",
        mechanism=("inflation rises on a sigmoid from 2 % to 10 %, 20 % of claims default and "
                   "valuations fall 30 % within 20 months: saturation corrects through both "
                   "numerator and denominator, moderately"),
        asset_implication=("nominal claims lose in real terms and to defaults; real assets and "
                           "short-duration claims hold up best")),
    "deferral": ResolutionPolicy(
        label="Deferral", target_mix=(0.5, 0.0, 0.0, 0.5),
        inflation=InflationSpec(form="hump", start=0.02, end=0.06, midpoint=0.5,
                                width_divisor=2.5),
        defaults=DefaultsSpec(start=1.0, end=0.9, inflection=0.5, steepness=2.5,
                              first_leg_share=0.3),
        valuations=ValuationsSpec(start=1.0, end=0.8, ramp_months=50),
        turn_position=0.9,
        corrects_through="little at first",
        mechanism=("inflation humps from 2 % to 6 % and back, 10 % of claims default and "
                   "valuations fall 20 % over 50 months: saturation corrects little at first, "
                   "the correction is deferred into the reset"),
        asset_implication=("a drawn-out correction: financial claims erode slowly, dispersion "
                           "between assets stays high")),
}

V1_4_0 = V1_3_0.model_copy(update={
    "version": "1.4.0",
    "parent_version": "1.3.0",
    "contract_version": "macrofield-calibration@1.4.0",
    "note": ("1.3.0 with review R-005 (decided 28.09.2026): the projection stops running far above "
             "its limit. A soft saturation ceiling around 5.0 (band 4.5 to 5.5, growth damped "
             "from 3.5 so the path bends and turns inside the band, no hard clamp); at the turn "
             "the path follows one of the four Phase IV resolution policies of Scenario_SAA.m "
             "(depression, hyperinflation, stagflation, deferral; stagflation by default, the "
             "template's selected case) through a 60-month crisis, then declines to the Foundation "
             "level over a 35-year reset and re-integrates with early-phase parameters. The model "
             "runs to 2080; years after 2039 carry a lower-confidence label. Observed-period "
             "outputs are identical to 1.3.0."),
    "projection": V1_3_0.projection.model_copy(update={
        "horizon_until": 2080,
        "display_until": 2039,
        "saturation_ceiling": SaturationCeiling(centre=5.0, lower=4.5, upper=5.5,
                                                damping_onset=3.5),
        "crisis": CrisisReset(months=60, default_policy="stagflation",
                              policies=RESOLUTION_POLICIES,
                              reset=ResetSpec(years=35, target="foundation",
                                              foundation_fraction=0.95),
                              early_phase_years=5),
    }),
})
# model_copy does not validate; a seed must satisfy every contract rule.
V1_4_0 = Calibration.model_validate(V1_4_0.model_dump())

V1_5_0 = V1_4_0.model_copy(update={
    "version": "1.5.0",
    "parent_version": "1.4.0",
    "contract_version": "macrofield-calibration@1.5.0",
    "note": ("1.4.0 with TB-08's integrability fixed at the model level (decision of 29.09.2026, "
             "TB-27): the investment share is bounded at zero, r = max(0, 1 - K_R/Y), in the fit "
             "and the projection alike, so financial capital stops flowing into real capital once "
             "real capital has reached output instead of real capital being liquidated at an "
             "unbounded rate, and the equations have no finite-time singularity; and every "
             "parameter carried past the window or into the post-reset re-integration is held "
             "inside its meaningful range (parameter_ranges). Identical to the written share "
             "wherever K_R <= Y. Every fit now integrates its window and every projection "
             "integrates to 2080. Inputs, diagnostics, phases and current states (what "
             "aggregation and cycle read) are identical to 1.4.0; the fit report, the simulated "
             "path and the projection are not."),
    "investment_share": "bounded",
    "projection": V1_4_0.projection.model_copy(update={"parameters_within_ranges": True}),
})
V1_5_0 = Calibration.model_validate(V1_5_0.model_dump())

#: Every seed, oldest first. Append; never edit a published version.
SEEDS: tuple[Calibration, ...] = (V1_0_0, V1_1_0, V1_2_0, V1_3_0, V1_4_0, V1_5_0)



def canonical_json(cal: Calibration) -> str:
    return json.dumps(cal.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(cal: Calibration) -> str:
    return "CAL-" + hashlib.sha256(canonical_json(cal).encode("utf-8")).hexdigest()[:16]
