"""Which Regime a pcp run uses: the latest succeeded Regime of one optimism level (C-30).

aggregation issues one Regime per optimism level (defensive, default, aggressive, rogue) in one go,
so its newest run says nothing about the level: it is whichever level happened to finish last. The
Regime is therefore chosen by level, read from aggregation (its runs, and the Regime's own
``optimism_scale`` from ``GET /regime/{id}/current``), never by position in a list. A scenario is
derived from the chosen base Regime (``POST /scenario``), so it keeps the base's level.

Used by the Parameters page (``GET /api/curator/regime``) and by the run route when the caller names
no Regime, so a scripted caller gets the ``default`` level unless it names another. Routing only: no
figure is computed here.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .clients import Engines, _describe
from .settings import Engine

#: aggregation's optimism levels, from its contract (``OptimismScale``), cautious to bold.
LEVELS: tuple[str, ...] = ("defensive", "default", "aggressive", "rogue")
DEFAULT_LEVEL = "default"
#: How far back aggregation's run list is read; four runs per issue, so this covers many issues.
RUN_WINDOW = 200


class RegimeProblem(Exception):
    """aggregation cannot give the Regime asked for; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _when(run: dict[str, Any]) -> str:
    return str(run.get("finished_at") or run.get("started_at") or "")


async def _get(engines: Engines, agg: Engine, path: str) -> Any:
    try:
        return await engines.get_json(agg, path)
    except httpx.HTTPStatusError as exc:
        raise RegimeProblem(502, f"aggregation {path} answered {exc.response.status_code}: "
                                 f"{exc.response.text[:300]}") from exc
    except httpx.HTTPError as exc:
        raise RegimeProblem(502, f"aggregation is {_describe(exc)} at {agg.url}") from exc
    except ValueError as exc:
        raise RegimeProblem(502, f"aggregation {path} did not answer JSON") from exc


async def regime_level(engines: Engines, agg: Engine, regime_id: str) -> Optional[str]:
    """The Regime's own optimism level, as aggregation states it (None when it names none)."""
    cur = await _get(engines, agg, f"/regime/{regime_id}/current")
    return cur.get("optimism_scale") if isinstance(cur, dict) else None


async def levels(engines: Engines, agg: Engine) -> list[dict[str, Any]]:
    """The four levels with their labels. aggregation's model card and calibration name no labels, so
    the label is the level's name; the calibration's target state is given as the description."""
    targets: dict[str, Any] = {}
    try:
        cal = await engines.get_json(agg, "/calibration")
        targets = ((cal or {}).get("optimism") or {}).get("targets") or {}
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    out = []
    for key in LEVELS:
        t = targets.get(key)
        out.append({"key": key, "label": key.capitalize(), "default": key == DEFAULT_LEVEL,
                    "target_state": t,
                    "description": (f"target state {t:g} of 25 in aggregation's calibration")
                                   if isinstance(t, (int, float)) else ""})
    return out


async def choose(engines: Engines, agg: Engine, optimism: Optional[str] = None,
                 policy: Optional[str] = None) -> dict[str, Any]:
    """The latest succeeded Regime of ``optimism`` (``default`` when None), and, with ``policy``,
    the scenario Regime aggregation derives from it."""
    level = optimism or DEFAULT_LEVEL
    if level not in LEVELS:
        raise RegimeProblem(422, f"no optimism level {level!r}: one of {', '.join(LEVELS)}")
    runs = await _get(engines, agg, f"/runs?limit={RUN_WINDOW}")
    done = [r for r in (runs if isinstance(runs, list) else [])
            if isinstance(r, dict) and r.get("status") == "succeeded" and r.get("regime_id")]
    done.sort(key=_when, reverse=True)  # newest first by time, whatever order the list came in
    checked: dict[str, Optional[str]] = {}
    base = None
    for run in done:
        listed = run.get("optimism_scale")
        if listed is not None and listed != level:
            continue  # the run says itself it issued another level
        rid = run["regime_id"]
        if rid not in checked:
            checked[rid] = await regime_level(engines, agg, rid)
        if checked[rid] == level:  # the Regime's own optimism_scale decides
            base = run
            break
    if base is None:
        raise RegimeProblem(404, f"aggregation has no succeeded run at optimism level {level!r} among its latest "
                                 f"{RUN_WINDOW} runs: run aggregation (it issues every level) and try again")
    out: dict[str, Any] = {"optimism": level, "regime_id": base["regime_id"], "base_regime_id": base["regime_id"],
                           "policy": None, "cached": None, "run_id": base.get("run_id"),
                           "run_finished_at": base.get("finished_at") or base.get("started_at")}
    if policy:
        try:
            r = await engines.forward(agg, "POST", "scenario", "",
                                      json.dumps({"base_regime_id": base["regime_id"], "policy": policy}).encode("utf-8"),
                                      "application/json")
        except httpx.HTTPError as exc:
            raise RegimeProblem(502, f"aggregation is {_describe(exc)} at {agg.url}: no scenario Regime") from exc
        if r.status_code >= 400:
            raise RegimeProblem(422 if r.status_code == 422 else 502,
                                f"aggregation /scenario answered {r.status_code}: {r.text[:300]}")
        s = r.json()
        out.update(regime_id=s["regime_id"], policy=s.get("policy") or policy,
                   base_regime_id=s.get("base_regime_id") or base["regime_id"], cached=s.get("cached"))
    return out
