"""Golden layer A: the port reproduces the draft's ``gameplan.assemble`` and ``paths.ledger`` (LBSIM-13).

The expected files are the draft's own output under its own interpreter (``dev/build_golden.py``), with its two
missing tables pointed at lbsim's seed records. Every float within 1e-9, every string, verdict and finding code
exact, every list the same length.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from conftest import GOLDEN, differences, load_json, plain

from lbsim.fast import gameplan as G
from lbsim.fast import paths as P
from lbsim.model import bvg, canton

LAYER_A = GOLDEN / "draft"
MANIFEST = load_json(LAYER_A / "manifest.json")
CASES = MANIFEST["cases"]


def _case(name: str) -> tuple[dict, dict]:
    return load_json(LAYER_A / "cases" / f"{name}.json"), load_json(LAYER_A / "expected" / f"{name}.json")


@pytest.mark.parametrize("name", CASES)
def test_assemble_reproduces_the_draft(name):
    sub, expected = _case(name)
    got = plain(G.assemble(sub))
    diff = differences(expected["assemble"], got)
    assert not diff, "\n".join(diff[:20])


@pytest.mark.parametrize("name", CASES)
def test_the_finding_codes_and_verdicts_are_exact(name):
    sub, expected = _case(name)
    got = G.assemble(sub)
    exp = expected["assemble"]
    assert [f["code"] for f in got["findings"]] == [f["code"] for f in exp["findings"]]
    assert [f["severity"] for f in got["findings"]] == [f["severity"] for f in exp["findings"]]
    assert [f["urgency"] for f in got["findings"]] == [f["urgency"] for f in exp["findings"]]
    for run_got, run_exp in zip(got["paths"]["paths"], exp["paths"]["paths"]):
        assert [g["reachable"] for g in run_got["goals"]] == [g["reachable"] for g in run_exp["goals"]]
    assert got["gate"]["stage"] == exp["gate"]["stage"]
    assert got["required_return"]["rungs"][0]["outcome"] == exp["required_return"]["rungs"][0]["outcome"]


@pytest.mark.parametrize("name", CASES)
def test_ledger_reproduces_the_draft(name):
    sub, expected = _case(name)
    p = G._params_from(sub)
    stop = G._stop_age(sub, p)
    diff = differences(expected["ledger"], plain(P.ledger(sub, p, stop_age=stop)))
    diff += differences(expected["ledger_stop_60_extra_035"],
                        plain(P.ledger(sub, p, stop_age=60.0, extra_rates=(0.035,))))
    assert not diff, "\n".join(diff[:20])


def test_layer_a_covers_every_rule_that_can_fire_without_the_plan():
    """Every rule of the draft's RULES fires in at least one case, except ``goal_not_fundable``, which only the
    optimiser can trigger."""
    fired = set()
    for name in CASES:
        fired |= {f["code"] for f in _case(name)[1]["assemble"]["findings"]}
    from lbsim.fast.findings import RULES
    codes = {r.__name__ for r in RULES} - {"goal_not_fundable"}
    # The draft's rule `wealth_that_cannot_work` reports under the code `drawable_thin`.
    codes = {("drawable_thin" if c == "wealth_that_cannot_work" else c) for c in codes}
    assert codes <= fired, sorted(codes - fired)


def test_the_tables_are_the_ones_layer_a_was_built_with():
    tables = MANIFEST["tables"]
    assert hashlib.sha256(bvg.TABLE.read_bytes()).hexdigest() == tables["social-insurance"]
    assert hashlib.sha256(canton.TABLE.read_bytes()).hexdigest() == tables["canton-tax"]


def test_the_seed_tables_are_the_source_files_unchanged():
    """Every key below ``_about`` is the source file's (LBSIM-12); the source's sha256 is recorded in ``_about``."""
    for path in (bvg.TABLE, canton.TABLE):
        record = json.loads(path.read_text(encoding="utf-8"))
        about = record.pop("_about")
        assert len(about["source_sha256"]) == 64
        assert record["source"] and record["as_of"]
        # The two loaders accept the record as they accepted the file.
    assert bvg.load()["bvg"]["savings_start_age"] == 25
    assert canton.load()["present"] is True


def test_the_alias_restated_in_gameplan_is_the_converters():
    """LBSIM-03: ``gameplan`` no longer imports ``onboarding``; the alias it read from there is restated and held
    equal to the draft's."""
    assert G._ALIASES == MANIFEST["onboarding_param_aliases"]


def test_the_params_defaults_are_the_drafts():
    from lbsim.model.params import Params
    ours = plain({k: (list(v) if isinstance(v, tuple) else v) for k, v in Params().__dict__.items()})
    assert not differences(MANIFEST["params_defaults"], ours)
