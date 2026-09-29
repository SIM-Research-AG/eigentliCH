"""Reference reconciliation (engine page section 5, Guide 6.1). Tolerance: 1e-12 absolute.

Layer A: calibration 1.0.0 reproduces the first draft's combination rule, run by the draft's
own functions on the same readings (``golden/draft_1.0.0.json``).
Layer B: the frozen inputs are the files ``golden/inputs/source.json`` names.
Layer C: this build's output under each seed and optimism level (regression only).
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from aggregation import calibration as seeds
from aggregation.contracts import OPTIMISM_SCALES
from aggregation.engine import run_model
from aggregation.service import build_regime, content_id, regime_id_for

from .conftest import INPUTS, expected

TOLERANCE = 1e-12


def test_layer_b_inputs_are_the_frozen_files():
    source = json.loads((INPUTS / "source.json").read_text(encoding="utf-8"))
    for name, digest in source["sha256"].items():
        assert hashlib.sha256((INPUTS / name).read_bytes()).hexdigest() == digest, name


def test_layer_a_reproduces_the_first_draft(mrs, cycle, macro, draft):
    out = run_model(mrs, cycle, macro, seeds.DRAFT, "default")
    by_code = {e.code: e for e in out.economies}
    assert draft["economies"], "the draft reference is empty"
    worst = 0.0
    for code, ref in draft["economies"].items():
        e = by_code[code]
        # The annual macro half, year by year.
        for year, row in zip(ref["years"], ref["macro_rows"]):
            mine = e.macro_layer[e.years.index(year)]
            worst = max(worst, float(np.max(np.abs(np.asarray(mine) - np.asarray(row)))))
        # The published months are exactly the draft's, and each merged row agrees.
        published = [d for d, dist in zip(out.dates, e.distribution) if dist is not None]
        assert published == ref["dates"], code
        index = {d: i for i, d in enumerate(out.dates)}
        for d, row in zip(ref["dates"], ref["merged"]):
            mine = e.distribution[index[d]]
            worst = max(worst, float(np.max(np.abs(np.asarray(mine) - np.asarray(row)))))
    assert worst <= TOLERANCE, worst


def test_layer_a_draft_publishes_no_month_past_its_macro_window(mrs, cycle, macro):
    """1.0.0 carries nothing: a month whose year has no macro reading is not assessed."""
    out = run_model(mrs, cycle, macro, seeds.DRAFT, "default")
    for e in out.economies:
        assert not any(e.carried)
        for d, y in zip(out.dates, e.macro_year):
            assert y is None or int(d[:4]) == y


@pytest.mark.parametrize("cal", seeds.SEEDS, ids=lambda c: c.version)
def test_layer_c_regression(mrs, cycle, macro, cal):
    ref = expected(cal.version)
    for level in OPTIMISM_SCALES:
        key = content_id("IDK", {"golden": True, "calibration": cal.version, "optimism": level})
        regime = build_regime(mrs, cycle, macro, cal, level, key, regime_id_for(key))
        want = ref[level]
        assert regime.artefact_id == want["artefact_id"], (cal.version, level)
        for e in regime.economies:
            assert list(e.state) == want["economies"][e.code]["state"]
            last = want["economies"][e.code]["last"]
            if last is not None:
                got = e.distribution[regime.dates.index(last["date"])]
                assert np.max(np.abs(np.asarray(got) - np.asarray(last["distribution"]))) <= TOLERANCE
