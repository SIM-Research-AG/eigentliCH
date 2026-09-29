"""Reporting for a portfolio challenge.

Ordered so the reader meets admissibility before quality. Whether a proposal is allowed under the mandate
is a different kind of fact from whether it fits the curve well, and a breach is not made acceptable by a
good objective value.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pcp.config import Config
from pcp.contracts import Result
from pcp.model.challenge import ChallengeResult


def challenge_payload(
    challenge: ChallengeResult,
    result: Result,
    config: Config,
) -> dict[str, Any]:
    """The machine-readable comparison, stamped like every other artefact."""
    mandate = result.mandate
    return {
        "header": {
            "client": mandate.client,
            "mandate": mandate.name,
            "market": mandate.market,
            "currency": mandate.currency,
            "as_of": result.as_of,
            "regime_id": result.regime_id,
            "return_set_id": result.return_set_id,
            "universe_version": result.universe_version,
            "engine_version": result.engine_version,
            "idempotency_key": result.idempotency_key,
            "trace_id": result.trace_id,
            "label": result.label,
            "values_unit": str(config.get("contracts.expected_values_unit")),
            "comparison": (
                "both portfolios scored on the same objective, regime, profile matrix and mandate curve"
            ),
            "disclaimer": config.disclaimer,
        },
        "admissible": challenge.admissible,
        "breaches": [
            {
                "kind": b.kind,
                "dimension": b.dimension,
                "category": b.category,
                "side": b.side,
                "limit": b.limit,
                "realised": b.realised,
                "size": b.size,
                "description": b.describe(),
            }
            for b in challenge.breaches
        ],
        "objective": {
            "proposed": challenge.proposed.objective_value,
            "optimised": challenge.optimised.objective_value,
            "gap": challenge.objective_gap,
            "ratio": challenge.objective_ratio,
            "note": (
                "a worse objective means a worse fit to the mandate curve under this regime, which is the "
                "mandate's own definition of good. It is not by itself a reason to change a holding."
            ),
        },
        "shortfall_by_state": {
            "proposed": [float(v) for v in challenge.proposed.shortfall_by_state],
            "optimised": [float(v) for v in challenge.optimised.shortfall_by_state],
        },
        "worst_states": challenge.worst_states(5),
        "achieved_curve": {
            "proposed": [float(v) for v in challenge.proposed.achieved_curve],
            "optimised": [float(v) for v in challenge.optimised.achieved_curve],
            "target": [float(v) for v in np.asarray(mandate.target_curve, dtype=float)],
        },
        "esg": {
            "proposed": challenge.proposed.esg,
            "optimised": challenge.optimised.esg,
            "minimum": mandate.esg_min,
        },
        "role_allocation": {
            "proposed": challenge.proposed.role_allocation,
            "optimised": challenge.optimised.role_allocation,
        },
        "exposure_differences": challenge.exposure_differences(),
        "weight_differences": challenge.weight_differences(),
        "outside_universe": list(challenge.outside_universe),
        "notes": list(challenge.notes),
    }


def render_challenge(
    challenge: ChallengeResult,
    result: Result,
    config: Config,
) -> str:
    """A prose brief for the comparison."""
    mandate = result.mandate
    lines: list[str] = []

    lines.append(f"# {mandate.client} / {mandate.name}: portfolio challenge")
    lines.append("")
    lines.append(
        f"A proposed portfolio scored against the optimised allocation, on the same objective, the same "
        f"regime as at {result.as_of}, and the same mandate limits. Model-derived, not a forecast."
    )
    lines.append("")
    lines.append(f"- Regime: `{result.regime_id}`")
    lines.append(f"- ReturnSet: `{result.return_set_id}` (universe {result.universe_version})")
    lines.append(f"- Engine: {result.engine_version}, trace `{result.trace_id}`")
    lines.append("")

    # ---- admissibility first ---------------------------------------------
    lines.append("## Is it allowed under the mandate")
    lines.append("")
    if challenge.admissible:
        lines.append(
            "Yes. The proposal respects every mandate limit: the budget equality, all category bounds, "
            "the maximum single position, the ESG floor, and the investable universe."
        )
    else:
        lines.append(
            f"**No. The proposal breaches {len(challenge.breaches)} mandate limit(s).** A breach is not "
            f"offset by a good fit: these are the mandate's own constraints, and a portfolio that fails "
            f"them is outside what was agreed."
        )
        lines.append("")
        lines.append("| breach | limit | realised |")
        lines.append("|---|---|---|")
        for breach in challenge.breaches:
            lines.append(
                f"| {breach.describe()} | {breach.limit:.4f} | {breach.realised:.4f} |"
            )
    lines.append("")

    # ---- how much worse --------------------------------------------------
    lines.append("## How well it fits")
    lines.append("")
    ratio = challenge.objective_ratio
    if challenge.objective_gap <= 1e-12:
        lines.append(
            f"The proposal fits at least as well as the optimised allocation on this objective "
            f"({challenge.proposed.objective_value:.6g} against "
            f"{challenge.optimised.objective_value:.6g}). Where a proposal scores better than the "
            f"optimum, the optimiser did not converge to it and that is worth investigating."
        )
    else:
        multiple = f"{ratio:.2f} times" if ratio is not None else "not expressible as a multiple, the optimum being zero"
        lines.append(
            f"The proposal scores {challenge.proposed.objective_value:.6g} against the optimum's "
            f"{challenge.optimised.objective_value:.6g}, so it is {multiple} the shortfall the mandate "
            f"could achieve under this regime."
        )
    lines.append("")

    worst = challenge.worst_states(5)
    if worst:
        lines.append(
            "The gap is not spread evenly. These regime states account for most of it, state 1 being the "
            "most cautious and 25 the most aggressive:"
        )
        lines.append("")
        lines.append("| state | proposed shortfall | optimised shortfall | gap |")
        lines.append("|---|---|---|---|")
        for row in worst:
            lines.append(
                f"| {row['state']} | {row['proposed_shortfall']:.4f} | "
                f"{row['optimised_shortfall']:.4f} | {row['gap']:.4f} |"
            )
        lines.append("")
        if any(row["state"] <= 5 for row in worst):
            lines.append(
                "At least one of those states is in the crisis tail, so the proposal is materially more "
                "exposed than the optimum where the mandate is hardest to meet. That is a different "
                "finding from being uniformly slightly behind."
            )
            lines.append("")

    # ---- where the weight differs ---------------------------------------
    lines.append("## Where the weight differs")
    lines.append("")
    rows = [r for r in challenge.weight_differences() if abs(r["difference"]) >= 5e-4]
    if rows:
        lines.append("| instrument | proposed | optimised | difference |")
        lines.append("|---|---|---|---|")
        for row in rows[:20]:
            flag = "" if row["in_universe"] else " (outside the universe)"
            lines.append(
                f"| {row['name']}{flag} | {row['proposed']:.2%} | {row['optimised']:.2%} | "
                f"{row['difference']:+.2%} |"
            )
        if len(rows) > 20:
            lines.append("")
            lines.append(f"{len(rows) - 20} smaller difference(s) omitted.")
    else:
        lines.append("The two portfolios are the same to within five basis points per instrument.")
    lines.append("")

    lines.append("## By role")
    lines.append("")
    lines.append("| role | proposed | optimised | difference |")
    lines.append("|---|---|---|---|")
    for role in challenge.proposed.role_allocation:
        p = challenge.proposed.role_allocation[role]
        o = challenge.optimised.role_allocation[role]
        lines.append(f"| {role} | {p:.2%} | {o:.2%} | {p - o:+.2%} |")
    lines.append("")
    lines.append(
        f"Weighted-average ESG is {challenge.proposed.esg:.2f} proposed against "
        f"{challenge.optimised.esg:.2f} optimised, on a mandate floor of {mandate.esg_min:.2f}."
    )
    lines.append("")

    if challenge.notes:
        lines.append("## What a reader must know")
        lines.append("")
        for note in challenge.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(config.disclaimer)
    lines.append("")
    return "\n".join(lines)
