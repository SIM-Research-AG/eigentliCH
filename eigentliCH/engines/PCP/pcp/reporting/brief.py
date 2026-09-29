"""A short prose brief for a run.

Written so that a reader meets the binding condition before the number, per the house rules. The order is
deliberate: what produced the allocation, then whether it is feasible, then what binds, then the numbers.
An allocation read without its constraints is not interpretable, so the constraints come first.

British spelling, no em-dashes, every projected figure labelled model-derived, and the disclaimer present.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from pcp.config import Config
from pcp.contracts import Result


def render_brief(
    result: Result,
    config: Config,
    diagnostics: Mapping[str, Any] | None = None,
) -> str:
    mandate = result.mandate
    current = result.current
    lines: list[str] = []

    lines.append(f"# {mandate.client} / {mandate.name}: allocation brief")
    lines.append("")
    lines.append(
        f"Model-derived, not a forecast. Optimised for the regime as at {result.as_of} under "
        f"{'the asymmetric squared-shortfall curve fit' if result.optimiser == 'curve' else 'the mean-variance comparison branch'}."
    )
    lines.append("")

    # ---- what produced it ------------------------------------------------
    lines.append("## What produced this")
    lines.append("")
    lines.append(f"- Regime: `{result.regime_id}` (timeline `{result.regime_timeline_id}`, {result.regime_model_version})")
    lines.append(f"- ReturnSet: `{result.return_set_id}` ({result.returnset_model_version}, universe {result.universe_version})")
    lines.append(f"- Engine: {result.engine_version}, speed {result.speed}")
    lines.append(f"- Market scope: {mandate.market}, reported in {mandate.currency}")
    lines.append(f"- Replay: `{result.idempotency_key[:16]}` (trace `{result.trace_id}`)")
    if result.country_weights:
        blend = ", ".join(
            f"{code} {weight:.0%}" for code, weight in sorted(result.country_weights.items())
        )
        lines.append(f"- Regime blend: {blend}")
    lines.append("")

    # ---- feasibility first -----------------------------------------------
    lines.append("## Whether it is feasible")
    lines.append("")
    if current.conditions_met == "yes":
        lines.append(
            "The budget equality was met and the mandate's constraints are satisfied, so the weights below "
            "are a feasible allocation."
        )
    else:
        lines.append(
            "**The budget equality was not met within tolerance.** The weights below have been renormalised "
            "so they sum to one, which does not make the mandate feasible. Read this before the numbers: "
            "the allocation shown may satisfy no constraint set at all."
        )
    lines.append("")
    lines.append(
        f"The crisis tail of the live regime carries {result.crisis_tail:.1%} of the probability mass. "
        f"The objective penalises only shortfall below the mandate curve, weighted by the regime, so this "
        f"is the share of the fit driven by the crisis states."
    )
    lines.append("")

    # ---- what binds ------------------------------------------------------
    lines.append("## What binds")
    lines.append("")
    if current.binding:
        lines.append("These constraints are active at the optimum, so they, not the fit, set the exposures they govern:")
        lines.append("")
        lines.append("| dimension | category | side | bound | realised |")
        lines.append("|---|---|---|---|---|")
        for binding in current.binding:
            lines.append(
                f"| {binding.dimension} | {binding.category} | {binding.side} | "
                f"{binding.bound:.4f} | {binding.realised:.4f} |"
            )
    else:
        lines.append(
            "No constraint is active at the optimum, so every exposure below was chosen by the curve fit "
            "rather than by a limit."
        )
    lines.append("")

    # ---- the allocation --------------------------------------------------
    lines.append("## The allocation")
    lines.append("")
    rows = _instrument_rows(result, diagnostics)
    lines.append("| instrument | weight | role | region | currency | asset class |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        if row["weight"] < 5e-5:
            continue
        lines.append(
            f"| {row['name']} | {row['weight']:.2%} | {row['role']} | {row['region_geo']} | "
            f"{row['currency']} | {row['asset_class']} |"
        )
    held = sum(1 for row in rows if row["weight"] >= 5e-5)
    lines.append("")
    lines.append(
        f"{held} of {len(rows)} instruments in the investable universe carry weight. Positions below "
        f"0.005 percent are omitted from the table as rounding."
    )
    lines.append("")

    # ---- roles and the map ----------------------------------------------
    lines.append("## By role")
    lines.append("")
    lines.append("| role | weight |")
    lines.append("|---|---|")
    for role, weight in current.role_allocation.items():
        lines.append(f"| {role} | {weight:.2%} |")
    lines.append("")
    lines.append(
        f"Weighted-average ESG is {current.esg:.2f} against a mandate floor of {mandate.esg_min:.2f}."
    )
    lines.append("")

    # ---- the curve fit ---------------------------------------------------
    lines.append("## The curve fit")
    lines.append("")
    target = np.asarray(mandate.target_curve, dtype=float)
    achieved = np.asarray(current.return_dist_final, dtype=float)
    lines.append(
        f"The mandate target runs from {target[0]:+.1%} in the most cautious state to {target[-1]:+.1%} in "
        f"the most aggressive. The achieved portfolio profile runs from {achieved[0]:+.1%} to "
        f"{achieved[-1]:+.1%}."
    )
    lines.append("")
    lines.append(
        "The achieved profile is the portfolio's own per-state return and is not the quantity the "
        "objective minimises: the objective weights each instrument's contribution by the regime "
        "probability of the state, so the two can differ while the fit is still optimal for this regime."
    )
    lines.append("")

    if diagnostics is not None and diagnostics.get("weight_leverage") is not None:
        leverage = float(diagnostics["weight_leverage"])
        floor = float(diagnostics["objective_floor"])
        lines.append(
            f"**How much the fit decided.** The objective is {current.objective_value:.6g} against a floor "
            f"of {floor:.6g} with nothing allocated, so the weights control {leverage:.2%} of its level."
        )
        if leverage < 0.05:
            lines.append("")
            lines.append(
                "That is a small share, so this allocation was settled mainly by the mandate's "
                "constraints, with the curve fit acting as a tie-breaker between portfolios the "
                "constraints already permit. Read the binding constraints above as the substantive answer. "
                "The cause is a property of the objective, not a solver failure: it sums shortfall over "
                "instruments before squaring, so an instrument at zero weight still contributes its full "
                "target to every state, and a probability-normalised regime makes each contribution small "
                "against that. Recorded as decisions.md D28 and D29."
            )
        lines.append("")
    if diagnostics is not None and "shortfall_by_state" in diagnostics:
        shortfall = np.asarray(diagnostics["shortfall_by_state"], dtype=float)
        worst = int(np.argmax(shortfall))
        if shortfall[worst] > 0:
            lines.append(
                f"The largest remaining shortfall is in state {worst + 1} of 25, where the summed gap "
                f"below the mandate curve is {shortfall[worst]:.4f}. States with no shortfall are already "
                f"met or exceeded."
            )
            lines.append("")

    if len(result.allocations) > 1:
        lines.append("## Backtest")
        lines.append("")
        infeasible = sum(1 for a in result.allocations if a.conditions_met != "yes")
        lines.append(
            f"{len(result.allocations)} periods re-optimised, from {result.allocations[0].period} to "
            f"{result.allocations[-1].period}. Every path is model-derived, not a forecast and not a "
            f"realised return."
        )
        if infeasible:
            lines.append("")
            lines.append(
                f"**{infeasible} of {len(result.allocations)} periods did not meet the budget equality.** "
                f"Those periods' weights are renormalised and should not be read as feasible allocations."
            )
        lines.append("")

    if result.notes:
        lines.append("## What a reader must know")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(config.disclaimer)
    lines.append("")
    return "\n".join(lines)


def _instrument_rows(
    result: Result,
    diagnostics: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if diagnostics is not None and diagnostics.get("instruments"):
        return sorted(
            (dict(row) for row in diagnostics["instruments"]),
            key=lambda row: -float(row["weight"]),
        )
    current = result.current
    return sorted(
        (
            {
                "name": f"bb_id {bb_id}",
                "weight": float(weight),
                "role": "",
                "region_geo": "",
                "currency": "",
                "asset_class": "",
            }
            for bb_id, weight in zip(current.bb_ids, np.asarray(current.weights, dtype=float))
        ),
        key=lambda row: -float(row["weight"]),
    )
