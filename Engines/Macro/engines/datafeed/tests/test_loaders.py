"""The importer against the real MATLAB files, and the public clients against the real
internet. Both skip, loudly, when their source is absent."""

from __future__ import annotations

import json

from datafeed.engine import checksum, panel_of
from datafeed.etl.bootstrap import FROZEN_RAW
from datafeed.etl.matlab import read as _read
from datafeed.etl.seed import load_seed
from datafeed.settings import load

from .conftest import needs_matlab, needs_network


def read(settings):
    return _read(settings, *load_seed())


@needs_matlab
class TestMatlabImport:
    def test_the_import_reproduces_the_frozen_snapshot(self, frozen_manifest):
        snapshot, files, _ = read(load())
        assert checksum(panel_of(snapshot)) == frozen_manifest["checksum"]
        assert files[0].name == "M_TS.mat" and len(files) == 17

    def test_the_zero_rule_counts_are_unchanged(self):
        _, _, conversions = read(load())
        frozen = json.loads((FROZEN_RAW / "zero_rule.json").read_text(encoding="utf-8"))["conversions"]
        assert conversions == frozen

    def test_placeholder_tickers_are_no_data(self):
        """The sheets hold positions with USD BGN Curncy; MATLAB pulled it as 1.0 and scored it."""
        snapshot, _, conversions = read(load())
        empty = {(s.definition.country, s.definition.series_id) for s in snapshot.series
                 if s.definition.pull_code == "USD BGN Curncy"}
        assert {("BD", "fx.terms_of_trade"), ("PH", "debt.corporate_gdp"),
                ("VN", "consumer.wage_growth"), ("VN", "debt.corporate_gdp")} <= empty
        assert ("BD", "fx.beer") in empty and ("US", "debt.senior_loan_etf") not in empty
        assert len(empty) == 37                      # 4 HoNI series + 24 mrs market series + 9 HY yield to worst
        for s in snapshot.series:
            if (s.definition.country, s.definition.series_id) in empty:
                assert s.cells == () and "placeholder" in s.definition.description
                assert conversions[f"{s.definition.country}/{s.definition.series_id}"]["placeholder"] == 241

    def test_definitions_carry_the_ticker(self):
        snapshot, _, _ = read(load())
        us = {s.definition.series_id: s.definition for s in snapshot.series if s.definition.country == "US"}
        assert us["money.broad_money"].pull_code == "OEUSMBAH Index"      # M3 (defect 9.4)
        cn = {s.definition.series_id: s.definition for s in snapshot.series if s.definition.country == "CN"}
        assert cn["money.broad_money"].pull_code == "CNMSM2 Index"        # M2


@needs_network
class TestPublicClients:
    def test_world_bank(self):
        from datafeed.clients import public_clients
        client, clients = public_clients()
        try:
            r = clients["worldbank"].annual("BGD", "NY.GDP.MKTP.CN")
        finally:
            client.close()
        assert len(r.values) > 20 and len(r.sha256) == 64 and r.values[2015] > 0

    def test_imf_datamapper(self):
        from datafeed.clients import public_clients
        client, clients = public_clients()
        try:
            r = clients["imf"].annual("JPN", "GGXCNL_NGDP")
        finally:
            client.close()
        assert 2006 in r.values and -20 < r.values[2006] < 5
