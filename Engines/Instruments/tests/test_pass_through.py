"""Inflation pass-through (beta) under a scenario Regime (owner, 29 September 2026).

FMRE-33 to FMRE-37, and FMRE-38 to FMRE-41 (``ipt@1.1.0``: the bond loss in log form
without a cap, cash beta 0, role profiles with a blended beta). Before: under a scenario Regime the real view deflated the historical
nominal profiles by the scenario's inflation, so under hyperinflation (63.6 % a year) gold
lost about 49 log points in every state. Now each instrument is carried to the scenario by
its pass-through beta::

    scenario nominal = (nominal - ln(1 + pi_hist)) + beta * ln(1 + pi_s)  [+ bond price]
    scenario real    = scenario nominal - ln(1 + pi_s)
    bond price       = -D * (ln(1 + pi_s) - ln(1 + pi_hist))

The API tests use the stand-ins of ``test_real_view.py``: a constant CPI rate per currency
(so ``pi_hist`` is known exactly) and aggregation's Regimes (a base Regime and the
hyperinflation scenario at its served ``inflation_final_12m``).
"""

from __future__ import annotations

import math
import random

import pytest

from engines.fund_map import pass_through as pt
from tests.conftest import needs_feed, needs_sources

REGIME = "RGM-e2658e8e9bbbc81e"
SCENARIO = "RGM-hyperinflation-standin"
#: The hyperinflation Regime's inflation_final_12m as aggregation serves it (29.09.2026).
PI_S = 0.6355609062627813
RATES = {"CHF": 0.01, "EUR": 0.02, "USD": 0.03}

#: The house type of every register instrument (FMRE-34). A register or rule change that
#: moves one is seen here.
MAPPING = {
    "Aktien Europe aktiv": "equities", "APAC Equities": "equities",
    "ASEAN Equities": "equities", "Asia ex Japan TR": "equities",
    "Asia Long Short Equities": "hedge_funds_alternatives",
    "Asia Multi Strategy HF": "hedge_funds_alternatives",
    "Asian JACI Bond Index": "nominal_bonds_aggregate",
    "Asia Pacific Arbitrage": "hedge_funds_alternatives", "AU NZ Equities": "equities",
    "Bloomberg Hedge Fund": "hedge_funds_alternatives",
    "Bloomberg Market Neutral HF": "hedge_funds_alternatives",
    "Bloomberg Multiverse (H-CHF)": "nominal_bonds_aggregate", "CH Equities": "equities",
    "CHF Cash": "cash", "CHF Corporate Loans IG": "nominal_bonds_aggregate",
    "China A Shares": "equities", "China Equities": "equities",
    "Commodities": "commodities", "CS Long Vola": "volatility",
    "Digital Assets": "digital_assets", "EM Equities": "equities",
    "EM Government Bonds LC": "nominal_bonds_government", "EU Equities": "equities",
    "EUR Cash": "cash", "EUR  Corporate Loans IG": "nominal_bonds_aggregate",
    "Fixed Holding": "equities", "Fundo World Equity": "equities",
    "Global Bonds": "nominal_bonds_aggregate", "Global Equities": "equities",
    "Global Governmental Bonds": "nominal_bonds_government",
    "Global High Yields": "nominal_bonds_aggregate",
    "Global Macro": "hedge_funds_alternatives", "Global Real Estate indirect": "real_estate",
    "Hang Seng Index": "equities", "India Equities": "equities",
    "Infrastructure": "real_estate", "Japan Equities": "equities",
    "Long Volatility Index": "volatility", "Mining Equities": "equities",
    "MSCI AC World IMI": "equities", "Precious Metals": "precious_metals",
    "Private Debt": "nominal_bonds_short", "Private Equity": "equities",
    "Real Estate direct": "real_estate", "Short MSCI US": "hedge_funds_alternatives",
    "Structured Products": "equities", "Swiss Dividend Equity": "equities",
    "Swiss Performance Index": "equities", "SXI Real Estate": "real_estate",
    "Trend Following": "hedge_funds_alternatives", "UK Equities": "equities",
    "USD Cash": "cash", "US Equities": "equities",
    "US Treasury TR Index": "nominal_bonds_government",
}


