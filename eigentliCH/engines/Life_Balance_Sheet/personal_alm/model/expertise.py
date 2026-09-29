"""Expertise capital — SEAM 1: vector E (spec §3.1).

v1 uses a single component, but E is wrapped in an array-backed type from day one
so that promoting it to a vector of domain-specific capitals (a career pivot seeds
a new component; existing network lifts its ceiling) never touches the equations
that reference it. Income consumes an *aggregate*, so its interface is stable
whether d == 1 or d == 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Expertise:
    """Domain-specific expertise stocks. v1: a single active domain (d == 1)."""

    components: np.ndarray
    weights: np.ndarray | None = None  # aggregation weights; default equal

    def __post_init__(self) -> None:
        self.components = np.atleast_1d(np.asarray(self.components, dtype=float))
        if self.weights is None:
            self.weights = np.ones_like(self.components)
        else:
            self.weights = np.atleast_1d(np.asarray(self.weights, dtype=float))
        if self.weights.shape != self.components.shape:
            raise ValueError("expertise weights must match components shape")

    @classmethod
    def scalar(cls, value: float) -> "Expertise":
        """Construct the v1 single-domain expertise."""
        return cls(components=np.array([float(value)]))

    @property
    def dim(self) -> int:
        return int(self.components.size)

    def aggregate(self) -> float:
        """Scalar expertise entering income's Cobb–Douglas term.

        For d == 1 this is just the single component; the weighted sum
        generalises it without changing the income equation's signature.
        """
        return float(np.dot(self.weights, self.components))

    def copy(self) -> "Expertise":
        return Expertise(components=self.components.copy(), weights=self.weights.copy())
