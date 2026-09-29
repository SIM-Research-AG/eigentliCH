"""Typed contracts: ReturnSet build, validate, serialise."""

from fmre.contracts.returnset import (
    CANONICAL_ROLES,
    DEFAULT_HOUSE_VIEW,
    ReturnSet,
    ReturnSetValidationError,
    build_returnset,
    house_view_from_regime,
    load_returnset,
    superpose_block_expectations,
    superpose_role_expectations,
    to_canonical_json,
    validate_returnset,
    write_returnset,
)

__all__ = [
    "CANONICAL_ROLES",
    "DEFAULT_HOUSE_VIEW",
    "ReturnSet",
    "ReturnSetValidationError",
    "build_returnset",
    "house_view_from_regime",
    "load_returnset",
    "superpose_block_expectations",
    "superpose_role_expectations",
    "to_canonical_json",
    "validate_returnset",
    "write_returnset",
]
