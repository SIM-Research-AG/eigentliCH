"""Content-hash ids (spec section 3): ``<PREFIX>-<16 hex>`` over the canonical JSON of a payload."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def content_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()[:16]}"


def sha256(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
