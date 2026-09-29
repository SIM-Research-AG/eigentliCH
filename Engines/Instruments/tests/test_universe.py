"""The instrument register, and the three data levels built on it."""

from __future__ import annotations

import pytest

from store.etl.universe import COUNTRY_EXPOSURE, ROLE_OVERRIDES, UniverseError, read_universe
from tests.conftest import needs_feed, needs_sources


class TestRegister:
    def test_the_whole_published_universe_is_imported(self):
        assert len(read_universe()) == 54

    def test_names_are_unique(self):
        names = [i.name for i in read_universe()]
        assert len(set(names)) == len(names)

    def test_classification_metadata_survives_the_import(self):
        """Ticker, currency and liquidity are the register's real value -- the prototype's
        profiles were all seeded, so the classification is the only part worth keeping."""
        gold = next(i for i in read_universe() if i.name == "Precious Metals")
        assert gold.ticker == "XAU BGN Curncy"
        assert gold.currency == "CHF"
        assert gold.liquidity == "Daily"
        assert gold.asset_class == "Alternative"

    def test_the_register_is_multi_currency(self):
        """Which is why a currency choice is a real requirement rather than a preference."""
        currencies = {i.currency for i in read_universe()}
        assert {"USD", "CHF", "EUR"} <= currencies
        assert len(currencies) >= 5

    @pytest.mark.parametrize("name", sorted(ROLE_OVERRIDES))
    def test_each_declared_override_is_applied_and_reasoned(self, name):
        registry = {i.name: i for i in read_universe()}
        if name not in registry:
            pytest.skip(f"{name} is not in the published universe")
        instrument = registry[name]
        assert instrument.role == ROLE_OVERRIDES[name][0]
        if instrument.overridden:
            assert instrument.override_reason

    def test_government_bonds_are_protection_not_income(self):
        """Section 11.4: the coupon is not what defines the block, the crisis jump is."""
        registry = {i.name: i for i in read_universe()}
        assert registry["Global Governmental Bonds"].role == "protection"
        assert registry["Global Governmental Bonds"].source_role == "income"

    def test_real_estate_is_income_not_stabilisation(self):
        """Section 11.4: emphatically not Stabilisation -- it fails in exactly the state a
        stabiliser exists for."""
        registry = {i.name: i for i in read_universe()}
        assert registry["Global Real Estate indirect"].role == "income"

    def test_every_role_is_one_of_the_four(self):
        assert {i.role for i in read_universe()} <= {
            "gain", "income", "stabilisation", "protection"}

    def test_every_instrument_has_an_explicit_country_exposure(self):
        """An instrument added without a decision must fail here, not default to "global"."""
        names = {i.name for i in read_universe()}
        assert names == set(COUNTRY_EXPOSURE), sorted(names ^ set(COUNTRY_EXPOSURE))
        for name, (codes, reason) in COUNTRY_EXPOSURE.items():
            assert reason, name
            assert all(len(c) == 2 and c.isupper() for c in codes), name
            assert len(set(codes)) == len(codes), name

    def test_country_exposure_reaches_the_register(self):
        registry = {i.name: i for i in read_universe()}
        assert registry["CH Equities"].countries == ("CH",)
        assert registry["ASEAN Equities"].countries == ("ID", "MY", "PH", "TH")
        assert registry["Global Equities"].countries == ()

    def test_a_missing_file_is_refused(self, tmp_path):
        with pytest.raises(UniverseError, match="not found"):
            read_universe(tmp_path / "nope.json")

    def test_a_file_without_building_blocks_is_refused(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(UniverseError, match="building_blocks"):
            read_universe(path)


@needs_sources
@needs_feed
class TestDataLevels:
    @pytest.fixture(scope="class")
    def client(self, module_store):
        from fastapi.testclient import TestClient
        from store.etl import bootstrap

        bootstrap.main([])
        from api.main import app
        with TestClient(app) as c:
            yield c

    def test_no_source_FILE_was_downloaded(self, client):
        """The long record and the monthly report are NAS files and must stay that way.

        Downloaded proxy histories are feeds, counted separately below. The distinction is
        the point: a house series with a thesis behind it is not the same evidence as an
        ETF pulled off a public endpoint, and the provenance endpoint must not blur them.
        """
        body = client.get("/v1/data/sources").json()
        for source in body["sources"]:
            assert source["origin_kind"].startswith("nas:"), (
                f"{source['file']} is not under a known NAS root"
            )

    def test_downloaded_feeds_are_labelled_as_such(self, client):
        body = client.get("/v1/data/sources").json()
        downloaded = [f for f in body["feeds"] if f["origin_kind"].startswith("internet")]
        if downloaded:
            assert body["downloaded_rows"] > 0
            for feed in downloaded:
                assert feed["symbol"] and feed["proxy_grade"], (
                    "a downloaded feed must name its symbol and its proxy grade"
                )

    def test_every_source_is_attributed_to_a_root(self, client):
        for source in client.get("/v1/data/sources").json()["sources"]:
            assert source["origin_kind"].startswith("nas:")
            assert source["origin_note"]

    def test_level_three_reports_the_whole_register(self, client):
        body = client.get("/v1/data/performance").json()
        assert body["registered"] == 54
        assert body["with_history"] == 10
        assert body["without_history"] == 44

    def test_an_instrument_without_history_says_so_rather_than_inventing_one(self, client):
        body = client.get("/v1/data/performance").json()
        empty = next(i for i in body["instruments"] if not i["has_history"])
        assert empty["performance"]["months"] == 0
        assert empty["coverage"] == "seed"

    def test_performance_is_computed_for_the_ten_with_history(self, client):
        body = client.get(
            "/v1/data/performance?instrument_id=INS-precious-metals"
        ).json()["instruments"][0]
        p = body["performance"]
        assert p["months"] == 147
        assert p["max_drawdown"] < 0
        assert 0 < p["hit_rate"] < 1
        assert len(p["curve"]) == p["months"]
        assert p["by_year"]

    def test_the_summary_listing_omits_the_heavy_series(self, client):
        """A 54-row listing must not carry 54 monthly curves."""
        body = client.get("/v1/data/performance").json()
        for instrument in body["instruments"]:
            assert "curve" not in instrument["performance"]

    def test_the_performance_endpoint_declares_its_caveat(self, client):
        body = client.get("/v1/data/performance").json()
        assert "tactically managed" in body["caveat"]


@needs_sources
@needs_feed
class TestRegisterIntegrity:
    """Overlap and classification -- the two checks the register cannot run on itself."""

    @pytest.fixture(scope="class")
    def client(self, module_store):
        from fastapi.testclient import TestClient
        from store.etl import bootstrap

        bootstrap.main([])
        from api.main import app
        with TestClient(app) as c:
            yield c

    def test_ticker_collisions_are_found_without_needing_prices(self, client):
        """Shared tickers are a register fact, not a measurement.

        The count moves as corrections are made, so this asserts the mechanism and the
        one collision that is still genuine, rather than a total that has to be edited
        each time a decision is taken.
        """
        body = client.get("/v1/data/overlap").json()
        collisions = {c["ticker"]: c["instruments"] for c in body["ticker_collisions"]}
        assert "MXWO Index" in collisions
        assert len(collisions["MXWO Index"]) == 3
        assert body["ticker_collision_instruments"] >= 7

    def test_the_swiit_collision_was_resolved(self, client):
        """Infrastructure no longer shares SXI Real Estate's ticker.

        The register gave both `SWIIT Index`, which is the SXI Real Estate Funds index --
        so the infrastructure entry was pointing at Swiss listed property. SXI Real Estate
        keeps the ticker because it is the right one for it; Infrastructure was re-pointed
        at the global infrastructure index its name describes. If anyone reverts that,
        two instruments start carrying the same exposure again.
        """
        body = client.get("/v1/data/overlap").json()
        collisions = {c["ticker"]: c["instruments"] for c in body["ticker_collisions"]}
        assert "SWIIT Index" not in collisions, (
            f"SWIIT is shared again by {collisions.get('SWIIT Index')}"
        )

        rows = {i["instrument_id"]: i
                for i in client.get("/v1/instruments").json()}
        assert rows["INS-sxi-real-estate"]["ticker"] == "SWIIT Index"
        assert rows["INS-infrastructure"]["ticker"] == "SPGTIND Index"

    def test_overlap_separates_a_register_defect_from_a_proxy_artefact(self, client):
        """Blaming the register for this build's proxy choices would be wrong."""
        body = client.get("/v1/data/overlap").json()
        for pair in body["register_defect"]:
            assert pair["a_ticker"] == pair["b_ticker"]
        for pair in body["proxy_artefact"]:
            assert pair["a_ticker"] != pair["b_ticker"], (
                "a shared ticker is a register defect, not a proxy artefact"
            )
            assert pair["proxy"]

    def test_a_high_threshold_finds_less_than_a_low_one(self, client):
        loose = client.get("/v1/data/overlap?threshold=0.8").json()
        tight = client.get("/v1/data/overlap?threshold=0.99").json()
        count = lambda b: (len(b["register_defect"]) + len(b["proxy_artefact"])
                           + len(b["economic_overlap"]))
        assert count(tight) <= count(loose)

    def test_classification_logic_on_constructed_series(self, client):
        """The role rules, tested on series with known properties rather than live prices.

        Synthetic rather than downloaded, for two reasons: the suite must not touch the
        network, and an assertion about the real beta of a real ETF would fail one day for
        a reason that has nothing to do with this code.
        """
        import math

        from store import db

        periods = [f"{y}-{m:02d}" for y in range(2010, 2024) for m in range(1, 13)]
        # A deterministic pseudo-market: no RNG, so the fixture is reproducible.
        market = [0.01 * math.sin(i * 0.7) + 0.004 for i in range(len(periods))]

        def register(name, role, factor):
            instrument_id = f"INS-synthetic-{name}"
            now = db.utc_now()
            with db.session() as conn:
                conn.execute(
                    db.upsert(
                        "instrument",
                        ("instrument_id", "name", "role", "asset_class", "region_scope",
                         "capital_type", "currency", "active", "created_at", "updated_at",
                         "note"),
                        ("instrument_id",),
                    ),
                    (instrument_id, f"Synthetic {name}", role, "Test", "Global",
                     "Financial", "USD", 1, now, now, "test fixture"),
                )
                conn.executemany(
                    db.upsert(
                        "instrument_return",
                        ("instrument_id", "period", "value", "source", "ingested_at"),
                        ("instrument_id", "period"),
                    ),
                    [(instrument_id, p, factor * m, "test", now)
                     for p, m in zip(periods, market)],
                )
            return instrument_id

        # The benchmark the endpoint measures beta against.
        with db.session() as conn:
            now = db.utc_now()
            conn.execute(
                db.upsert(
                    "instrument",
                    ("instrument_id", "name", "role", "asset_class", "region_scope",
                     "capital_type", "currency", "active", "created_at", "updated_at", "note"),
                    ("instrument_id",),
                ),
                ("INS-us-equities", "US Equities", "gain", "Equity", "Global",
                 "Financial", "USD", 1, now, now, "test fixture"),
            )
            conn.executemany(
                db.upsert(
                    "instrument_return",
                    ("instrument_id", "period", "value", "source", "ingested_at"),
                    ("instrument_id", "period"),
                ),
                [("INS-us-equities", p, m, "test", now) for p, m in zip(periods, market)],
            )

        register("inverse", "gain", -1.0)     # a Gain instrument that moves against equities
        register("tracker", "protection", 1.0)  # a Protection instrument that tracks them

        rows = {i["name"]: i
                for i in client.get("/v1/data/classification").json()["instruments"]}

        inverse = rows["Synthetic inverse"]
        assert inverse["equity_beta"] == pytest.approx(-1.0, abs=0.05)
        assert inverse["flag"] == "low equity beta for a Gain instrument"

        tracker = rows["Synthetic tracker"]
        assert tracker["equity_beta"] == pytest.approx(1.0, abs=0.05)
        assert tracker["flag"] == "high equity beta for a Protection instrument"

    def test_a_weak_proxy_is_named_in_the_explanation(self, client):
        """A flag on a weak stand-in must not read as an accusation against the register."""
        from api.integrity import classification  # noqa: F401  - import guards the contract

        body = client.get("/v1/data/classification").json()
        for row in body["instruments"]:
            if row["flag"] and row["proxy_grade"] == "weak":
                assert "weak" in (row["explanation"] or "")

    def test_the_reading_says_a_flag_is_a_question(self, client):
        body = client.get("/v1/data/classification").json()
        assert "not a verdict" in body["reading"]