# ---------------------------------------------------------------------------
# The arithmetic, no store
# ---------------------------------------------------------------------------


class TestTheRule:
    def test_the_house_table(self):
        assert {t.key: (t.beta, t.duration) for t in pt.HOUSE_TABLE} == {
            "precious_metals": (1.0, None), "commodities": (1.0, None),
            "inflation_linked_bonds": (1.0, None), "real_estate": (0.8, None),
            "equities": (0.6, None), "cash": (0.0, None),
            "nominal_bonds_aggregate": (0.0, 6.0), "nominal_bonds_government": (0.0, 7.0),
            "nominal_bonds_short": (0.0, 0.25), "hedge_funds_alternatives": (0.5, None),
            "digital_assets": (0.5, None), "volatility": (0.5, None)}
        assert pt.CALIBRATION_VERSION == "ipt@1.1.0"
        assert pt.EARLIER_VERSIONS == {"ipt@1.0.0": "IPT-a6426b5352de9e3e"}
        assert pt.PRICE_FLOOR is None and "price_floor" not in pt.calibration_payload()

    def test_beta_one_leaves_the_real_return_unchanged_for_any_scenario_inflation(self):
        """Property: with beta = 1 the scenario real return is the historical real return,
        whatever pi_s (no duration)."""
        rng = random.Random(20260929)
        for _ in range(500):
            values = [rng.uniform(-0.8, 0.8) for _ in range(25)]
            hist = [rng.uniform(-0.05, 0.15) for _ in range(25)]
            pi_s = rng.uniform(-0.19, 3.0)
            nominal = pt.scenario_nominal(values, [math.log1p(h) for h in hist],
                                          pi_s, 1.0, None)
            real = [n - math.log1p(pi_s) for n in nominal]
            assert real == pytest.approx([v - math.log1p(h) for v, h in zip(values, hist)],
                                         abs=1e-14)

    def test_beta_zero_keeps_the_historical_real_nominal_and_loses_pi_s_real(self):
        values, hist = [0.05] * 25, [0.01] * 25
        nominal = pt.scenario_nominal(values, [math.log1p(0.01)] * 25, PI_S, 0.0, None)
        assert nominal == pytest.approx([0.05 - math.log1p(0.01)] * 25, abs=1e-15)

    def test_the_bond_price_change_in_log_form_without_a_cap(self):
        """FMRE-38: -D * (ln(1 + pi_s) - ln(1 + pi_hist)), a log return, no cap."""
        lg = math.log1p
        # Small moves: close to the simple duration rule.
        assert pt.bond_price_log(6.0, lg(0.03), lg(0.02)) == pytest.approx(
            -6 * (lg(0.03) - lg(0.02)), abs=1e-15)
        assert math.expm1(pt.bond_price_log(6.0, lg(0.03), lg(0.02))) == pytest.approx(
            -0.06, abs=0.005)
        # A fall in inflation is a price gain.
        assert pt.bond_price_log(7.0, lg(0.00), lg(0.02)) > 0
        # Hyperinflation: no cap, and the durations stay apart.
        losses = {d: math.expm1(pt.bond_price_log(d, lg(PI_S), lg(0.01)))
                  for d in (0.25, 6.0, 7.0)}
        assert losses[6.0] == pytest.approx(-0.944, abs=0.001)
        assert losses[7.0] == pytest.approx(-0.966, abs=0.001)
        assert -1 < losses[7.0] < losses[6.0] < losses[0.25] < 0
        assert losses[0.25] == pytest.approx(-0.114, abs=0.001)

    def test_cash_loses_the_full_inflation(self):
        """FMRE-39: beta 0, no duration: scenario real = historical real - ln(1 + pi_s)."""
        cash = pt.TYPES["cash"]
        assert cash.beta == 0.0 and cash.duration is None and not cash.nominal_bond
        hist = [math.log1p(0.01)] * 25
        nominal = pt.scenario_nominal([0.02] * 25, hist, PI_S, cash.beta, cash.duration)
        assert [n - math.log1p(PI_S) for n in nominal] == pytest.approx(
            [0.02 - hist[0] - math.log1p(PI_S)] * 25, abs=1e-15)

    def test_every_role_block_has_a_type_and_the_roles_their_blend(self):
        """FMRE-40: a role takes the weighted beta (and bond duration) of its blocks."""
        from engines.fund_map.calibrate import BLOCKS
        from engines.fund_map.roles import ROLE_MAP
        in_roles = {b for spec in ROLE_MAP for b in spec.weights}
        assert set(pt.BLOCK_TYPES) == in_roles
        assert in_roles < {b.key for b in BLOCKS} and "long_rate" not in pt.BLOCK_TYPES
        assert {b: t for b, (t, _) in pt.BLOCK_TYPES.items()} == {
            "equity": "equities", "real_estate": "real_estate",
            "gov_bonds": "nominal_bonds_government", "gold": "precious_metals",
            "commodities": "commodities", "agriculture": "commodities",
            "short_rate": "cash"}
        blends = pt.role_blends()
        got = {r: (b["beta"], b["duration"]) for r, b in blends.items()}
        assert got == {"gain": (pytest.approx(0.6), None),
                       "income": (pytest.approx(0.75), None),
                       "stabilisation": (pytest.approx(2 / 3), None),
                       "protection": (pytest.approx(0.5), pytest.approx(3.5))}
        for blend in blends.values():
            assert sum(c["weight"] for c in blend["composition"]) == pytest.approx(1.0)
            assert blend["beta"] == pytest.approx(
                sum(c["weight"] * c["beta"] for c in blend["composition"]))
        assert pt.calibration_payload()["roles"] == blends

    def test_the_blended_duration_is_the_weighted_sum_of_the_block_losses(self):
        """In log form the loss is linear in D: a role equals its blocks' weighted carry."""
        rng = random.Random(40)
        blend = pt.role_blend({"gov_bonds": 1.0, "gold": 1.0})
        for _ in range(200):
            hist = [math.log1p(rng.uniform(-0.05, 0.15)) for _ in range(25)]
            values = [rng.uniform(-0.5, 0.5) for _ in range(25)]
            pi_s = rng.uniform(-0.19, 3.0)
            role = pt.scenario_nominal(values, hist, pi_s, blend["beta"], blend["duration"])
            parts = [pt.scenario_nominal(values, hist, pi_s, pt.TYPES[t].beta,
                                         pt.TYPES[t].duration)
                     for t in ("nominal_bonds_government", "precious_metals")]
            assert role == pytest.approx([0.5 * a + 0.5 * b for a, b in zip(*parts)],
                                         abs=1e-12)

    @pytest.mark.parametrize("name, expected", sorted(MAPPING.items()))
    def test_every_register_instrument_has_its_type(self, name, expected):
        asset = {"equities": "Equity", "cash": "Cash", "real_estate": "Real Estate"}.get(
            expected, "Fixed Income" if expected.startswith("nominal") else "Alternative")
        if name == "Infrastructure":
            asset = "Alternative"
        proxy = {"Private Debt": "BKLN", "Long Volatility Index": "VXTH",
                 "Precious Metals": "GLD", "Commodities": "GSG"}.get(name)
        assert pt.classify({"name": name, "asset_class": asset, "proxy_symbol": proxy}
                           )[0] == expected

    def test_an_unmapped_asset_class_is_named_the_default(self):
        key, rule = pt.classify({"name": "Something new", "asset_class": "Unclassified"})
        assert key == "hedge_funds_alternatives" and "default" in pt.RULES[rule][1]


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def _periods():
    return [f"{y}-{m:02d}" for y in range(1995, 2031) for m in range(1, 13)]


