"""Shared helpers: where the golden files are, and the one comparison every golden test uses."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"
TOL = 1e-9


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def differences(expected: Any, actual: Any, path: str = "", tol: float = TOL) -> list[str]:
    """Every leaf where ``actual`` differs from ``expected``: floats within ``tol`` (relative above 1, absolute
    below), everything else exact. Strings, booleans, None and every list length must match exactly."""
    out: list[str] = []
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual and expected != actual or type(expected) is not type(actual):
            out.append(f"{path}: {expected!r} != {actual!r}")
        return out
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        a, b = float(expected), float(actual)
        if math.isnan(a) or math.isnan(b):
            if not (math.isnan(a) and math.isnan(b)):
                out.append(f"{path}: {a!r} != {b!r}")
        elif abs(a - b) > tol * max(1.0, abs(a), abs(b)):
            out.append(f"{path}: {a!r} != {b!r}")
        return out
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual), key=str):
            if key not in expected:
                out.append(f"{path}.{key}: unexpected key")
            elif key not in actual:
                out.append(f"{path}.{key}: missing")
            else:
                out.extend(differences(expected[key], actual[key], f"{path}.{key}", tol))
        return out
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return [f"{path}: length {len(expected)} != {len(actual)}"]
        for i, (e, a) in enumerate(zip(expected, actual)):
            out.extend(differences(e, a, f"{path}[{i}]", tol))
        return out
    if expected != actual:
        out.append(f"{path}: {expected!r} != {actual!r}")
    return out


def plain(value: Any) -> Any:
    """A value as JSON would carry it (tuples to lists, numpy scalars to floats)."""
    return json.loads(json.dumps(value, ensure_ascii=False))
