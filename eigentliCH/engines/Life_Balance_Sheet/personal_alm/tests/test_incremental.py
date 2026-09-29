"""A run that is killed must keep what it finished.

**The case that forced this.** A twenty-four-year-old's risk assessment ran three hours: one two-phase solve,
then the achievable-goal search, which spends a further complete solve per probe. `ENGINE_TIMEOUT_S` is 3600,
so in the desktop flow that run would have been killed and everything discarded — including the main solve,
which had finished long before and whose facts are the deliverable.

Every test here drives the search with a stub runner. The point is the bookkeeping around the solves, not the
solves, and an hour of IPOPT would test the wrong thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest

from personal_alm.optim.achievable import largest_fundable


@dataclass
class FakeResult:
    p_goal: float
    shortfall: float = 0.0


def case_for(amount: float, confidence: float = 0.9):
    """A minimal case object, built through the engine's own converter so the shape is real."""
    from personal_alm.app.onboarding import case_from_submission
    sub = {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22"},
        "state": {"age": 45, "W_L": 300_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 400_000.0, "W_3a": 80_000.0, "H": 0.9, "N": 0.5, "E": 0.6},
        "params": {"G": 90_000.0, "ahv_record_share": 1.0, "epsilon": 1.0 - confidence},
        "goals": [{"kind": "fi", "description": "Unabhängigkeit", "target_year": 2046,
                   "amount_chf": amount, "confidence": confidence, "is_consumption": False}],
        "raw": {"birth_year": 1981, "income_gross": 200_000.0, "spend_now": 90_000.0},
    }
    return case_from_submission(sub).case


# --- the search reports each probe as it completes --------------------------------------------------------

def test_every_probe_is_reported_as_it_finishes():
    """**Each probe is a full solve.** A caller that records the bracket as it moves keeps an answer when the
    run is killed; before this, an hour of solving was discarded entire."""
    seen: list[tuple[int, float, bool, float]] = []

    def never_funded(case, **kw):
        return FakeResult(p_goal=0.10, shortfall=20_000.0)

    largest_fundable(case_for(90_000.0), probes=3, run=never_funded,
                     on_probe=lambda *a: seen.append(a))
    assert len(seen) >= 2, seen
    # The count is the running total, so a reader knows how far the search got.
    assert [row[0] for row in seen] == sorted(row[0] for row in seen)
    assert all(isinstance(row[1], float) and isinstance(row[2], bool) for row in seen)


def test_a_callback_that_raises_cannot_destroy_the_search():
    """It exists to preserve the search; letting it take the search down would invert its purpose."""
    def never_funded(case, **kw):
        return FakeResult(p_goal=0.10, shortfall=20_000.0)

    def explode(*_a):
        raise RuntimeError("the caller's disk is full")

    got = largest_fundable(case_for(90_000.0), probes=3, run=never_funded, on_probe=explode)
    assert got.probes_used >= 1


def test_no_callback_is_the_default_and_changes_nothing():
    def never_funded(case, **kw):
        return FakeResult(p_goal=0.10, shortfall=20_000.0)

    with_cb = largest_fundable(case_for(90_000.0), probes=3, run=never_funded, on_probe=lambda *a: None)
    without = largest_fundable(case_for(90_000.0), probes=3, run=never_funded)
    assert with_cb.probes_used == without.probes_used
    assert with_cb.largest_amount == without.largest_amount


# --- befund writes what it reaches ------------------------------------------------------------------------

