"""Ingest: read the consumed contracts and the mandate into typed objects.

Everything here reads. Nothing here computes a Regime, estimates a return profile, or fills a missing
input. A run that needs an unavailable input fails loudly at this boundary rather than proceeding on a
substituted value, which is why these modules raise on absence instead of returning a default.
"""

from pcp.ingest.mandate import MandateNotFound, list_mandates, load_mandate
from pcp.ingest.regime import (
    RegimeBlend,
    blend_regimes,
    load_regime,
    load_regime_for_market,
    resolve_country_weights,
)
from pcp.ingest.returnset import load_returnset

__all__ = [
    "MandateNotFound",
    "RegimeBlend",
    "blend_regimes",
    "list_mandates",
    "load_mandate",
    "load_regime",
    "load_regime_for_market",
    "load_returnset",
    "resolve_country_weights",
]
