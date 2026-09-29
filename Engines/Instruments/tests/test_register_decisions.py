"""The register decisions of 29 September 2026, and that every bootstrap applies them.

Role review after R-001 (Global Bonds and Bloomberg Market Neutral HF in Stabilisation),
Short MSCI US and CS Long Vola deactivated, Long Volatility Index read through the Cboe
VXTH index (FMRE-16 to FMRE-18). A decision that reaches only a freshly built store is not
a decision: the bootstrap wrote roles on first insert only, so the Digital Assets decision
of 27 September never reached the live store. ``TestDecisionsReachAnExistingStore``
builds a store, puts the pre-decision values back, and rebuilds.
"""

from __future__ import annotations

import pytest

from feeds import cboe
from feeds.proxy_map import PROXIES, feed_series_id, source_of
from store.etl.universe import DEACTIVATED, ROLE_OVERRIDES, read_universe
from tests.conftest import needs_feed, needs_sources


class TestTheRegister:
    def test_the_role_review(self):
        registry = {i.name: i for i in read_universe()}
        # Moved to Stabilisation in the role review, then back to Income by the owner the
        # same day because the evidence is thin (FMRE-25).
        assert registry["Global Bonds"].role == "income"
        assert registry["Global Bonds"].source_role == "income"
        assert registry["Bloomberg Market Neutral HF"].role == "stabilisation"
        for name in ("Global Bonds", "Bloomberg Market Neutral HF"):
            reason = ROLE_OVERRIDES[name][1]
            assert "29 September 2026" in reason and "Income A" in reason
            assert "Stabilisation 0." in reason, "the curve evidence belongs in the reason"
            assert "confirmed" in registry[name].note or "changed" in registry[name].note

    def test_deactivated_are_kept_with_their_reason(self):
        registry = {i.name: i for i in read_universe()}
        assert len(registry) == 54, "deactivated, never deleted"
        assert set(DEACTIVATED) == {"Short MSCI US", "CS Long Vola"}
        assert [n for n, i in registry.items() if not i.active] == sorted(
            DEACTIVATED, key=list(registry).index)
        assert DEACTIVATED["Short MSCI US"].startswith(
            "A short index is not a hold-through-crisis instrument (owner, 29.09.2026)")
        for name in DEACTIVATED:
            assert "Not active." in registry[name].note
            assert DEACTIVATED[name] in registry[name].note
        assert registry["Long Volatility Index"].active

    def test_long_volatility_reads_vxth_from_cboe(self):
        proxy = PROXIES["Long Volatility Index"]
        assert (proxy.symbol, proxy.grade, proxy.source) == ("VXTH", "close", "cboe")
        assert feed_series_id("VXTH") == "cboe.VXTH"
        assert feed_series_id("GLD") == "yahoo.GLD" and source_of("VIXY") == "yahoo"

    def test_a_cboe_series_is_in_usd(self):
        from engines.fund_map.currency import source_currency
        assert source_currency("cboe:VXTH:close", "CHF") == "USD"


class TestTheCboeReader:
    """Offline: the reader on a constructed file, never the network."""

    TEXT = "DATE,VXTH\n" + "\n".join(
        f"{m:02d}/{d:02d}/2024,{100 + m + d / 100:.6f}"
        for m in range(1, 13) for d in (2, 15, 28)
    ) + "\n01/03/2025,120.000000\n01/31/2025,121.000000\n02/03/2025,122.000000\n"

    def test_month_end_levels_and_returns(self):
        series = cboe.monthly("VXTH", cboe.parse_daily("VXTH", self.TEXT), today="2025-02-10")
        assert series.last_period == "2025-01", "the month in progress is dropped"
        assert series.levels["2024-03"] == pytest.approx(103.28)
        assert series.returns["2025-01"] == pytest.approx(121.0 / 112.28 - 1)
        assert series.currency == "USD" and series.months == 12

    def test_a_complete_last_month_is_kept(self):
        series = cboe.monthly("VXTH", cboe.parse_daily("VXTH", self.TEXT), today="2025-03-01")
        assert series.last_period == "2025-02"

    def test_the_ohlc_layout_reads_the_close(self):
        text = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.24,17.30,17.00,17.10\n"
        assert cboe.parse_daily("VIX", text) == {"1990-01-02": 17.10}

    def test_an_unknown_layout_is_refused(self):
        with pytest.raises(cboe.FeedError):
            cboe.parse_daily("VXTH", "WHEN,LEVEL\n01/02/2024,1\n")


