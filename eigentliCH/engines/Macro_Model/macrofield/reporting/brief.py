"""Auto-generated per-economy prose briefs.

Brief section 6: a short per-economy brief in prose stating the phase, the saturation level, the dominant
stock-to-gold driver and the tail weight, in the first-person-plural analytical register, with no
em-dashes and no fabricated figures, ending with the standard not-investment-advice note.

Two constraints are enforced in code rather than trusted to the author of a template:

- **No em-dashes.** `render` checks its own output and raises if one appears. The house rule is absolute,
  and a generated document is exactly where a stray character slips through unnoticed.
- **No fabricated figures.** Every number in a brief comes from a supplied field. Where a field is
  absent the brief says so in words rather than substituting a plausible value, so a missing diagnostic
  reads as missing rather than as a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from macrofield.reporting.export import DISCLAIMER, PROJECTION_LABEL

#: Characters the house rules forbid anywhere in generated prose.
FORBIDDEN_CHARACTERS = ("—", "–")

#: Wording used wherever a diagnostic could not be computed. Deliberately plain, so that a reader cannot
#: mistake an absence for a result.
UNAVAILABLE = "could not be computed on this run"


class BriefError(ValueError):
    """Raised when a brief cannot be rendered within the house rules."""


@dataclass
class BriefInputs:
    """The facts a brief may state. Anything absent is reported as unavailable, never inferred.

    Attributes:
        economy: The economy's name as it should read in prose.
        window: The (first, last) calibration period.
        phase: The classified phase label.
        phase_rule: The condition that selected the phase.
        saturation: Total credit to the non-financial sector over GDP.
        saturation_band: The (lower, upper) balanced band.
        honi_composite: The HoNI composite on the 1 to 5 axis.
        honi_stage: The four-stage category.
        dominant_driver: The dominant stock-to-gold driver.
        asset_stance: The stance that driver selects.
        tail_probability: Probability on the crisis tail of the regime distribution.
        turning_point_hit_rate: Share of observed turning points the model found.
        turning_point_lead: Mean signed lead in periods; positive means early.
        unsecured_ratio: Unsecured assets as a ratio to output.
        synchronisation_window: The (first, last) periods of the current synchronisation window.
        adjustments_applied: Whether a standardising adjustment was applied.
        caveats: Anything that qualifies the reading.
    """

    economy: str
    window: tuple[int, int]
    phase: str | None = None
    phase_rule: str | None = None
    saturation: float | None = None
    saturation_band: tuple[float, float] = (2.5, 3.5)
    honi_composite: float | None = None
    honi_stage: str | None = None
    dominant_driver: str | None = None
    asset_stance: str | None = None
    tail_probability: float | None = None
    turning_point_hit_rate: float | None = None
    turning_point_lead: float | None = None
    unsecured_ratio: float | None = None
    synchronisation_window: tuple[int, int] | None = None
    adjustments_applied: bool = False
    caveats: list[str] = field(default_factory=list)


def _band_position(saturation: float, band: tuple[float, float]) -> str:
    lower, upper = band
    if saturation > upper:
        return f"above the {lower:.2f} to {upper:.2f} band"
    if saturation < lower:
        return f"below the {lower:.2f} to {upper:.2f} band"
    return f"inside the {lower:.2f} to {upper:.2f} band"


def _driver_phrase(driver: str) -> str:
    return {
        "liquidity_credit_impulse": "the liquidity and credit impulse",
        "innovation_growth": "innovation-driven growth",
        "capital_cycle_currency_stability": "capital-cycle currency stability",
    }.get(driver, driver.replace("_", " "))


def _stance_phrase(stance: str) -> str:
    return {
        "participatory": "participatory assets",
        "value_producing": "value-producing assets",
        "value_preserving": "value-preserving assets",
    }.get(stance, stance.replace("_", " "))


def render(inputs: BriefInputs) -> str:
    """Render the brief.

    Written in the first-person-plural analytical register, per brief section 6.

    Raises:
        BriefError: If the rendered text contains a forbidden character, which would breach the house
            rules, or if the calibration window runs backwards.
    """
    first, last = inputs.window
    if first > last:
        raise BriefError(f"the calibration window {inputs.window} runs backwards")

    paragraphs: list[str] = []

    # Position.
    opening = [
        f"We calibrate {inputs.economy} over {first} to {last}."
    ]
    if inputs.phase:
        opening.append(f"The economy classifies in the {inputs.phase} phase.")
        if inputs.phase_rule:
            opening.append(f"That reading follows from {inputs.phase_rule}.")
    else:
        opening.append(f"The phase {UNAVAILABLE}.")

    if inputs.saturation is not None:
        opening.append(
            f"Credit to the non-financial sector stands at {inputs.saturation:.2f} times output, "
            f"{_band_position(inputs.saturation, inputs.saturation_band)} derived from the bifurcation "
            f"analysis."
        )
    else:
        opening.append(f"The saturation level {UNAVAILABLE}.")
    paragraphs.append(" ".join(opening))

    # Health and coverage.
    health: list[str] = []
    if inputs.honi_composite is not None:
        health.append(
            f"The Health of Nations composite reads {inputs.honi_composite:.2f} on the one to five axis, "
            f"on which five is healthiest."
        )
        if inputs.honi_stage:
            health.append(f"That places the economy in the {inputs.honi_stage} stage.")
    else:
        health.append(f"The Health of Nations composite {UNAVAILABLE}.")

    if inputs.unsecured_ratio is not None:
        health.append(
            f"Financial value not covered by the productive economy stands at "
            f"{inputs.unsecured_ratio:.2f} times output."
        )
    paragraphs.append(" ".join(health))

    # Asset stance.
    stance: list[str] = []
    if inputs.dominant_driver:
        stance.append(
            f"The dominant driver of the gold-to-equity ratio is {_driver_phrase(inputs.dominant_driver)}."
        )
        if inputs.asset_stance:
            stance.append(f"On that reading the stance favours {_stance_phrase(inputs.asset_stance)}.")
    else:
        stance.append(f"The dominant stock-to-gold driver {UNAVAILABLE}.")

    if inputs.tail_probability is not None:
        stance.append(
            f"The regime distribution carries {inputs.tail_probability:.1%} on the crisis tail."
        )
    else:
        stance.append(f"The crisis tail weight {UNAVAILABLE}.")
    paragraphs.append(" ".join(stance))

    # What the model gets right, which is the part that decides how much weight to give the rest.
    quality: list[str] = []
    if inputs.turning_point_hit_rate is not None:
        quality.append(
            f"Against the observed record the model identifies "
            f"{inputs.turning_point_hit_rate:.0%} of turning points"
        )
        if inputs.turning_point_lead is not None:
            if abs(inputs.turning_point_lead) < 0.5:
                quality.append("with broadly coincident timing.")
            elif inputs.turning_point_lead > 0:
                quality.append(
                    f"turning on average {inputs.turning_point_lead:.1f} periods early."
                )
            else:
                quality.append(
                    f"turning on average {abs(inputs.turning_point_lead):.1f} periods late."
                )
        else:
            quality.append("although the timing error is not reported.")
        quality.append(
            "We read the trend and the turning points rather than the levels, which the model does not "
            "reproduce closely and is not intended to."
        )
    else:
        quality.append(f"Turning-point agreement {UNAVAILABLE}.")

    if inputs.synchronisation_window:
        window_first, window_last = inputs.synchronisation_window
        quality.append(
            f"The cycles come into phase over {window_first} to {window_last} on this data vintage, "
            f"which the framework identifies as the regime of peak fragility. This window is recomputed "
            f"each run and moves with the vintage, so it is {PROJECTION_LABEL} and should be re-derived "
            f"rather than carried forward."
        )
    paragraphs.append(" ".join(quality))

    # Caveats.
    caveats = list(inputs.caveats)
    if inputs.adjustments_applied:
        caveats.append(
            "a standardising level adjustment has been applied to the source data, so the levels quoted "
            "are not the published levels. The adjustment cannot alter growth rates, direction or "
            "turning points."
        )
    if caveats:
        paragraphs.append(
            "We qualify this reading as follows: " + "; ".join(caveats) + "."
        )

    paragraphs.append(DISCLAIMER)

    text = "\n\n".join(paragraphs)
    _assert_house_rules(text)
    return text


def _assert_house_rules(text: str) -> None:
    """Check generated prose against the house rules.

    Raises:
        BriefError: If a forbidden character appears.
    """
    for character in FORBIDDEN_CHARACTERS:
        if character in text:
            position = text.index(character)
            context = text[max(0, position - 40) : position + 40]
            raise BriefError(
                f"the generated brief contains a forbidden character {character!r} near: ...{context}... "
                f"The house rules forbid it, so the brief is refused rather than emitted."
            )


def word_count(text: str) -> int:
    """Return the word count, used to keep briefs short as section 6 requires."""
    return len(re.findall(r"\b\w[\w'-]*\b", text))
