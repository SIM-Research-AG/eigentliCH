"""Reporting: machine-readable export, static charts, and the auto-generated per-economy briefs.

Every artefact this package produces carries the calibration window, the data vintage, the projection
label on any projected path, and the not-investment-advice disclaimer. Those are enforced at the write
boundary rather than left to each caller, per brief section 6.
"""

from macrofield.reporting.export import DISCLAIMER, PROJECTION_LABEL

__all__ = ["DISCLAIMER", "PROJECTION_LABEL"]
