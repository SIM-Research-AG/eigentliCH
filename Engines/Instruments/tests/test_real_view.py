"""``basis=real`` and ``GET /v1/inflation`` through the API (owner, 29 September 2026).

A throwaway store built from the NAS sources, with two stand-ins: Engine 01's CPI series
(``service.load_cpi_yoy``, a constant rate per currency, so every state's deflator is known
exactly) and aggregation's Regime (``api.main.fetch_regime``, a base Regime or a scenario
Regime with or without ``provenance.scenario.inflation_final_12m``).
"""

from __future__ import annotations

import math

import pytest

from tests.conftest import needs_feed, needs_sources

pytestmark = [needs_sources, needs_feed]

REGIME = "RGM-e2658e8e9bbbc81e"
SCENARIO = "RGM-scenario-standin"
SCENARIO_WITHOUT = "RGM-scenario-without-field"
#: The stand-in inflation per currency; a test may move one and must put it back.
RATES = {"CHF": 0.01, "EUR": 0.02, "USD": 0.03}
SCENARIO_RATE = 0.62


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

    def regime(regime_id):
        if regime_id == REGIME:
            return {"regime_id": regime_id, "provenance": {"regime_id": regime_id}}
        scenario = {"policy": "hyperinflation", "horizon_months": 60}
        if regime_id == SCENARIO:
            scenario.update(inflation_final_12m=SCENARIO_RATE,
                            inflation_path=[0.2] * 48 + [SCENARIO_RATE] * 12)
        return {"regime_id": regime_id, "provenance": {"scenario": scenario}}

    def current(regime_id):
        # aggregation's /regime/{id}/current: a scenario Regime carries its scenario there
        # (AGG-21), which the nominal pass-through reads (FMRE-33).
        body = {"regime_id": regime_id}
        if regime_id != REGIME:
            body["scenario"] = regime(regime_id)["provenance"]["scenario"]
        return body

    saved = (api.main.confirm_regime, api.main.fetch_regime, service.load_cpi_yoy)
    api.main.confirm_regime = current
    api.main.fetch_regime = regime
    service.load_cpi_yoy = cpi
    try:
        with TestClient(api.main.app) as c:
            yield c
    finally:
        api.main.confirm_regime, api.main.fetch_regime, service.load_cpi_yoy = saved


def _profiles(body, kind="instrument_profiles"):
    return {p["key"]: [s["value"] for s in p["states"]] for p in body[kind]}


