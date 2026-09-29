"""The deflator of the nominal and real view (owner's decisions of 29 September 2026).

Pure functions first, on synthetic signals and year-on-year series whose right answer is
known; then the reader of Engine 01's ``inflation.cpi_yoy`` against a throwaway schema
(the EUR splice) and, read-only, against the live datafeed.
"""

from __future__ import annotations

import math
import uuid

import pytest

from engines.fund_map import inflation as infl
from engines.fund_map.forward import KNOT_INDEX, add_months
from tests.test_cascade import make_state_map

KNOT_STATES = [k + 1 for k in KNOT_INDEX]      # 3, 8, 13, 18, 23
RATES = (0.01, 0.02, 0.03, 0.04, 0.05)          # crisis .. boom


def synthetic(rates=RATES, *, thin_boom: bool = False, today: float | None = None):
    """Signal months 2000-01 .. 2019-12 in blocks of 12, cycling crisis .. boom knots.

    The year-on-year reading 12 months after a month in phase p is ``rates[p]``, so the
    forward inflation of each phase is exactly ``log(1 + rates[p])``. The tagged month's
    *own* reading is something else (0.5), and must never be used.
    """
    signal, yoy = {}, {}
    period = "2000-01"
    for block in range(20):
        phase = block % 5
        if thin_boom and phase == 4 and block > 4:
            phase = 3                               # boom only once: below the floor
        for _ in range(12):
            signal[period] = KNOT_STATES[phase]
            yoy[add_months(period, 12)] = rates[phase]
            period = add_months(period, 1)
    if today is not None:
        yoy[add_months(period, 12)] = today
    return signal, yoy


def curve(rates=RATES, currency="CHF", **kw):
    signal, yoy = synthetic(rates, **kw)
    return infl.state_curve(currency, yoy, signal, make_state_map({}), index="test",
                            source="test")


class TestTheCeiling:
    @pytest.mark.parametrize("rate, label", [
        (-0.10, "measured"), (0.0, "measured"), (0.20, "measured"),
        (0.2000001, "extrapolated"), (-0.1000001, "extrapolated"),
        (1.00, "extrapolated"), (-0.20, "extrapolated"),
        (1.0000001, "not_computable"), (-0.2000001, "not_computable"),
    ])
    def test_the_band_edges(self, rate, label):
        """Decision 4: measured -10 % .. +20 %, extrapolated to -20 % and +100 %, edges in."""
        assert infl.band(rate) == label


class TestThePerStateDeflator:
    def test_each_phase_is_the_inflation_of_the_following_12_months(self):
        c = curve()
        for phase, state in enumerate(KNOT_STATES):
            s = c.states[state - 1]
            assert s.log_inflation == pytest.approx(math.log1p(RATES[phase]), abs=1e-15)
            assert s.inflation == pytest.approx(RATES[phase], abs=1e-14)
            assert s.label == "measured" and s.estimate == "data-driven"
            assert s.n_obs >= 6
        assert len(c.states) == 25 and [s.state for s in c.states] == list(range(1, 26))
        assert [p.method for p in c.phases] == ["data-driven"] * 5

    def test_the_tagged_months_own_reading_is_not_its_forecast(self):
        signal, yoy = synthetic()
        yoy_own = {p: 0.5 for p in signal}          # the tagged months' own readings
        yoy_own.update(yoy)                         # t+12 readings override where they meet
        assert yoy_own["2000-01"] == 0.5
        windows = infl.forward_inflation_windows(yoy_own, signal, make_state_map({}))
        assert windows[0] == ("2000-01", 3, pytest.approx(math.log1p(0.01)))

    def test_a_missing_reading_drops_the_window_never_fills_it(self):
        signal, yoy = synthetic()
        del yoy["2001-01"]                          # the reading 12 months after 2000-01
        windows = infl.forward_inflation_windows(yoy, signal, make_state_map({}))
        assert "2000-01" not in [w[0] for w in windows]
        assert len(windows) == len(signal) - 1

    def test_a_thin_phase_takes_todays_inflation_labelled_fallback(self):
        """Decision 1: too little data in a state -> today's year-on-year, labelled."""
        c = curve(thin_boom=True, today=0.017)
        boom = c.phases[4]
        assert boom.method == "fallback" and boom.n_eff < 6
        assert boom.value == pytest.approx(math.log1p(0.017))
        assert c.today == pytest.approx(0.017)
        for s in c.states[20:25]:
            assert s.label == "fallback" and s.n_obs == 0 and s.estimate == "fallback"
        assert c.states[22].inflation == pytest.approx(0.017)
        assert all(s.label == "measured" for s in c.states[:20])

    def test_a_fallback_above_the_ceiling_is_not_computable(self):
        c = curve(thin_boom=True, today=1.5)
        assert c.states[22].label == "not_computable"
        assert 23 in c.outside() and not c.computable()

    def test_states_between_knots_are_labelled_by_the_ceiling(self):
        """A curve crossing +20 % between knots: measured below, extrapolated above."""
        c = curve((0.10, 0.15, 0.18, 0.30, 0.60))
        labels = c.labels
        assert labels[KNOT_STATES[2] - 1] == "measured"
        assert labels[KNOT_STATES[3] - 1] == "extrapolated"
        assert labels[KNOT_STATES[4] - 1] == "extrapolated"
        for s in c.states:
            assert s.label == infl.band(s.inflation)

    def test_no_series_at_all_is_refused(self):
        signal, _ = synthetic()
        with pytest.raises(infl.NotComputable, match="no CHF inflation series"):
            infl.state_curve("CHF", {}, signal, make_state_map({}), index="x", source="x")


