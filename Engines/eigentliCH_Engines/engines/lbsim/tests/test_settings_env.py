"""deploy/ENGINE_CHANGES.md item 1: the upstream engines' addresses from the environment."""

from __future__ import annotations

import pytest

from lbsim import settings

VARS = {"LBSIM_LBS_URL": ("lbs_url", "http://lbs:8013"), "LBSIM_PCP_URL": ("pcp_url", "http://pcp:8007"),
        "LBSIM_AGGREGATION_URL": ("aggregation_url", "http://aggregation:8004"),
        "LBSIM_FMRE_URL": ("fmre_url", "http://fmre:8006")}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in VARS:
        monkeypatch.delenv(var, raising=False)


def test_without_the_variables_the_config_addresses_hold():
    s = settings.load()
    assert (s.upstream.lbs_url, s.upstream.pcp_url, s.upstream.aggregation_url, s.upstream.fmre_url) == (
        "http://127.0.0.1:8013", "http://127.0.0.1:8007", "http://127.0.0.1:8004", "http://127.0.0.1:8006")


def test_each_variable_sets_its_engine_and_keeps_the_rest(monkeypatch):
    for var, (field, url) in VARS.items():
        monkeypatch.setenv(var, url)
    s = settings.load()
    for var, (field, url) in VARS.items():
        assert getattr(s.upstream, field) == url
        assert f"env: {var}" in s.sources
    # The contracts and the pass-through list beside the url are kept.
    assert s.upstream.accept_ipt == ("ipt@1.1.0",)
    assert s.upstream.contracts["lbs:sheet"] == "lbs-balance-sheet@1.0.0"


def test_one_variable_moves_one_engine(monkeypatch):
    monkeypatch.setenv("LBSIM_FMRE_URL", "http://fmre:8006")
    s = settings.load()
    assert s.upstream.fmre_url == "http://fmre:8006" and s.upstream.lbs_url == "http://127.0.0.1:8013"


def test_the_environment_outranks_config_local_and_an_empty_value_is_ignored(monkeypatch, tmp_path):
    root = settings.ROOT / "config.yaml"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(root.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("upstream:\n  pcp:\n    url: http://local-pcp:1\n"
                                                "  lbs:\n    url: http://local-lbs:2\n", encoding="utf-8")
    monkeypatch.setenv("LBSIM_PCP_URL", "http://pcp:8007")
    monkeypatch.setenv("LBSIM_LBS_URL", "  ")
    s = settings.load(cfg)
    assert s.upstream.pcp_url == "http://pcp:8007" and s.upstream.lbs_url == "http://local-lbs:2"