@pytest.fixture(scope="module")
def client(module_store):
    from fastapi.testclient import TestClient
    from engines.fund_map import service
    from store.etl import bootstrap

    bootstrap.main([])
    import api.main

    def cpi(conn, currency):
        return service.CpiSeries(currency, {p: RATES[currency] for p in _periods()},
                                 f"stand-in {currency} index", "test:stand-in", "test")

    def scenario(regime_id):
        return {"policy": "hyperinflation", "horizon_months": 60,
                "inflation_final_12m": PI_S, "inflation_path": [PI_S] * 60}

    def regime(regime_id):
        if regime_id == REGIME:
            return {"regime_id": regime_id, "provenance": {"regime_id": regime_id}}
        return {"regime_id": regime_id, "provenance": {"scenario": scenario(regime_id)}}

    def current(regime_id):
        body = {"regime_id": regime_id}
        if regime_id != REGIME:
            body["scenario"] = scenario(regime_id)
        return body

    saved = (api.main.confirm_regime, api.main.fetch_regime, service.load_cpi_yoy)
    api.main.confirm_regime, api.main.fetch_regime, service.load_cpi_yoy = current, regime, cpi
    try:
        with TestClient(api.main.app) as c:
            yield c
    finally:
        api.main.confirm_regime, api.main.fetch_regime, service.load_cpi_yoy = saved