class TestTheInflationEndpoint:
    @pytest.mark.parametrize("currency", ["CHF", "EUR", "USD"])
    def test_per_state_and_currency(self, client, currency):
        r = client.get(f"/v1/inflation?currency={currency}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"currency", "index", "method", "states", "as_of", "source"} <= set(body)
        assert body["currency"] == currency and len(body["states"]) == 25
        for s in body["states"]:
            assert set(s) >= {"state", "inflation", "log_inflation", "label", "n_obs"}
            assert s["log_inflation"] == pytest.approx(math.log1p(RATES[currency]))
            assert s["inflation"] == pytest.approx(RATES[currency])
            assert s["label"] in ("measured", "fallback")
        assert body["real_view"] == {"status": "computable", "currency": currency,
                                     "hard_currency_fallback": None}

    def test_the_currency_is_required_and_checked(self, client):
        assert client.get("/v1/inflation").status_code == 422
        assert client.get("/v1/inflation?currency=GBP").status_code == 422

    def test_a_scenario_regime_gives_its_own_inflation_in_every_state(self, client):
        body = client.get(f"/v1/inflation?currency=CHF&regime_id={SCENARIO}").json()
        assert body["regime_kind"] == "scenario" and body["scenario"] == "hyperinflation"
        assert {s["log_inflation"] for s in body["states"]} == {math.log1p(SCENARIO_RATE)}
        assert {s["label"] for s in body["states"]} == {"extrapolated"}
        assert body["index"] == "scenario:hyperinflation"

    def test_a_base_regime_gives_the_historical_inflation(self, client):
        body = client.get(f"/v1/inflation?currency=CHF&regime_id={REGIME}").json()
        assert body["regime_kind"] == "base"
        assert body["states"][0]["log_inflation"] == pytest.approx(math.log1p(0.01))

    def test_a_scenario_without_the_field_fails_loudly(self, client):
        r = client.get(f"/v1/inflation?currency=CHF&regime_id={SCENARIO_WITHOUT}")
        assert r.status_code == 503
        assert "provenance.scenario.inflation_final_12m" in r.json()["detail"]
        assert "never the historical" in r.json()["detail"]


class TestTheRealReturnSet:
    def test_real_is_nominal_minus_log_inflation_per_state(self, client):
        nominal = client.get(f"/v1/return-set?regime_id={REGIME}&currency=CHF").json()
        real = client.get(f"/v1/return-set?regime_id={REGIME}&currency=CHF&basis=real").json()
        d = math.log1p(RATES["CHF"])
        n, r = _profiles(nominal), _profiles(real)
        assert n.keys() == r.keys() and len(r) == 52
        for key in n:
            assert r[key] == pytest.approx([v - d for v in n[key]], abs=1e-15)
        # The role profiles are USD and are deflated by USD inflation.
        du = math.log1p(RATES["USD"])
        for key, values in _profiles(nominal, "role_profiles").items():
            assert _profiles(real, "role_profiles")[key] == pytest.approx(
                [v - du for v in values], abs=1e-15)
        # Labels, counts and coverage are the nominal ones.
        for a, b in zip(nominal["instrument_profiles"], real["instrument_profiles"]):
            assert [s["method"] for s in a["states"]] == [s["method"] for s in b["states"]]
            assert a["coverage"] == b["coverage"]

    def test_the_basis_is_in_the_id_the_provenance_and_the_notes(self, client):
        nominal = client.get(f"/v1/return-set?regime_id={REGIME}&currency=CHF").json()
        real = client.get(f"/v1/return-set?regime_id={REGIME}&currency=CHF&basis=real").json()
        assert real["return_set_id"] != nominal["return_set_id"]
        prov = real["provenance"]
        assert prov["basis"] == "real" and prov["currency"] == "CHF"
        assert prov["regime_id"] == REGIME and real["contract_version"] == "rs@1.0.0"
        d = prov["deflator"]
        assert d["currency"] == "CHF" and d["index"] == "stand-in CHF index"
        assert d["hard_currency_fallback"] is None and d["scenario"] is None
        assert len(d["labels"]) == 25 and "forward_12m" in d["method"]
        assert {c["currency"]: c["applied_to"] for c in d["curves"]} == {
            "CHF": ["instruments"], "USD": ["roles"]}
        assert prov["notes"][1].startswith("Basis: real in currency=CHF: every profile is "
                                           "nominal minus ln(1 + inflation) per state")
        assert "in currency=CHF" in prov["notes"][3], "pcp reads the currency here"
        assert "basis" not in nominal["provenance"]
        assert "deflator" not in nominal["provenance"]

    @pytest.mark.parametrize("query", ["currency=CHF&basis=real", "basis=real",
                                       f"regime_id={SCENARIO}&currency=CHF&basis=real"])
    def test_idempotent(self, client, query):
        first = client.get(f"/v1/return-set?regime_id={REGIME}&{query}")
        assert first.status_code == 200, first.text
        assert first.content == client.get(f"/v1/return-set?regime_id={REGIME}&{query}"
                                           ).content

    def test_the_currency_the_source_and_the_scenario_are_their_own_id(self, client):
        """The throwaway store has no FX series, so EUR and USD are not measurable here."""
        ids = {q: client.get(f"/v1/return-set?{q}").json()["return_set_id"] for q in (
            f"regime_id={REGIME}&currency=CHF&basis=real",
            f"regime_id={REGIME}&basis=real",
            f"regime_id={SCENARIO}&currency=CHF&basis=real",
            f"regime_id={REGIME}&currency=CHF",
            f"regime_id={SCENARIO}&currency=CHF")}
        assert len(set(ids.values())) == 5

    def test_without_a_currency_each_series_in_its_source_currency_stated(self, client):
        nominal = client.get(f"/v1/return-set?regime_id={REGIME}").json()
        real = client.get(f"/v1/return-set?regime_id={REGIME}&basis=real").json()
        prov = real["provenance"]
        assert prov["currency"] is None and prov["deflator"]["currency"] is None
        assert "Basis: real in currency=source" in prov["notes"][1]
        assert "the currency their series is measured in" in prov["notes"][1]
        # The throwaway store's histories are the andersCH recoveries in CHF.
        n, r = _profiles(nominal), _profiles(real)
        for p in real["instrument_profiles"]:
            if p["coverage"] != "seed":
                d = math.log1p(RATES["CHF"])
                assert r[p["key"]] == pytest.approx([v - d for v in n[p["key"]]], abs=1e-15)

    def test_the_cascade_can_be_real_too(self, client):
        nominal = client.get("/v1/return-set?profile_method=cascade&currency=CHF").json()
        real = client.get("/v1/return-set?profile_method=cascade&currency=CHF&basis=real"
                          ).json()
        d = math.log1p(RATES["CHF"])
        for key, values in _profiles(nominal).items():
            assert _profiles(real)[key] == pytest.approx([v - d for v in values], abs=1e-15)
        assert real["provenance"]["estimator"] == "cascade"

    def test_an_unknown_basis_is_the_callers_error(self, client):
        assert client.get("/v1/return-set?basis=gold").status_code == 422


class TestTheCeilingInTheReturnSet:
    def test_above_the_ceiling_the_set_is_real_in_chf_labelled(self, client):
        RATES["EUR"] = 1.5
        try:
            r = client.get(f"/v1/return-set?regime_id={REGIME}&currency=EUR&basis=real")
        finally:
            RATES["EUR"] = 0.02
        assert r.status_code == 200, r.text
        prov = r.json()["provenance"]
        assert prov["currency"] == "CHF", "the set says what it is in; pcp refuses a mismatch"
        fb = prov["deflator"]["hard_currency_fallback"]
        assert fb["from"] == "EUR" and fb["to"] == "CHF"
        assert "EUR inflation of 150.0% a year is above the ceiling of 100%" in fb["reason"]
        assert "Hard-currency view" in prov["notes"][1]
        assert "in currency=CHF" in prov["notes"][3]
        assert "asked for currency=EUR" in prov["notes"][3]
        chf = client.get(f"/v1/return-set?regime_id={REGIME}&currency=CHF&basis=real").json()
        assert _profiles(r.json()) == _profiles(chf)

    def test_then_usd(self, client):
        RATES["EUR"], RATES["CHF"] = 1.5, 1.5
        try:
            body = client.get(f"/v1/inflation?currency=EUR").json()
        finally:
            RATES["EUR"], RATES["CHF"] = 0.02, 0.01
        assert body["real_view"]["currency"] == "USD"
        assert {s["label"] for s in body["states"]} == {"not_computable"}
        assert all("above the ceiling" in s["reason"] for s in body["states"])

    def test_no_currency_inside_the_band_is_not_computable_with_the_reason(self, client):
        saved = dict(RATES)
        RATES.update(CHF=1.5, EUR=1.5, USD=-0.5)
        try:
            r = client.get(f"/v1/return-set?regime_id={REGIME}&currency=EUR&basis=real")
            i = client.get("/v1/inflation?currency=EUR").json()
        finally:
            RATES.update(saved)
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["status"] == "not_computable" and detail["basis"] == "real"
        assert "below the floor of -20%" in detail["reason"]
        assert i["real_view"]["status"] == "not_computable"


class TestTheScenarioReturnSet:
    def test_the_scenario_inflation_deflates_every_state(self, client):
        nominal = client.get(f"/v1/return-set?regime_id={SCENARIO}&currency=CHF").json()
        real = client.get(f"/v1/return-set?regime_id={SCENARIO}&currency=CHF&basis=real"
                          ).json()
        d = math.log1p(SCENARIO_RATE)
        for key, values in _profiles(nominal).items():
            assert _profiles(real)[key] == pytest.approx([v - d for v in values], abs=1e-15)
        for key, values in _profiles(nominal, "role_profiles").items():
            assert _profiles(real, "role_profiles")[key] == pytest.approx(
                [v - d for v in values], abs=1e-15)
        prov = real["provenance"]
        assert prov["deflator"]["scenario"] == SCENARIO
        assert set(prov["deflator"]["labels"]) == {"extrapolated"}
        assert "scenario Regime" in prov["notes"][1] and "62.00%" in prov["notes"][1]

    def test_a_scenario_without_the_field_is_refused(self, client):
        r = client.get(f"/v1/return-set?regime_id={SCENARIO_WITHOUT}&basis=real")
        assert r.status_code == 503
        assert "inflation_final_12m" in r.json()["detail"]
        # Since FMRE-33 the nominal scenario set needs the field too: its instruments are
        # carried to the scenario's inflation by their pass-through beta (FMRE-37).
        r = client.get(f"/v1/return-set?regime_id={SCENARIO_WITHOUT}")
        assert r.status_code == 503
        assert "pass-through" in r.json()["detail"]


class TestTheRealProfile:
    def test_real_profile_is_nominal_minus_log_inflation(self, client):
        iid = client.get("/v1/return-set").json()["instrument_profiles"][0]["key"]
        n = client.get(f"/v1/instruments/{iid}/profile?currency=CHF").json()
        r = client.get(f"/v1/instruments/{iid}/profile?currency=CHF&basis=real").json()
        d = math.log1p(RATES["CHF"])
        assert [s["value"] for s in r["states"]] == pytest.approx(
            [s["value"] - d for s in n["states"]], abs=1e-15)
        assert r["basis"] == "real" and r["deflator"]["currency"] == "CHF"
        assert r["protection_check"] == n["protection_check"], "judged nominal"
        assert "basis" not in n and "deflator" not in n

    def test_a_scenario_profile_and_the_regime_rule(self, client):
        """Real under a scenario: the historical real return plus (beta - 1) ln(1 + pi_s)
        (FMRE-33); before, nominal minus ln(1 + pi_s), which destroyed every hedge."""
        iid = client.get("/v1/return-set").json()["instrument_profiles"][0]["key"]
        n = client.get(f"/v1/instruments/{iid}/profile").json()
        r = client.get(f"/v1/instruments/{iid}/profile?basis=real&regime_id={SCENARIO}").json()
        pt = r["inflation_pass_through"]["instruments"][0]
        assert pt["duration"] is None, "the first instrument is not a nominal bond"
        d = math.log1p(SCENARIO_RATE)
        dh = math.log1p(RATES[pt["deflator_currency"]])
        assert [s["value"] for s in r["states"]] == pytest.approx(
            [s["value"] - dh + (pt["beta"] - 1) * d for s in n["states"]], abs=1e-14)
        assert r["deflator"]["scenario"] == SCENARIO
        # A scenario Regime moves the nominal profile too, since FMRE-33.
        nominal = client.get(f"/v1/instruments/{iid}/profile?regime_id={SCENARIO}")
        assert nominal.status_code == 200, nominal.text
        assert [s["value"] for s in nominal.json()["states"]] == pytest.approx(
            [s["value"] - dh + pt["beta"] * d for s in n["states"]], abs=1e-14)
        # A base Regime changes nothing.
        assert client.get(f"/v1/instruments/{iid}/profile?regime_id={REGIME}"
                          ).content == client.get(f"/v1/instruments/{iid}/profile").content

    def test_nominal_is_the_profile_as_before(self, client):
        iid = client.get("/v1/return-set").json()["instrument_profiles"][0]["key"]
        for q in ("", "?method=cascade", "?currency=CHF"):
            sep = "&" if q else "?"
            assert client.get(f"/v1/instruments/{iid}/profile{q}{sep}basis=nominal"
                              ).content == client.get(f"/v1/instruments/{iid}/profile{q}"
                                                      ).content