def test_the_main_solve_is_snapshotted_before_the_search_starts(monkeypatch):
    """**The whole point.** The search is the optional second half and costs a solve per probe; the facts from
    the main solve are the deliverable and must survive a kill during it."""
    from personal_alm.app import befund as B

    snapshots: list[dict] = []
    order: list[str] = []

    def fake_run_case(case, **kw):
        order.append("solve")
        return FakeResult(p_goal=0.10, shortfall=20_000.0)

    def fake_search(case, **kw):
        order.append("search")
        cb = kw.get("on_probe")
        if cb:
            cb(1, 50_000.0, False, 0.2)
        return None

    monkeypatch.setattr(B, "run_case", fake_run_case)
    monkeypatch.setattr(B, "largest_fundable", fake_search)
    monkeypatch.setattr(B, "report_facts", _stub_report_facts)

    sub = _submission()
    B.befund(sub, settings={"M_opt": 1, "M_eval": 4, "seed": 0, "n_starts": 1},
             achievable_probes=2, progress=snapshots.append)

    assert order[0] == "solve"
    assert snapshots, "a snapshot must exist before the search runs"
    assert snapshots[0]["partial"] is True
    assert snapshots[0]["probes_done"] == 0


def test_a_snapshot_is_written_after_each_probe(monkeypatch):
    from personal_alm.app import befund as B
    snapshots: list[dict] = []

    def fake_run_case(case, **kw):
        return FakeResult(p_goal=0.10, shortfall=20_000.0)

    def fake_search(case, **kw):
        cb = kw.get("on_probe")
        for i in (1, 2, 3):
            cb(i, 90_000.0 / i, False, 0.1)
        return None

    monkeypatch.setattr(B, "run_case", fake_run_case)
    monkeypatch.setattr(B, "largest_fundable", fake_search)
    monkeypatch.setattr(B, "report_facts", _stub_report_facts)

    B.befund(_submission(), settings={"M_opt": 1, "M_eval": 4, "seed": 0, "n_starts": 1},
             achievable_probes=4, progress=snapshots.append)
    assert [s["probes_done"] for s in snapshots] == [0, 1, 2, 3]


def test_the_returned_object_is_not_marked_partial(monkeypatch):
    """A finished run must not look interrupted, or every consumer learns to ignore the flag."""
    from personal_alm.app import befund as B
    monkeypatch.setattr(B, "run_case", lambda case, **kw: FakeResult(p_goal=0.95))
    monkeypatch.setattr(B, "report_facts", _stub_report_facts)
    out = B.befund(_submission(), settings={"M_opt": 1, "M_eval": 4, "seed": 0, "n_starts": 1},
                   achievable_probes=0)
    assert "partial" not in out
    assert "publishable" in out


def test_a_progress_writer_that_fails_does_not_take_the_run_down(monkeypatch, capsys):
    from personal_alm.app import befund as B
    monkeypatch.setattr(B, "run_case", lambda case, **kw: FakeResult(p_goal=0.95))
    monkeypatch.setattr(B, "report_facts", _stub_report_facts)

    def explode(_snap):
        raise OSError("disk full")

    out = B.befund(_submission(), settings={"M_opt": 1, "M_eval": 4, "seed": 0, "n_starts": 1},
                   achievable_probes=0, progress=explode)
    assert "publishable" in out
    assert "progress snapshot failed" in capsys.readouterr().err


# --- helpers ----------------------------------------------------------------------------------------------

class _StubFacts:
    """Stands in for `ReportFacts`, which needs a real solve to build. Only the two things `befund` reads."""

    def __init__(self, achievable):
        self.publishable = True
        self._achievable = achievable

    def to_dict(self):
        return {"stub": True, "achievable_amount": getattr(self._achievable, "largest_amount", None)}


def _stub_report_facts(case, result, **kw):
    return _StubFacts(kw.get("achievable"))


def _submission():
    return {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22"},
        "state": {"age": 45, "W_L": 300_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 400_000.0, "W_3a": 80_000.0, "H": 0.9, "N": 0.5, "E": 0.6},
        "params": {"G": 90_000.0, "ahv_record_share": 1.0, "epsilon": 0.10},
        "goals": [{"kind": "fi", "description": "Unabhängigkeit", "target_year": 2046,
                   "amount_chf": 90_000.0, "confidence": 0.90, "is_consumption": False}],
        "raw": {"birth_year": 1981, "income_gross": 200_000.0, "spend_now": 90_000.0},
    }