class TestTheScenarioDeflator:
    def test_the_scenario_inflation_in_every_state(self):
        """Decision 2: the policy's own final-year inflation, never the history."""
        c = infl.scenario_curve("CHF", 0.6, policy="hyperinflation", regime_id="RGM-x")
        assert {s.log_inflation for s in c.states} == {math.log1p(0.6)}
        assert set(c.labels) == {"extrapolated"} and {s.n_obs for s in c.states} == {0}
        assert c.index == "scenario:hyperinflation" and c.scenario == "hyperinflation"

    def test_a_scenario_inside_the_measured_band_is_measured(self):
        c = infl.scenario_curve("EUR", 0.09, policy="stagflation", regime_id="RGM-x")
        assert set(c.labels) == {"measured"}

    def test_a_scenario_above_the_ceiling_is_not_computable(self):
        c = infl.scenario_curve("USD", 1.2, policy="x", regime_id="RGM-x")
        assert set(c.labels) == {"not_computable"} and not c.computable()


class TestRealIsNominalMinusLogInflation:
    def test_per_state(self):
        c = curve()
        nominal = [0.01 * i - 0.1 for i in range(25)]
        real = infl.deflate(nominal, c)
        for n, r, s in zip(nominal, real, c.states):
            assert r == pytest.approx(n - math.log1p(s.inflation), abs=1e-15)

    def test_deflating_outside_the_band_is_refused(self):
        with pytest.raises(infl.NotComputable):
            infl.deflate([0.0] * 25, curve((0.1, 0.1, 0.1, 0.1, 2.0)))


class TestTheHardCurrencyFallback:
    """Decision 5: above the ceiling, real in CHF, then USD; else not computable."""

    def curves(self, chf, eur, usd):
        return {"CHF": curve((0.02,) * 4 + (chf,), "CHF"),
                "EUR": curve((0.02,) * 4 + (eur,), "EUR"),
                "USD": curve((0.02,) * 4 + (usd,), "USD")}

    def test_inside_the_band_no_fallback(self):
        assert infl.hard_currency("EUR", self.curves(0.02, 0.5, 0.02)) == ("EUR", None)

    def test_above_the_ceiling_first_chf(self):
        eff, fb = infl.hard_currency("EUR", self.curves(0.02, 1.5, 0.02))
        assert eff == "CHF"
        assert fb["from"] == "EUR" and fb["to"] == "CHF" and 23 in fb["states"]
        # The worst state is named: the pchip tail beyond the boom knot runs higher.
        assert fb["reason"].startswith("real in CHF: EUR inflation of ")
        assert "a year is above the ceiling of 100%" in fb["reason"]

    def test_then_usd(self):
        eff, fb = infl.hard_currency("EUR", self.curves(1.5, 1.5, 0.02))
        assert eff == "USD" and fb["to"] == "USD"
        assert infl.hard_currency("CHF", self.curves(1.5, 0.02, 0.02))[0] == "USD"

    def test_below_the_floor_falls_back_too(self):
        assert infl.hard_currency("EUR", self.curves(0.02, -0.25, 0.02))[0] == "CHF"

    def test_neither_is_not_computable_with_the_reason(self):
        with pytest.raises(infl.NotComputable) as err:
            infl.hard_currency("EUR", self.curves(1.5, 1.5, 3.0))
        text = str(err.value)
        assert "EUR inflation" in text and "CHF inflation" in text and "USD inflation" in text
        assert "No hard currency is inside the band" in text