class TestTheAcceptanceCheck:
    """FMRE-19 on constructed views: positive everywhere, highest in crisis at source."""

    @staticmethod
    def view(profile, currency, series_currency):
        return {"profile": profile, "methods": ["data-driven"] * 25,
                "currency": currency, "series_currency": series_currency}

    def test_highest_in_crisis_is_required_in_the_source_currency_only(self):
        from engines.fund_map.service import protection_check
        peak_in_boom = [0.02] * 20 + [0.05] * 5
        assert not protection_check(self.view(peak_in_boom, "USD", "USD"))["passed"]
        assert protection_check(self.view(peak_in_boom, "CHF", "USD"))["passed"]

    def test_negative_in_crisis_fails_in_any_currency(self):
        from engines.fund_map.service import protection_check
        dip = [-0.01] + [0.05] * 24
        for currency in ("CHF", "USD"):
            assert not protection_check(self.view(dip, currency, "USD"))["passed"]

    def test_a_crisis_peak_passes(self):
        from engines.fund_map.service import protection_check
        check = protection_check(self.view([0.10] * 5 + [0.01] * 20, "USD", "USD"))
        assert check["passed"] and check["highest_in_crisis"] and check["in_source_currency"]


class TestTheRulePerProtectionType:
    """FMRE-24 on constructed views and register rows."""

    def test_the_type_is_read_from_what_the_instrument_is(self):
        from engines.fund_map.service import ProtectionType, protection_type
        assert protection_type({"asset_class": "Cash", "proxy_symbol": "BIL"})             is ProtectionType.CASH
        assert protection_type({"asset_class": "Alternative", "proxy_symbol": "VXTH"})             is ProtectionType.TAIL_HEDGE
        assert protection_type({"asset_class": "Alternative", "proxy_symbol": "GLD"})             is ProtectionType.FORWARD

    def test_cash_fails_on_any_negative_state_and_passes_without_a_crisis_peak(self):
        from engines.fund_map.service import ProtectionType, protection_check
        flat = [0.01] * 20 + [0.02] * 5
        view = TestTheAcceptanceCheck.view
        assert protection_check(view(flat, "USD", "USD"), ProtectionType.CASH)["passed"]
        dip = [0.01] * 10 + [-0.001] + [0.01] * 14
        assert not protection_check(view(dip, "USD", "USD"), ProtectionType.CASH)["passed"]

    def test_a_tail_hedge_is_judged_on_the_crisis_months_not_the_forward_year(self):
        from engines.fund_map.service import ProtectionType, protection_check
        rebound = [-0.02] * 5 + [0.10] * 20      # forward profile: fails the forward rule
        view = TestTheAcceptanceCheck.view(rebound, "USD", "USD")
        view["crisis_months"] = [{"period": "2008-10", "state": 1, "return": 0.30},
                                 {"period": "2008-11", "state": 2, "return": -0.05}]
        assert not protection_check(view)["passed"]
        check = protection_check(view, ProtectionType.TAIL_HEDGE)
        assert check["passed"] and check["crisis_months"] == 2
        view["crisis_months"] = [{"period": "2008-10", "state": 1, "return": -0.01}]
        assert not protection_check(view, ProtectionType.TAIL_HEDGE)["passed"]


@needs_sources
@needs_feed
class TestDecisionsReachAnExistingStore:
    @pytest.fixture(scope="class")
    def rebuilt(self, module_store):
        from store import db
        from store.etl import bootstrap

        bootstrap.main([])
        with db.session() as conn:
            # The state of a store built before the decisions (or edited since).
            conn.execute("UPDATE instrument SET role = 'income', note = 'old' "
                         "WHERE instrument_id = 'INS-global-bonds'")
            conn.execute("UPDATE instrument SET role = 'stabilisation' "
                         "WHERE instrument_id = 'INS-digital-assets'")
            conn.execute("UPDATE instrument SET active = 1 "
                         "WHERE instrument_id IN ('INS-short-msci-us', 'INS-cs-long-vola')")
            # An instrument retired through the API, which no decision names.
            conn.execute("UPDATE instrument SET active = 0 "
                         "WHERE instrument_id = 'INS-global-macro'")
        bootstrap.main([])
        with db.session() as conn:
            return {r["instrument_id"]: dict(r) for r in conn.execute(
                "SELECT instrument_id, role, active, note FROM instrument")}

    def test_roles_are_re_applied(self, rebuilt):
        assert rebuilt["INS-global-bonds"]["role"] == "income"
        assert rebuilt["INS-digital-assets"]["role"] == "gain"
        assert rebuilt["INS-bloomberg-market-neutral-hf"]["role"] == "stabilisation"

    def test_deactivations_are_re_applied(self, rebuilt):
        assert rebuilt["INS-short-msci-us"]["active"] == 0
        assert rebuilt["INS-cs-long-vola"]["active"] == 0
        assert "hold-through-crisis" in rebuilt["INS-short-msci-us"]["note"]
        assert len(rebuilt) == 54

    def test_a_retired_instrument_is_not_revived(self, rebuilt):
        assert rebuilt["INS-global-macro"]["active"] == 0
        assert rebuilt["INS-long-volatility-index"]["active"] == 1
