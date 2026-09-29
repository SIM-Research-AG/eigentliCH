"""The published default moves only on purpose, and is pinned where it stands.

pcp mirrors this engine's ReturnSet with an exact pin on ``contract_version`` and names
the ``return_set_id`` fmre serves for a Regime in its request. This module pins what a
request **without** an estimator returns: the ids, the contract version, the shape of the
payload down to its key sets, the provenance notes, and the method vocabulary the default
actually emits. It also pins that another estimator, or a currency, is another id, so a
consumer can never receive one set under another's name.

**The pin was moved deliberately twice on 29 September 2026.**

FMRE-20, the owner's register decisions: Income became real estate 75 % and equity 25 %
(R-001, ``CAL-092efd097adb0b26`` -> ``CAL-69d9d1ee5245ac71``) and Short MSCI US and CS Long
Vola were deactivated (54 -> 52 instruments)::

    unstamped   RS-b61c78223f520245  ->  RS-ca414ad663de0621
    stamped     RS-9cf5467a868babbe  ->  RS-101354ae344db5b3   (RGM-e2658e8e9bbbc81e)

FMRE-22, the owner's decision on R-002: the default estimator is the 12 month forward
measurement with a light smoothing across neighbouring states (``forward_12m_smoothed``),
and **the estimator and the currency now enter every set's id**, defaulted or named
(before, the default's id did not say which estimator built it)::

    unstamped   RS-ca414ad663de0621  ->  RS-8b6a98484992c9d3
    stamped     RS-101354ae344db5b3  ->  RS-59598b143ab78c56   (RGM-e2658e8e9bbbc81e)
    stamped, currency=CHF            ->  RS-c472e411e39645f5
    stamped, currency=EUR            ->  RS-dd496e3d3e72affe
    stamped, currency=USD            ->  RS-76d1a29edc752997

``profile_method=cascade`` is the stored cascade set, now under its own id
(``RS-f040698f3e4c0d53`` unstamped, ``RS-7f9e617239897d7b`` stamped). The contract stays
``rs@1.0.0``: the label ``forward-12m-smoothed`` is additive and ``provenance.currency`` is
unchanged (null unless a currency is asked for). Moving the pin again is a decision, not a
fix: update the ids here, say why, and record it in DECISIONS.md.
"""

from __future__ import annotations

import pytest

from tests.conftest import needs_feed, needs_sources

pytestmark = [needs_sources, needs_feed]

DEFAULT_ID = "RS-8b6a98484992c9d3"
STAMPED_ID = "RS-59598b143ab78c56"
#: The default estimator in each currency, stamped against REGIME (FMRE-22).
STAMPED_IN = {"CHF": "RS-c472e411e39645f5", "EUR": "RS-dd496e3d3e72affe",
              "USD": "RS-76d1a29edc752997"}
#: The stored cascade, named explicitly: its own id since FMRE-22.
CASCADE_ID = "RS-f040698f3e4c0d53"
CASCADE_STAMPED_ID = "RS-7f9e617239897d7b"
#: Earlier defaults. A default served under any of them is stale: before FMRE-22 (the
#: cascade, the id without its estimator) and before FMRE-20 (the earlier calibration).
PREVIOUS_IDS = ("RS-ca414ad663de0621", "RS-101354ae344db5b3",
                "RS-b61c78223f520245", "RS-9cf5467a868babbe")
CALIBRATION = "CAL-69d9d1ee5245ac71"
INSTRUMENTS = 52
INACTIVE = {"INS-short-msci-us", "INS-cs-long-vola"}
REGIME = "RGM-e2658e8e9bbbc81e"
CONTRACT = "rs@1.0.0"
DEFAULT_METHOD = "forward_12m_smoothed"

TOP_KEYS = {"return_set_id", "contract_version", "engine_version", "as_of", "state_grid",
            "role_profiles", "instrument_profiles", "block_profiles", "provenance", "run_id"}
PROVENANCE_KEYS = {"calibration_id", "state_map_id", "regime_id", "universe_version",
                   "calibration_window", "signal_window", "estimator", "source_sha256",
                   "notes", "currency"}
PROFILE_KEYS = {"key", "kind", "role", "unit", "coverage", "states", "borrowed_from",
                "match_score"}
