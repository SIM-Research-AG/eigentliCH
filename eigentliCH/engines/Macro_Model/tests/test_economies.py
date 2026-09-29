"""Tests for the per-economy configurations.

Brief section 8.4 requires at least the United States, China, Japan, Germany, France, the United
Kingdom, India and a euro-area aggregate. These tests check that each is present, well formed, and
that its overlay actually reaches the loaded configuration.
"""

import pytest

from macrofield import config as config_module

REQUIRED = ["us", "cn", "jp", "de", "fr", "gb", "in", "eurozone"]

VALID_STIMULUS_PROXIES = {"fiscal_balance", "central_bank_assets", "net_new_credit"}
VALID_FINANCIAL_MEASURES = {"consolidated_financial_assets", "credit_only", "credit_plus_listed_equity"}


class TestPresence:
    def test_every_required_economy_has_a_configuration(self):
        available = set(config_module.available_economies())
        missing = [code for code in REQUIRED if code not in available]
        assert not missing, f"missing economy configurations: {missing}"

    @pytest.mark.parametrize("code", REQUIRED)
    def test_configuration_loads(self, code):
        assert config_module.load(code) is not None


class TestIdentity:
    @pytest.mark.parametrize("code", REQUIRED)
    def test_declares_its_codes(self, code):
        config = config_module.load(code)
        assert config.get("economy.code") == code
        assert config.get("economy.name")
        assert config.get("economy.world_bank")
        assert config.get("economy.bis")
        assert config.get("economy.currency")

    def test_country_codes_are_distinct_across_economies(self):
        """Two economies sharing a source code would silently load the same data."""
        world_bank, bis = {}, {}
        for code in REQUIRED:
            config = config_module.load(code)
            world_bank.setdefault(config.get("economy.world_bank"), []).append(code)
            bis.setdefault(config.get("economy.bis"), []).append(code)
        assert not [k for k, v in world_bank.items() if len(v) > 1], world_bank
        assert not [k for k, v in bis.items() if len(v) > 1], bis

    def test_aggregate_uses_aggregate_codes(self):
        config = config_module.load("eurozone")
        assert config.get("economy.world_bank") == "EMU"
        assert config.get("economy.bis") == "XM"


class TestOverlay:
    def test_defaults_are_inherited(self):
        """An economy file states only what is distinctive, so the shared thresholds must come through."""
        config = config_module.load("us")
        assert config.get("saturation.balanced_band.lower") == 2.5
        assert config.get("phases.optimisation_saturation_ceiling") == 3.5
        assert config.get("regime.states") == 25

    def test_series_templates_are_inherited(self):
        config = config_module.load("us")
        assert config.get("data.series.output_nominal.identifier") == "NY.GDP.MKTP.CD"
        assert config.get("data.series.total_credit.connector") == "bis"

    def test_economy_overrides_the_default_stimulus_proxy(self):
        """Japan's central-bank channel is larger than its fiscal deficit, so it overrides the default."""
        assert config_module.load("us").get("data.stimulus.proxy") == "fiscal_balance"
        assert config_module.load("jp").get("data.stimulus.proxy") == "central_bank_assets"
        assert config_module.load("cn").get("data.stimulus.proxy") == "net_new_credit"

    def test_overlay_does_not_leak_between_economies(self):
        """Loading Japan must not change what a later load of the United States sees."""
        config_module.load("jp")
        assert config_module.load("us").get("data.stimulus.proxy") == "fiscal_balance"

    def test_economy_overrides_the_depreciation_prior(self):
        assert config_module.load("us").get("data.real_capital_extension.default_depreciation_rate") == 0.05
        assert config_module.load("cn").get("data.real_capital_extension.default_depreciation_rate") == 0.06


class TestValues:
    @pytest.mark.parametrize("code", REQUIRED)
    def test_stimulus_proxy_is_recognised(self, code):
        proxy = config_module.load(code).get("data.stimulus.proxy")
        assert proxy in VALID_STIMULUS_PROXIES, f"{code} uses unknown proxy {proxy!r}"

    @pytest.mark.parametrize("code", REQUIRED)
    def test_financial_capital_measures_are_recognised(self, code):
        config = config_module.load(code)
        assert config.get("data.financial_capital.primary") in VALID_FINANCIAL_MEASURES
        assert config.get("data.financial_capital.fallback") in VALID_FINANCIAL_MEASURES

    @pytest.mark.parametrize("code", REQUIRED)
    def test_depreciation_rate_is_a_proper_fraction(self, code):
        rate = config_module.load(code).get("data.real_capital_extension.default_depreciation_rate")
        assert 0.0 < rate < 1.0, f"{code} has an impossible depreciation rate {rate}"

    @pytest.mark.parametrize("code", REQUIRED)
    def test_every_economy_documents_itself(self, code):
        """The notes are where a non-default choice or a data limitation is recorded, so an economy
        without any has not been thought about."""
        notes = config_module.load(code).get("notes", default=[])
        assert notes, f"{code} carries no notes"
        assert all(isinstance(note, str) and note.strip() for note in notes)

    @pytest.mark.parametrize("code", REQUIRED)
    def test_no_dated_forecast_is_encoded(self, code):
        """Brief section 0.14. Descriptive references to historical episodes are fine; a forward-dated
        claim is not, so the years the legacy notes used are checked for."""
        rendered = str(config_module.load(code).as_dict())
        for forbidden in ("2032 synchronisation", "peak in 2022", "2025 to 2028"):
            assert forbidden not in rendered

    def test_economies_with_a_non_default_proxy_say_so_in_their_notes(self):
        """A departure from the default must be visible to a reader of the config, not only in code."""
        for code in ("jp", "cn", "eurozone"):
            config = config_module.load(code)
            notes = " ".join(config.get("notes"))
            assert "proxy" in notes.lower() or "stimulus" in notes.lower(), code


class TestAggregateCaveats:
    def test_eurozone_records_that_it_overlaps_its_members(self):
        """Ranking the aggregate alongside its members would double count, so the caveat must be there."""
        notes = " ".join(config_module.load("eurozone").get("notes")).lower()
        assert "not independent" in notes or "double count" in notes

    def test_eurozone_records_the_changing_composition(self):
        notes = " ".join(config_module.load("eurozone").get("notes")).lower()
        assert "composition" in notes

    def test_euro_members_record_the_currency_union_caveat(self):
        for code in ("de", "fr"):
            notes = " ".join(config_module.load(code).get("notes")).lower()
            assert "euro area" in notes or "currency union" in notes, code


