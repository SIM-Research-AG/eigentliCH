"""Calibration: cycle definitions, bands, anchors, widths and thresholds, and nothing else.

Every figure is copied from the first draft's ``config/defaults.yaml`` (section ``cycles``,
Macro_Model, as of 2026-08-02) and is unchanged. What is new is that the cycle set itself is
a parameter: each cycle names how it is found (estimated or anchored), what it reads, its
orientation on the 25-bin axis and whether it enters the interference measure.

Four seed versions ship with the engine:

``1.0.0``
    The five nested cycles: the 3.6-year fundamental pulse, the 7-year business cycle and
    the 18-year credit cycle band-passed from real output growth, the innovation cycle
    anchored on a low in 2032 with a 47-year period, and the 90-year capital cycle
    anchored where capital saturation crosses 3.5. The 130-year hegemonic succession of the
    draft is not one of the five; a calibration can add it as an ``anchored_peak`` (1945,
    130 years, ``in_interference: false``).

``1.1.0``
    1.0.0 with the capital cycle of every economy anchored on a
    historical reset (``RESETS``) instead of the saturation crossing, and reshaped
    (``rise_fall``): low at the reset, a 90-year rise to the peak, a 40-year fall to the next
    reset at 130 years, the hegemonic period. The credit cycle is anchored on each economy's
    credit crisis (``CREDIT_LOWS``, its low) with an 18-year period, instead of band-passed.
    The pulse and business cycles are band-passed from macrofield's observed output Y, in
    current US dollars as the first draft read it, which runs back to 1972 for some economies.

``1.2.0``
    1.1.0 with the capital cycle's risk reading inverted. Its peak is read as the aggressive
    end of the 25-bin axis (orientation +1), like the other cycles.

``1.3.0``
    The active version: 1.2.0 with the capital shape inverted (``fall_rise``): peak at the
    reset, low at saturation 90 years later, next reset at 130. High level means aggressive
    for every cycle; a saturated economy sits at the cautious end of the axis.

A seed can never be changed in place. To change a figure, propose a new version through
``PUT /calibration``; the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Calibration, CycleSpec

_CYCLES = (
    CycleSpec(
        name="fundamental_pulse", kind="estimated", input="output_growth", period_years=3.6,
        # Narrowed from 3.6 +/- 40% (2.16 to 5.04): 2.16 years against annual sampling sits
        # at the Nyquist limit and would alias. Still marginal: 3.6 intervals per period.
        band=(3.0, 4.5),
        source="frequency analysis of the Officer-Williamson real-return series; band 2026-08-02",
    ),
    CycleSpec(name="business", kind="estimated", input="output_growth", period_years=7.0,
              source="frequency analysis; Capital Saturation ch. 6.4 and 9"),
    CycleSpec(name="credit", kind="estimated", input="output_growth", period_years=18.0,
              source="frequency analysis; Capital Saturation ch. 6.4 and 9"),
    CycleSpec(name="innovation", kind="anchored_trough", anchor_year=2032.0, period_years=47.0,
              source="author, 2026-07-27; period the midpoint of the observed 40 to 54 year band"),
    CycleSpec(name="capital", kind="anchored_saturation", anchor_saturation=3.5,
              years_into_cycle_at_anchor=90.0, period_years=90.0, orientation=-1,
              source="author, 2026-07-27; orientation corrected 2026-08-02"),
)

DEFAULT = Calibration(
    version="1.0.0",
    note=(
        "The five nested cycles of the first draft (cycles.py, cycle_bins.py): pulse, business "
        "and credit band-passed from real output growth, innovation and capital anchored. "
        "Draft figures unchanged."
    ),
    cycles=_CYCLES,
)

#: Historical resets, year 0 of each economy's capital cycle. Chosen by the author on
#: 2026-09-27: CN given; the others read off history and confirmed one by one.
RESETS: dict[str, float] = {
    "US": 1933.0,   # New Deal, bank holiday
    "EU": 1945.0,   # end of the war, post-war order
    "CH": 1936.0,   # franc devaluation, leaving the gold bloc
    "BR": 1964.0,   # 1964 regime and its reordering
    "TH": 1932.0,   # end of absolute monarchy
    "CN": 1948.0,   # founding of the new order
    "IN": 1947.0,   # independence
    "ID": 1966.0,   # New Order
    "MY": 1963.0,   # formation of Malaysia
    "PH": 1946.0,   # independence
    "GB": 1945.0,   # post-war settlement
    "JP": 1945.0,   # end of war
    "BD": 1971.0,   # independence
    "VN": 1986.0,   # Doi Moi
    "DE": 1948.0,   # currency reform
    "ES": 1939.0,   # end of the civil war
}

#: Credit-cycle lows (crises), one per economy, chosen by the author on 2026-09-27.
CREDIT_LOWS: dict[str, float] = {
    "US": 2009.0, "GB": 2009.0, "DE": 2009.0, "CH": 2009.0, "EU": 2009.0,   # Global Financial Crisis
    "ES": 2012.0,                                                           # banking crisis, bailout
    "TH": 1998.0, "MY": 1998.0, "ID": 1998.0, "PH": 1998.0,                 # Asian financial crisis
    "JP": 1998.0,   # banking crisis
    "CN": 2015.0,   # stock crash, deleveraging
    "IN": 2013.0,   # taper tantrum
    "BR": 2016.0,   # deep recession
    "VN": 2012.0,   # banking stress
    "BD": 2011.0,   # stock-market crash
}


def _v110(c) -> dict:
    d = c.model_dump()
    if c.name == "capital":
        return {**d, "resets": RESETS, "shape": "rise_fall", "period_years": 130.0,
                "source": ("author, 2026-09-27: historical resets per economy; low at the reset, peak "
                           "90 years later, next reset at 130 (the hegemonic period); orientation 2026-08-02")}
    if c.name in ("fundamental_pulse", "business"):
        return {**d, "input": "macrofield_output_growth",
                "source": d["source"] + "; reads macrofield output (current USD), author 2026-09-27"}
    if c.name == "credit":
        return {**d, "kind": "anchored_trough", "input": None, "band": None, "anchor_years": CREDIT_LOWS,
                "source": ("author, 2026-09-27: anchored on each economy's credit crisis (low), 18 years; "
                           "20 years of data cannot identify an 18-year cycle")}
    return d


HISTORICAL_RESETS = Calibration.model_validate({
    **DEFAULT.model_dump(),
    "version": "1.1.0",
    "parent_version": "1.0.0",
    "note": (
        "1.0.0 with the capital cycle anchored on a historical reset for every economy, supplied "
        "by the author, instead of the saturation crossing, which dated only five of sixteen "
        "economies; and reshaped: low at the reset, a 90-year rise to the peak, a 40-year fall to "
        "the next reset at 130 years. The credit cycle is anchored on each economy's credit crisis "
        "(its low), 18 years, since the sample cannot identify it. The pulse and business cycles "
        "read macrofield's output Y (current US dollars, as the draft)."
    ),
    "cycles": [_v110(c) for c in DEFAULT.cycles],
})

CAPITAL_AGGRESSIVE = Calibration.model_validate({
    **HISTORICAL_RESETS.model_dump(),
    "version": "1.2.0",
    "parent_version": "1.1.0",
    "note": (
        "1.1.0 with the capital cycle's risk reading inverted: its peak (year 90 after the reset) "
        "is read as the aggressive end of the 25-bin axis, like every other cycle, instead of the "
        "cautious end. Shape, resets and all other cycles unchanged."
    ),
    "cycles": [c.model_dump() if c.name != "capital" else {
                   **c.model_dump(), "orientation": 1,
                   "source": c.source + "; orientation inverted to +1 by the author, 2026-09-28"}
               for c in HISTORICAL_RESETS.cycles],
})

CAPITAL_INVERTED = Calibration.model_validate({
    **CAPITAL_AGGRESSIVE.model_dump(),
    "version": "1.3.0",
    "parent_version": "1.2.0",
    "note": (
        "1.2.0 with the capital cycle's shape inverted so it reads like the others (high "
        "level = aggressive): peak at the reset, a 90-year fall to its low at saturation, a "
        "40-year rise to the next reset at 130 years. A saturated economy sits at the cautious "
        "end of the 25-bin axis again, as in 1.1.0."
    ),
    "cycles": [c.model_dump() if c.name != "capital" else {
                   **c.model_dump(), "shape": "fall_rise",
                   "source": c.source + "; shape inverted to fall_rise by the author, 2026-09-28"}
               for c in CAPITAL_AGGRESSIVE.cycles],
})

SEEDS: tuple[Calibration, ...] = (DEFAULT, HISTORICAL_RESETS, CAPITAL_AGGRESSIVE, CAPITAL_INVERTED)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