BASE_NOTES = [
    "Profiles are annual log returns per state. The mandate's horizon governs; the "
    "ReturnSet is a property of the world, not of a household.",
    "Series are nominal and not de-trended. Real is obtained by subtracting current "
    "inflation at the point of use.",
    "Four of the 25 states are extrapolated beyond the hull of the five phase "
    "estimates, reproducing the published reference. They are labelled.",
]
DEFAULT_NOTES = BASE_NOTES + [
    "Instrument profiles: profile_method=forward_12m_smoothed in currency=source; the "
    "default estimator: the 12 month forward return after each month, measured per "
    "phase, read onto the 25 states by pchip and lightly smoothed across neighbouring "
    "states; computed on request.",
    "Currency: each instrument series in its source currency (CHF for the andersCH "
    "recovered returns, USD for public proxies).",
]
#: The labels the default emits on instrument profiles: the smoothed measurement, a
#: phase filled from D2's scaled role shape, and the role seed of an instrument with no
#: history. Never ``borrowed`` (that is the cascade's).
DEFAULT_INSTRUMENT_LABELS = {"forward-12m-smoothed", "shape-scaled", "seed"}
ROLE_LABELS = {"data-driven", "data-driven-trimmed", "interpolated", "extrapolated"}


@pytest.fixture(scope="module")
def client(module_store):
    from fastapi.testclient import TestClient
    from store.etl import bootstrap

    bootstrap.main([])
    import api.main
    original = api.main.confirm_regime
    # The stamp is confirmed with aggregation first; that exchange has its own tests in
    # test_api.py. Here only what the stamp does to the payload matters.
    api.main.confirm_regime = lambda regime_id: None
    try:
        with TestClient(api.main.app) as c:
            yield c
    finally:
        api.main.confirm_regime = original


def _shape(body: dict) -> None:
    assert set(body) == TOP_KEYS
    assert set(body["provenance"]) == PROVENANCE_KEYS
    for profile in body["role_profiles"] + body["instrument_profiles"]:
        assert set(profile) == PROFILE_KEYS
        for state in profile["states"]:
            assert set(state) == {"state", "value", "method", "n_obs"}


class TestTheDefaultIsPinned:
    def test_unstamped_id_and_version(self, client):
        body = client.get("/v1/return-set").json()
        assert body["return_set_id"] == DEFAULT_ID
        assert body["contract_version"] == CONTRACT
        assert body["provenance"]["regime_id"] is None
        assert body["provenance"]["calibration_id"] == CALIBRATION
        assert body["provenance"]["estimator"] == "plain_mean"
        assert body["provenance"]["currency"] is None, "the default is not converted"

    def test_stamped_id_and_version(self, client):
        body = client.get(f"/v1/return-set?regime_id={REGIME}").json()
        assert body["return_set_id"] == STAMPED_ID
        assert body["contract_version"] == CONTRACT
        assert body["provenance"]["regime_id"] == REGIME
        assert body["provenance"]["currency"] is None

    def test_the_explicit_form_pcp_uses_is_the_same_set(self, client):
        explicit = client.get(f"/v1/return-set?include_instruments=true&include_blocks=false"
                              f"&regime_id={REGIME}")
        assert explicit.content == client.get(f"/v1/return-set?regime_id={REGIME}").content

    def test_shape_notes_and_labels(self, client):
        body = client.get(f"/v1/return-set?regime_id={REGIME}").json()
        _shape(body)
        assert list(body["provenance"]["notes"]) == DEFAULT_NOTES
        assert len(body["instrument_profiles"]) == INSTRUMENTS
        assert not {p["key"] for p in body["instrument_profiles"]} & INACTIVE
        instrument_labels = {s["method"] for p in body["instrument_profiles"]
                             for s in p["states"]}
        assert instrument_labels <= DEFAULT_INSTRUMENT_LABELS
        assert "forward-12m-smoothed" in instrument_labels
        role_labels = {s["method"] for p in body["role_profiles"] for s in p["states"]}
        assert role_labels <= ROLE_LABELS, "the role profiles are the calibration's, unchanged"

    def test_naming_the_default_method_is_the_default(self, client):
        """``profile_method=forward_12m_smoothed`` is the default set, byte for byte."""
        default = client.get(f"/v1/return-set?regime_id={REGIME}").content
        named = client.get(
            f"/v1/return-set?regime_id={REGIME}&profile_method={DEFAULT_METHOD}").content
        assert named == default

    def test_the_previous_default_ids_are_not_served(self, client):
        """Neither the cascade default's ids (FMRE-20) nor the ones before them."""
        served = {client.get(f"/v1/return-set{q}").json()["return_set_id"]
                  for q in ("", f"?regime_id={REGIME}", "?profile_method=cascade",
                            f"?regime_id={REGIME}&profile_method=cascade")}
        assert not served & set(PREVIOUS_IDS)


