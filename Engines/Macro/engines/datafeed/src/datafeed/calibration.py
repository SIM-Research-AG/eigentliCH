"""Calibration: alignment, carry-forward and fill-acceptance rules, versioned.

datafeed has no model to calibrate (engine page section 4). Its "calibration" is the set of
rules that decide what a snapshot contains: how far an annual public-source value may be
carried, how much overlap a candidate needs, and how well it must fit. The version used is
stamped on every snapshot built with it. Seeds are immutable; ``PUT /calibration`` adds
versions.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Calibration

DEFAULT = Calibration(
    version="1.0.0",
    note=("Monthly axis. An annual public value sits at December and is carried at most 11 "
          "months, into missing cells only. A candidate needs 5 overlapping years and must "
          "fit within 10% (levels) or 0.01 absolute (rates)."),
)

SEEDS: tuple[Calibration, ...] = (DEFAULT,)


def canonical_json(calibration: Calibration) -> str:
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