def _profiles(body, kind="instrument_profiles"):
    return {p["key"]: [s["value"] for s in p["states"]] for p in body[kind]}


def _pt(body):
    return {i["instrument_id"]: i
            for i in body["provenance"]["inflation_pass_through"]["instruments"]}


def _set(client, regime, basis=None):
    q = f"/v1/return-set?regime_id={regime}&currency=CHF" + (f"&basis={basis}" if basis else "")
    r = client.get(q)
    assert r.status_code == 200, r.text
    return r


LS = math.log1p(PI_S)
LH = math.log1p(RATES["CHF"])


@needs_sources
@needs_feed
class TestTheScenarioSet:
    def test_gold_is_no_longer_destroyed(self, client):
        """Real crisis value under hyperinflation = its historical real value (beta 1)."""
        base_real = _profiles(_set(client, REGIME, "real").json())["INS-precious-metals"]
        base_nominal = _profiles(_set(client, REGIME).json())["INS-precious-metals"]
        body = _set(client, SCENARIO, "real").json()
        scen_real = _profiles(body)["INS-precious-metals"]
        assert _pt(body)["INS-precious-metals"]["beta"] == 1.0
        assert scen_real == pytest.approx(base_real, abs=1e-14)
        before = [v - LS for v in base_nominal]          # what FMRE-31 served
        for s in range(5):                                # the crisis states
            assert scen_real[s] - before[s] == pytest.approx(LS - LH, abs=1e-14)
            assert scen_real[s] - before[s] > 0.48

    def test_every_instrument_follows_the_rule(self, client):
        base = _profiles(_set(client, REGIME).json())
        nominal = _set(client, SCENARIO).json()
        real = _set(client, SCENARIO, "real").json()
        used = _pt(nominal)
        assert set(used) == set(base) and len(used) == 52
        for key, values in base.items():
            u = used[key]
            assert u["deflator_currency"] == "CHF" and u["source"] == "house"
            bond = pt.bond_price_log(u["duration"], LS, LH) if u["duration"] else 0
            expected = [v - LH + u["beta"] * LS + bond for v in values]
            assert _profiles(nominal)[key] == pytest.approx(expected, abs=1e-13), key
            assert _profiles(real)[key] == pytest.approx(
                [e - LS for e in expected], abs=1e-13), key

    def test_a_nominal_bond_loses_pi_s_and_the_duration_loss(self, client):
        base_real = _profiles(_set(client, REGIME, "real").json())
        body = _set(client, SCENARIO, "real").json()
        used = _pt(body)
        for key, duration in (("INS-global-bonds", 6.0), ("INS-us-treasury-tr-index", 7.0),
                              ("INS-private-debt", 0.25)):
            assert used[key]["beta"] == 0.0 and used[key]["duration"] == duration
            loss = -duration * (LS - LH)
            assert _profiles(body)[key] == pytest.approx(
                [v - LS + loss for v in base_real[key]], abs=1e-13)
            assert all(r < b - LS for r, b in zip(_profiles(body)[key], base_real[key]))

    def test_provenance_the_id_and_the_notes(self, client):
        nominal = _set(client, SCENARIO).json()
        real = _set(client, SCENARIO, "real").json()
        base = _set(client, REGIME).json()
        prov = nominal["provenance"]["inflation_pass_through"]
        assert prov["calibration_version"] == "ipt@1.1.0"
        assert prov["calibration_id"].startswith("IPT-")
        assert prov["calibration_id"] != pt.EARLIER_VERSIONS["ipt@1.0.0"]
        assert prov["scenario"] == SCENARIO and prov["inflation_final_12m"] == PI_S
        assert prov["applied_to"] == ["instruments", "roles"]
        assert prov["price_floor"] is None and "no cap" in prov["formula"]
        assert "owner decision of 29.09.2026" in prov["source"]
        assert nominal["provenance"]["notes"][1].startswith(
            "Basis: nominal. Inflation pass-through under the scenario Regime")
        assert "Inflation pass-through" in real["provenance"]["notes"][1]
        assert "(beta - 1)" in real["provenance"]["notes"][1]
        assert "no cap" in nominal["provenance"]["notes"][1]
        assert "Role profiles follow the same rule" in nominal["provenance"]["notes"][1]
        assert "inflation_pass_through" not in base["provenance"]
        assert len({nominal["return_set_id"], real["return_set_id"],
                    base["return_set_id"]}) == 3

    def test_the_role_profiles_take_their_blended_beta(self, client):
        """FMRE-40: each role from its historical real return (USD) by its blended beta."""
        base = _profiles(_set(client, REGIME).json(), "role_profiles")
        nominal = _set(client, SCENARIO).json()
        real = _set(client, SCENARIO, "real").json()
        lu = math.log1p(RATES["USD"])
        roles = {r["role"]: r
                 for r in nominal["provenance"]["inflation_pass_through"]["roles"]}
        assert set(roles) == {"gain", "income", "stabilisation", "protection"}
        assert {k: (r["beta"], r["duration"]) for k, r in roles.items()} == {
            "gain": (pytest.approx(0.6), None), "income": (pytest.approx(0.75), None),
            "stabilisation": (pytest.approx(2 / 3), None),
            "protection": (pytest.approx(0.5), pytest.approx(3.5))}
        assert {r["deflator_currency"] for r in roles.values()} == {"USD"}
        assert [(c["block"], c["weight"], c["type"]) for c in roles["income"]["composition"]
                ] == [("equity", 0.25, "equities"), ("real_estate", 0.75, "real_estate")]
        assert real["provenance"]["inflation_pass_through"]["roles"] == list(roles.values())
        for key, values in base.items():
            r = roles[key]
            bond = -r["duration"] * (LS - lu) if r["duration"] else 0.0
            expected = [v - lu + r["beta"] * LS + bond for v in values]
            assert _profiles(nominal, "role_profiles")[key] == pytest.approx(
                expected, abs=1e-13), key
            assert _profiles(real, "role_profiles")[key] == pytest.approx(
                [e - LS for e in expected], abs=1e-13), key

    def test_block_profiles_carry_no_pass_through(self, client):
        def blocks(regime):
            return _profiles(client.get(f"/v1/return-set?regime_id={regime}&currency=CHF"
                                        f"&include_blocks=true").json(), "block_profiles")
        assert blocks(SCENARIO) == blocks(REGIME) and len(blocks(REGIME)) == 8

    def test_cash_under_the_scenario_loses_the_full_inflation(self, client):
        base_real = _profiles(_set(client, REGIME, "real").json())
        body = _set(client, SCENARIO, "real").json()
        for key in ("INS-chf-cash", "INS-eur-cash", "INS-usd-cash"):
            u = _pt(body)[key]
            assert (u["type"], u["beta"], u["duration"]) == ("cash", 0.0, None)
            assert _profiles(body)[key] == pytest.approx(
                [v - LS for v in base_real[key]], abs=1e-13)

    def test_the_instrument_profile_under_the_scenario(self, client):
        n = client.get("/v1/instruments/INS-precious-metals/profile?currency=CHF").json()
        s = client.get(f"/v1/instruments/INS-precious-metals/profile?currency=CHF"
                       f"&regime_id={SCENARIO}").json()
        r = client.get(f"/v1/instruments/INS-precious-metals/profile?currency=CHF"
                       f"&regime_id={SCENARIO}&basis=real").json()
        values = [x["value"] for x in n["states"]]
        assert [x["value"] for x in s["states"]] == pytest.approx(
            [v - LH + LS for v in values], abs=1e-14)
        assert [x["value"] for x in r["states"]] == pytest.approx(
            [v - LH for v in values], abs=1e-14)
        assert s["inflation_pass_through"]["instruments"][0]["beta"] == 1.0
        assert s["inflation_pass_through"]["applied_to"] == ["instruments"]
        assert s["inflation_pass_through"]["roles"] == []
        assert s["protection_check"] == n["protection_check"], "judged historical nominal"
        assert "inflation_pass_through" not in n