class TestTheEstimatorIsInTheId:
    def test_the_cascade_is_the_stored_set_under_its_own_id(self, client):
        body = client.get(f"/v1/return-set?regime_id={REGIME}&profile_method=cascade").json()
        assert body["return_set_id"] == CASCADE_STAMPED_ID
        assert client.get("/v1/return-set?profile_method=cascade").json()[
            "return_set_id"] == CASCADE_ID
        assert body["contract_version"] == CONTRACT
        _shape(body)
        assert list(body["provenance"]["notes"])[:3] == BASE_NOTES
        assert "profile_method=cascade in currency=source; the stored cascade profiles" in \
            body["provenance"]["notes"][3]
        labels = {s["method"] for p in body["instrument_profiles"] for s in p["states"]}
        assert "forward-12m-smoothed" not in labels

    def test_each_method_has_its_own_id(self, client):
        ids = {
            m: client.get(f"/v1/return-set?regime_id={REGIME}&profile_method={m}").json()[
                "return_set_id"]
            for m in ("cascade", "shape_scaled", "forward_12m", DEFAULT_METHOD)
        }
        assert len(set(ids.values())) == 4
        assert ids[DEFAULT_METHOD] == STAMPED_ID

    def test_another_method_is_named_in_the_notes(self, client):
        body = client.get(f"/v1/return-set?regime_id={REGIME}&profile_method=forward_12m").json()
        _shape(body)
        assert len(body["provenance"]["notes"]) == 5
        assert "profile_method=forward_12m in currency=source; computed on request; not " \
               "the default estimator." in body["provenance"]["notes"][3]
        assert body["provenance"]["currency"] is None, "another method is not a conversion"

    def test_a_currency_without_rates_is_refused_not_approximated(self, client):
        """The throwaway store has no FX series; a conversion must fail loudly.

        USD, because the histories here are the andersCH recoveries in CHF: asked for CHF
        they need no rate.
        """
        response = client.get(f"/v1/return-set?regime_id={REGIME}&currency=USD")
        assert response.status_code == 503
        assert "store.etl.fx" in response.json()["detail"]

    def test_an_unknown_currency_or_method_is_the_callers_error(self, client):
        assert client.get("/v1/return-set?currency=GBP").status_code == 422
        assert client.get("/v1/return-set?profile_method=regression").status_code == 422


class TestTheCurrencyIsInTheProvenance:
    """``provenance.currency`` (29 September 2026, for pcp v1.1.0): the measurement currency
    of a converted set, null on the default. Optional and additive, so ``rs@1.0.0`` stays;
    the note still names the currency (``in currency=CHF``), which pcp read before the
    field existed."""

    @pytest.fixture()
    def client_with_rates(self, store):
        from fastapi.testclient import TestClient
        from store import db
        from store.etl import bootstrap
        from store.etl.datafeed import upsert_series

        bootstrap.main([])
        periods = [f"{y}-{m:02d}" for y in range(2003, 2027) for m in range(1, 13)]
        with db.datafeed_session() as conn:
            # Constant rates: enough to convert, and the conversion itself is tested in
            # test_forward.py; here only what the payload says about it matters.
            for series_id, level in (("fx.USDCHF", 0.9), ("fx.EURCHF", 1.1)):
                upsert_series(conn, series_id=series_id, name=series_id, unit="price",
                              currency="CHF", magnitude="units", period="M",
                              country="CH", category="fx", source="test",
                              origin_kind="test", quality_grade="close",
                              values={p: level for p in periods})
        import api.main
        original = api.main.confirm_regime
        api.main.confirm_regime = lambda regime_id: None
        try:
            with TestClient(api.main.app) as c:
                yield c
        finally:
            api.main.confirm_regime = original

    @pytest.mark.parametrize("currency", ["CHF", "EUR", "USD"])
    def test_a_converted_set_names_its_currency(self, client_with_rates, currency):
        response = client_with_rates.get(f"/v1/return-set?regime_id={REGIME}&currency={currency}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provenance"]["currency"] == currency
        assert body["contract_version"] == CONTRACT
        assert body["return_set_id"] == STAMPED_IN[currency]
        assert (f"profile_method={DEFAULT_METHOD} in currency={currency}; the default "
                f"estimator") in body["provenance"]["notes"][3]
        default = client_with_rates.get(f"/v1/return-set?regime_id={REGIME}").json()
        assert default["provenance"]["currency"] is None
        assert default["return_set_id"] == STAMPED_ID
