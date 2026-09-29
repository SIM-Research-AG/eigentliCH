"""Read a client mandate from YAML.

The mandate is the per-user input and sits on the user side of the regulated wall: a target return curve
and the allocation constraints. The Regime and the ReturnSet are population-level; this is the only
input that is specific to a client.

The legacy positional read of `Controller_Test.xlsx` is not a runtime path (decisions.md D1). The
workbook is read exactly once, read-only, by `tools/seed_mandates.py`, which writes YAML. Thereafter the
mandate is YAML, so a bound is named rather than inferred from a cell offset, and the Capital Type header
ambiguity of the workbook cannot recur.

Bounds are declared per named category. A category the mandate does not mention is unconstrained, which
is the only sane default: the alternative, treating silence as zero, would forbid every asset class the
mandate had not thought to mention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import yaml

from pcp.config import Config
from pcp.contracts import STATE_GRID, Bound, Mandate, MandateError

#: The constraint dimensions a mandate may bound, and the vocabulary each is checked against.
BOUND_DIMENSIONS: tuple[str, ...] = (
    "currency",
    "region",
    "role",
    "capital_type",
    "liquidity",
    "phase",
    "asset_class",
)


class MandateNotFound(MandateError):
    """Raised when no mandate file matches the requested identity."""


def list_mandates(directory: Path | str | None = None, config: Config | None = None) -> list[dict[str, Any]]:
    """Every configured mandate, as identity summaries.

    Reads only the header of each file, so a malformed target curve elsewhere in the directory does not
    stop the list. A file that cannot be parsed at all is reported with its error rather than skipped
    silently.
    """
    root = _resolve_directory(directory, config)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            rows.append(
                {
                    "client": payload.get("client"),
                    "mandate": payload.get("mandate"),
                    "market": payload.get("market"),
                    "currency": payload.get("currency"),
                    "benchmark": payload.get("benchmark"),
                    "universe_size": len(payload.get("universe", []) or []),
                    "path": str(path),
                    "ok": True,
                }
            )
        except yaml.YAMLError as error:
            rows.append({"path": str(path), "ok": False, "error": str(error)})
    return rows


def load_mandate(
    name: str,
    directory: Path | str | None = None,
    config: Config | None = None,
) -> Mandate:
    """Load one mandate by file stem, by mandate name, or by `client/mandate`.

    Raises:
        MandateNotFound: If nothing matches, with the available identities listed.
        MandateError: If the file is malformed.
    """
    root = _resolve_directory(directory, config)
    candidates = sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))
    if not candidates:
        raise MandateNotFound(
            f"no mandate files in {root}. Seed them from the legacy workbook with "
            f"'python -m tools.seed_mandates', or author one by hand."
        )

    wanted = name.strip()
    matches = [p for p in candidates if p.stem == wanted]
    if not matches:
        matches = [p for p in candidates if _identity_of(p) in {wanted, wanted.replace("\\", "/")}]
    if not matches:
        matches = [p for p in candidates if _mandate_name_of(p) == wanted]
    if not matches:
        available = ", ".join(sorted(_identity_of(p) for p in candidates))
        raise MandateNotFound(
            f"no mandate matches {name!r}. Available: {available}."
        )
    if len(matches) > 1:
        found = ", ".join(str(p) for p in matches)
        raise MandateError(
            f"{name!r} matches more than one mandate ({found}). Name it as 'client/mandate'."
        )
    return mandate_from_file(matches[0], config)


def mandate_from_file(path: Path | str, config: Config | None = None) -> Mandate:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise MandateError(f"mandate {source} is not valid YAML: {error}") from error
    if not isinstance(payload, Mapping):
        raise MandateError(f"mandate {source} must be a mapping at the top level")
    return mandate_from_payload(payload, config, source=source)


def mandate_from_payload(
    payload: Mapping[str, Any],
    config: Config | None = None,
    source: Path | str | None = None,
) -> Mandate:
    where = f" in {source}" if source else ""
    required = (
        "client", "mandate", "market", "currency", "benchmark",
        "max_single_position", "esg_min", "target_curve", "universe",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise MandateError(f"mandate is missing field(s) {missing}{where}")

    curve = [float(v) for v in payload["target_curve"]]
    if len(curve) != STATE_GRID:
        raise MandateError(
            f"mandate{where} target_curve has {len(curve)} points, expected {STATE_GRID}. The curve is "
            f"the objective the allocation is fitted to, one point per regime state."
        )

    universe = [int(v) for v in payload["universe"]]
    if not universe:
        raise MandateError(f"mandate{where} has an empty universe")

    fixed_raw = payload.get("fixed_allocations") or {}
    if not isinstance(fixed_raw, Mapping):
        raise MandateError(f"mandate{where} fixed_allocations must be a mapping of bb_id to weight")
    fixed = {int(k): float(v) for k, v in fixed_raw.items()}

    bounds = _bounds_from_payload(payload.get("bounds") or {}, config, where)

    return Mandate(
        client=str(payload["client"]),
        name=str(payload["mandate"]),
        market=str(payload["market"]),
        currency=str(payload["currency"]),
        benchmark=str(payload["benchmark"]),
        max_single_position=float(payload["max_single_position"]),
        esg_min=float(payload["esg_min"]),
        horizon_years=float(payload.get("horizon_years", 1.0)),
        target_curve=np.asarray(curve, dtype=float),
        universe=tuple(universe),
        fixed_allocations=fixed,
        bounds=bounds,
    )


def _bounds_from_payload(
    raw: Mapping[str, Any],
    config: Config | None,
    where: str,
) -> dict[str, dict[str, Bound]]:
    unknown = [key for key in raw if key not in BOUND_DIMENSIONS]
    if unknown:
        raise MandateError(
            f"mandate{where} bounds names unknown dimension(s) {unknown}. Known: "
            f"{list(BOUND_DIMENSIONS)}."
        )

    bounds: dict[str, dict[str, Bound]] = {}
    for dimension in BOUND_DIMENSIONS:
        declared = raw.get(dimension) or {}
        if not isinstance(declared, Mapping):
            raise MandateError(
                f"mandate{where} bounds.{dimension} must be a mapping of category to bound"
            )
        per_category: dict[str, Bound] = {}
        for category, spec in declared.items():
            per_category[str(category)] = _bound_from_spec(spec, dimension, str(category), where)
        bounds[dimension] = per_category

    if config is not None:
        _check_against_vocabularies(bounds, config, where)
    return bounds


def _bound_from_spec(spec: Any, dimension: str, category: str, where: str) -> Bound:
    """Read one bound.

    Accepts `{lower: a, upper: b}` or the two-element `[a, b]`. The mapping form is preferred and is what
    the seeding tool writes, because a pair says nothing about which end is which, and that ambiguity is
    exactly what made the legacy workbook's Capital Type block unreadable.
    """
    if isinstance(spec, Mapping):
        unknown = set(spec) - {"lower", "upper"}
        if unknown:
            raise MandateError(
                f"mandate{where} bounds.{dimension}.{category} has unknown key(s) {sorted(unknown)}; "
                f"expected 'lower' and 'upper'"
            )
        lower = float(spec.get("lower", 0.0))
        upper = float(spec.get("upper", 1.0))
    elif isinstance(spec, (list, tuple)):
        if len(spec) != 2:
            raise MandateError(
                f"mandate{where} bounds.{dimension}.{category} as a list must have exactly two entries "
                f"[lower, upper], got {len(spec)}"
            )
        lower, upper = float(spec[0]), float(spec[1])
    else:
        raise MandateError(
            f"mandate{where} bounds.{dimension}.{category} must be a mapping with lower and upper, or a "
            f"two-element list, got {type(spec).__name__}"
        )

    try:
        return Bound(lower=lower, upper=upper)
    except MandateError as error:
        raise MandateError(f"mandate{where} bounds.{dimension}.{category}: {error}") from error


def _check_against_vocabularies(
    bounds: Mapping[str, Mapping[str, Bound]],
    config: Config,
    where: str,
) -> None:
    """Refuse a bound on a category that does not exist.

    A typo in a category name would otherwise create a bound that constrains nothing, and the run would
    report itself as having satisfied a limit it never applied.
    """
    vocabularies = config.vocabularies
    by_dimension = {
        "currency": vocabularies.currencies,
        "region": vocabularies.regions,
        "role": vocabularies.roles,
        "capital_type": vocabularies.capital_types,
        "liquidity": vocabularies.liquidity,
        "phase": vocabularies.phases,
        "asset_class": vocabularies.asset_classes,
    }
    problems: list[str] = []
    for dimension, categories in bounds.items():
        vocabulary = by_dimension[dimension]
        for category in categories:
            if not vocabulary.contains(category):
                problems.append(
                    f"bounds.{dimension}.{category!r} is not a known {vocabulary.name} "
                    f"(known: {list(vocabulary.labels)})"
                )
    if problems:
        raise MandateError(f"mandate{where} has bounds on unknown categories:\n  " + "\n  ".join(problems))


def _identity_of(path: Path) -> str:
    header = _header(path)
    client = header.get("client")
    mandate = header.get("mandate")
    if client and mandate:
        return f"{client}/{mandate}"
    return path.stem


def _mandate_name_of(path: Path) -> str | None:
    return _header(path).get("mandate")


def _header(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except yaml.YAMLError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_directory(directory: Path | str | None, config: Config | None) -> Path:
    if directory is not None:
        return Path(directory)
    configured = "mandates"
    if config is not None:
        configured = str(config.get("paths.mandates_dir"))
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    return (Path(__file__).resolve().parent.parent.parent / candidate).resolve()
