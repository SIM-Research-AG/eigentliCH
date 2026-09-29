"""CLI smoke tests: ingest, build-returnset, validate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fmre.cli import main


def test_cli_ingest_synthetic_prints_summary(capsys):
    rc = main(["ingest", "MXUS Index", "--source", "synthetic"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "MXUS Index" in captured.out
    assert "return obs" in captured.out


def test_cli_ingest_writes_parquet(tmp_path, capsys):
    rc = main(["ingest", "MXUS Index", "--source", "synthetic", "--out", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    printed = captured.out.strip()
    assert printed.endswith(".parquet")
    assert Path(printed).exists()


def test_cli_ingest_unknown_ticker_returns_2(capsys):
    rc = main(["ingest", "NOT_A_TICKER", "--source", "synthetic"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "NOT_A_TICKER" in err


def test_cli_build_returnset_end_to_end(tmp_path, capsys):
    out = tmp_path / "rs.json"
    rc = main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index", "BGAUTRCH Index", "XAU BGN Curncy", "BXIIBUS0 Index",
        "--source", "synthetic",
        "--calibration", "1998-01,2024-12",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["state_grid"] == 25
    assert payload["return_set_id"].startswith("RS-")
    assert len(payload["building_blocks"]) == 4


def test_cli_validate_accepts_valid_returnset(tmp_path, capsys):
    # First build one
    out = tmp_path / "rs.json"
    main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index",
        "--source", "synthetic",
        "--out", str(out),
    ])
    # Then validate it
    rc = main(["validate", str(out)])
    assert rc == 0
    assert "OK:" in capsys.readouterr().out


def test_cli_validate_rejects_corrupted_returnset(tmp_path, capsys):
    out = tmp_path / "rs.json"
    main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index",
        "--source", "synthetic",
        "--out", str(out),
    ])
    # Corrupt: inject a forbidden moment key
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["mu"] = 0.05
    out.write_text(json.dumps(payload), encoding="utf-8")

    rc = main(["validate", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "forbidden moment key" in err


def test_cli_stats_prints_summary(tmp_path, capsys):
    rs_path = tmp_path / "rs.json"
    main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index", "BGAUTRCH Index", "XAU BGN Curncy", "BXIIBUS0 Index",
        "--source", "synthetic",
        "--out", str(rs_path),
    ])
    rc = main(["stats", str(rs_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ReturnSet" in out
    assert "Coverage" in out
    assert "Role expectations" in out
    assert "Reference book" in out


def test_cli_stats_rejects_invalid_returnset(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"garbage": true}', encoding="utf-8")
    rc = main(["stats", str(bad)])
    # load_returnset raises on missing required fields; cmd_stats propagates
    assert rc != 0


def test_cli_seed_aware_synthetic_builds(tmp_path):
    """--source seed-aware-synthetic should produce a valid ReturnSet without
    external inputs (state-conditional means come from the seed)."""
    out = tmp_path / "rs.json"
    rc = main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index", "BGAUTRCH Index", "XAU BGN Curncy", "BXIIBUS0 Index",
        "--source", "seed-aware-synthetic",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    # Also validate
    rc = main(["validate", str(out)])
    assert rc == 0


def test_cli_doc_renders_html_from_returnset(tmp_path):
    rs_path = tmp_path / "rs.json"
    doc_path = tmp_path / "doc.html"
    main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--tickers", "MXUS Index", "BGAUTRCH Index", "XAU BGN Curncy", "BXIIBUS0 Index",
        "--source", "synthetic",
        "--out", str(rs_path),
    ])
    rc = main(["doc", str(rs_path), "--out", str(doc_path)])
    assert rc == 0
    assert doc_path.exists()
    html = doc_path.read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")


def test_cli_build_returnset_all_default_tickers(tmp_path):
    out = tmp_path / "rs.json"
    rc = main([
        "build-returnset",
        # The stand-in Regime is now an explicit opt-in, so that a ReturnSet cannot be stamped with a
        # synthetic regime_id by default.
        "--synthetic-timeline",
        "--source", "synthetic",
        "--out", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    # 54 seed rows but with proxy dedupe (MXWO x3, MXEU x2, SWIIT x2, VXTH x2)
    # We estimate PER BLOCK, so all 54 blocks appear in building_blocks
    assert len(payload["building_blocks"]) == 54