@needs_sources
@needs_feed
class TestTheOverride:
    def test_get_lists_every_active_instrument(self, client):
        body = client.get("/v1/inflation-beta").json()
        rows = {r["name"]: r for r in body["instruments"]}
        assert len(rows) == 52
        for name, row in rows.items():
            assert row["type"] == MAPPING[name], name
            assert row["house_beta"] == pt.TYPES[row["type"]].beta
            assert row["beta"] == row["house_beta"] and row["source"] == "house"
            assert row["override"] is None
        assert rows["Global Bonds"]["duration"] == 6.0
        assert rows["Precious Metals"]["duration"] is None
        assert rows["CHF Cash"]["beta"] == 0.0 and rows["CHF Cash"]["duration"] is None
        assert body["calibration"]["version"] == "ipt@1.1.0"
        assert body["calibration"]["roles"]["protection"]["duration"] == 3.5
        assert body["calibration"]["blocks"]["agriculture"]["type"] == "commodities"

    def test_an_override_changes_exactly_that_instrument_and_the_id(self, client):
        base_before = {b: _set(client, REGIME, b).content for b in (None, "real")}
        before = _set(client, SCENARIO, "real").json()
        r = client.put("/v1/inflation-beta/INS-us-equities",
                       json={"beta": 1.0, "reason": "test: full pass-through",
                             "set_by": "test"})
        assert r.status_code == 200, r.text
        assert r.json()["beta"] == 1.0 and r.json()["source"] == "override"
        after = _set(client, SCENARIO, "real").json()
        assert after["return_set_id"] != before["return_set_id"]
        b, a = _profiles(before), _profiles(after)
        changed = {k for k in b if b[k] != a[k]}
        assert changed == {"INS-us-equities"}
        assert a["INS-us-equities"] == pytest.approx(
            [v + 0.4 * LS for v in b["INS-us-equities"]], abs=1e-13)
        used = _pt(after)["INS-us-equities"]
        assert used["source"] == "override" and used["override_version"] >= 1
        # Base Regimes are untouched, byte for byte.
        for basis, content in base_before.items():
            assert _set(client, REGIME, basis).content == content
        # beta null reverts to the house value, as a new version.
        r = client.put("/v1/inflation-beta/INS-us-equities",
                       json={"beta": None, "reason": "test: revert", "set_by": "test"})
        assert r.status_code == 200 and r.json()["beta"] == 0.6
        assert r.json()["source"] == "house"
        assert r.json()["written"]["version"] == used["override_version"] + 1
        again = _set(client, SCENARIO, "real")
        assert again.json()["return_set_id"] == before["return_set_id"]
        assert _profiles(again.json()) == _profiles(before)

    def test_a_duration_override(self, client):
        r = client.put("/v1/inflation-beta/INS-global-bonds",
                       json={"beta": None, "duration": 2.0, "reason": "test", "set_by": "t"})
        assert r.status_code == 200, r.text
        assert r.json()["duration"] == 2.0 and r.json()["duration_source"] == "override"
        assert r.json()["beta"] == 0.0 and r.json()["source"] == "house"
        client.put("/v1/inflation-beta/INS-global-bonds",
                   json={"beta": None, "duration": None, "reason": "test: revert",
                         "set_by": "t"})
        assert client.get("/v1/inflation-beta").json()["instruments"][
            [i["instrument_id"] for i in client.get("/v1/inflation-beta").json()[
                "instruments"]].index("INS-global-bonds")]["duration"] == 6.0

    @pytest.mark.parametrize("payload", [
        {"beta": 1.6, "reason": "x", "set_by": "t"},
        {"beta": -0.1, "reason": "x", "set_by": "t"},
        {"beta": 0.5, "set_by": "t"},
        {"beta": 0.5, "reason": "", "set_by": "t"},
        {"beta": 0.5, "reason": "x"},
        {"beta": 0.5, "reason": "x", "set_by": "t", "extra": 1},
        {"reason": "x", "set_by": "t"},
    ])
    def test_a_bad_override_is_refused(self, client, payload):
        assert client.put("/v1/inflation-beta/INS-us-equities", json=payload
                          ).status_code == 422

    def test_an_unknown_instrument_is_404(self, client):
        assert client.put("/v1/inflation-beta/INS-nope",
                          json={"beta": 0.5, "reason": "x", "set_by": "t"}).status_code == 404
        assert client.get("/v1/inflation-beta/INS-nope/history").status_code == 404

    def test_the_history_newest_first(self, client):
        assert client.get("/v1/inflation-beta/INS-eur-cash/history").json() == []
        client.put("/v1/inflation-beta/INS-eur-cash",
                   json={"beta": 0.7, "duration": 0.5, "reason": "first", "set_by": "cio"})
        client.put("/v1/inflation-beta/INS-eur-cash",
                   json={"beta": None, "reason": "revert", "set_by": "cio"})
        history = client.get("/v1/inflation-beta/INS-eur-cash/history").json()
        assert [set(h) for h in history] == [
            {"version", "beta", "duration", "reason", "set_by", "set_at"}] * 2
        assert [(h["version"], h["beta"], h["duration"], h["reason"]) for h in history] == [
            (2, None, None, "revert"), (1, 0.7, 0.5, "first")]
        assert history[0]["set_by"] == "cio" and history[0]["set_at"]

    def test_the_store_is_append_only(self, client):
        import psycopg
        from store import db
        client.put("/v1/inflation-beta/INS-commodities",
                   json={"beta": 0.9, "reason": "test", "set_by": "t"})
        client.put("/v1/inflation-beta/INS-commodities",
                   json={"beta": None, "reason": "test: revert", "set_by": "t"})
        with db.session() as conn:
            versions = [r["version"] for r in conn.execute(
                "SELECT version FROM inflation_beta_override WHERE instrument_id = %s "
                "ORDER BY version", ("INS-commodities",)).fetchall()]
            assert versions == [1, 2]
        for sql in ("UPDATE inflation_beta_override SET beta = 0.1",
                    "DELETE FROM inflation_beta_override",
                    "UPDATE inflation_beta_calibration SET source = 'x'",
                    "DELETE FROM inflation_beta_calibration"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                with db.session() as conn:
                    conn.execute(sql)

    def test_the_earlier_calibration_is_kept_beside_the_new_one(self, client):
        """ipt@1.1.0 is a new version; a stored ipt@1.0.0 stays, unchanged."""
        from engines.fund_map import service
        from store import db
        with db.session() as conn:
            conn.execute(
                "INSERT INTO inflation_beta_calibration (version, calibration_id, created_at, "
                "source, payload_json) VALUES ('ipt@1.0.0', %s, %s, 'the earlier table', "
                "'{}') ON CONFLICT (version) DO NOTHING",
                (pt.EARLIER_VERSIONS["ipt@1.0.0"], db.utc_now()))
            cal = service.ensure_pass_through_calibration(conn)
            rows = {r["version"]: r["calibration_id"] for r in conn.execute(
                "SELECT version, calibration_id FROM inflation_beta_calibration").fetchall()}
        assert cal["version"] == "ipt@1.1.0"
        assert rows["ipt@1.0.0"] == "IPT-a6426b5352de9e3e"
        assert rows["ipt@1.1.0"] == cal["calibration_id"] != rows["ipt@1.0.0"]

    def test_a_changed_house_table_needs_a_new_version(self, client, monkeypatch):
        from engines.fund_map import service
        client.get("/v1/inflation-beta")          # the calibration is stored
        monkeypatch.setattr(pt, "SOURCE", pt.SOURCE + " edited")
        with pytest.raises(service.PassThroughError, match="without a new version"):
            from store import db
            with db.session() as conn:
                service.ensure_pass_through_calibration(conn)
