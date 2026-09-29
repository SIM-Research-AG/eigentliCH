"""The frozen CIO ``signal`` export: parsing, what it proves about the kernels, and the load."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import psycopg
import pytest

from mrs import calibration as seeds, reference
from mrs.engine import kernel_matrix
from mrs.store import Store, put_reference_signal

FOLDER = Path(__file__).resolve().parent.parent / "golden" / "cio_signal_2026-09"


@pytest.fixture(scope="module")
def parsed():
    return next(reference.iter_folder(FOLDER))


def test_manifest_checksum_and_shape(parsed):
    manifest, rows, months = parsed
    assert months == 241
    assert len(rows) == 4 * 241 * 17
    # Month 1 is September 2006 (MRS-20: a later pull than M_TS.mat), month 241 September 2026.
    assert rows[0].date == "2006-09-30" and max(r.date for r in rows) == "2026-09-30"
    assert {r.economy for r in rows if r.is_blend} == {"EMCN"}
    assert {r.economy for r in rows if not r.is_blend} == set(reference.ECONOMIES.values())


def test_every_economy_vector_is_a_kernel_column(parsed):
    """The live MATLAB output uses exactly the kernels mrs builds (Weights.m port)."""
    _, rows, _ = parsed
    cal = seeds.MATLAB
    kernels = {s.name: kernel_matrix(s, cal.edges.count) * s.weight for s in cal.segments}
    worst = 0.0
    for r in rows:
        if r.is_blend:
            continue
        err = np.abs(kernels[r.segment] - np.array(r.probs)[:, None]).max(axis=0).min()
        worst = max(worst, float(err))
    assert worst < 1e-15


def test_emcn_is_the_fixed_blend(parsed):
    _, rows, _ = parsed
    w = {"IN": 0.6, "BR": 0.2, "ID": 0.05, "MY": 0.05, "PH": 0.05, "TH": 0.05}
    by = {(r.segment, r.economy, r.month_index): np.array(r.probs) for r in rows}
    for (seg, eco, k), v in by.items():
        if eco != "EMCN":
            continue
        blend = sum(wt * by[(seg, c, k)] for c, wt in w.items())
        np.testing.assert_allclose(v, blend, rtol=0, atol=1e-15)


def test_parse_rejects_unknown_economies_and_bad_vectors():
    good = {s: [{"USA": [0.0] * 25}] for s in reference.SEGMENTS}
    reference.parse_signal(good, "2006-01")
    with pytest.raises(reference.ReferenceError, match="unknown economy"):
        reference.parse_signal({s: [{"Atlantis": [0.0] * 25}] for s in reference.SEGMENTS}, "2006-01")
    with pytest.raises(reference.ReferenceError, match="25 finite"):
        reference.parse_signal({s: [{"USA": [0.0] * 24}] for s in reference.SEGMENTS}, "2006-01")


def test_load_is_idempotent_and_append_only(settings, parsed):
    manifest, rows, months = parsed
    store = Store(settings.database)
    store.initialise()
    with store.session() as conn:
        source_id, created = put_reference_signal(conn, manifest=manifest, rows=rows, months=months)
    assert created
    with store.session() as conn:
        _, again = put_reference_signal(conn, manifest=manifest, rows=rows, months=months)
        n = conn.execute("SELECT count(*) AS n FROM reference_signal").fetchone()["n"]
        probs = conn.execute(
            "SELECT probs FROM reference_signal WHERE segment = 'investment' AND economy = 'US' "
            "AND month_index = 241").fetchone()["probs"]
    assert not again and n == len(rows)
    expected = next(r.probs for r in rows if r.segment == "investment" and r.economy == "US"
                    and r.month_index == 241)
    assert tuple(probs) == expected, "DOUBLE PRECISION round trip must be exact"
    schema = settings.database.schema
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(f"DELETE FROM {schema}.reference_signal")