# ---------------------------------------------------------------------------
# Reading inflation.cpi_yoy (decision 3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def cpi_schema(monkeypatch):
    """A throwaway schema shaped like Engine 01's datafeed, the reader pointed at it."""
    from engines.fund_map import service
    from store import db

    name = f"t_cpi_{uuid.uuid4().hex[:10]}"
    with db.session() as conn:
        conn.execute(f"CREATE SCHEMA {name}")
        conn.execute(f"CREATE TABLE {name}.snapshot (snapshot_id text, parent_id text, "
                     f"checksum text, built_at text, manifest_json text)")
        conn.execute(f"CREATE TABLE {name}.observation (snapshot_id text, country text, "
                     f"series_id text, date text, value double precision, flag text, "
                     f"source text)")
        conn.execute(f"INSERT INTO {name}.snapshot VALUES ('old', NULL, '', "
                     f"'2025-01-01T00:00:00+00:00', '{{}}'), ('new', NULL, '', "
                     f"'2026-01-01T00:00:00+00:00', '{{}}')")
        rows = []
        for country, value in (("DE", 0.03), ("EU", 0.02), ("CH", 0.01), ("US", 0.04)):
            for year in (1997, 1998, 1999, 2000):
                rows.append(("new", country, "inflation.cpi_yoy", f"{year}-06-30", value))
                rows.append(("old", country, "inflation.cpi_yoy", f"{year}-06-30", 9.0))
        conn.executemany(f"INSERT INTO {name}.observation VALUES (%s, %s, %s, %s, %s, "
                         f"'observed', 'test')", rows)
    monkeypatch.setattr(service, "CPI_SCHEMA", name)
    try:
        yield name
    finally:
        with db.session() as conn:
            conn.execute(f"DROP SCHEMA {name} CASCADE")


class TestTheReader:
    def test_eur_is_german_cpi_before_1999_and_hicp_from_it(self, cpi_schema):
        from engines.fund_map import service
        from store import db
        with db.session() as conn:
            eur = service.load_cpi_yoy(conn, "EUR")
            chf = service.load_cpi_yoy(conn, "CHF")
            usd = service.load_cpi_yoy(conn, "USD")
        assert eur.yoy == {"1997-06": 0.03, "1998-06": 0.03, "1999-06": 0.02, "2000-06": 0.02}
        assert set(chf.yoy.values()) == {0.01} and set(usd.yoy.values()) == {0.04}
        assert eur.snapshot_id == "new", "the latest snapshot, never a mix"
        assert "HICP" in eur.index and "German CPI" in eur.index
        assert "Swiss CPI" in chf.index and "CPI-U" in usd.index

    def test_an_unknown_currency_has_no_index(self, cpi_schema):
        from engines.fund_map import service
        from store import db
        with db.session() as conn, pytest.raises(ValueError, match="no inflation index"):
            service.load_cpi_yoy(conn, "GBP")


class TestTheLiveDatafeed:
    """Read-only, against Engine 01's ``datafeed``: the series the design note names."""

    def test_ch_eu_us_monthly_from_2006(self):
        from engines.fund_map import service
        from store import db
        with db.session() as conn:
            for currency in ("CHF", "EUR", "USD"):
                cpi = service.load_cpi_yoy(conn, currency)
                assert min(cpi.yoy) == "2006-01", currency
                assert max(cpi.yoy) >= "2025-10", currency
                assert len(cpi.yoy) >= 230, currency
                assert all(-0.1 < v < 0.2 for v in cpi.yoy.values()), currency
