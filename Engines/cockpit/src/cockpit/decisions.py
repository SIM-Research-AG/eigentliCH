"""The CIO's decision log: optimiser boundary conditions and instrument shortlists.

HoNI has no automated consumer; the CIO reads it and decides. Until the optimiser (``pcp``)
publishes the contract it will take these in, the decisions are kept here, append-only, one
JSON object per line, each stamped with the artefacts it was based on so it can always be
read against the numbers the CIO saw (DECISIONS.md C-06). Nothing is ever edited or deleted:
a changed decision is a new record.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["optimiser_bounds", "instrument_selection"]


class BoundRow(BaseModel):
    """Weight bounds for one country, in percent of the portfolio. Blank means unbounded."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str = Field(min_length=2, max_length=8)
    name: str = ""
    min_pct: Optional[float] = Field(default=None, ge=0, le=100)
    max_pct: Optional[float] = Field(default=None, ge=0, le=100)
    note: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> "BoundRow":
        if self.min_pct is not None and self.max_pct is not None and self.min_pct > self.max_pct:
            raise ValueError(f"{self.code}: minimum above maximum")
        return self


class SelectionRow(BaseModel):
    """One instrument on the shortlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: str = Field(min_length=1)
    name: str = ""
    role: str = ""
    decision: Literal["include", "watch", "exclude"] = "include"
    note: str = ""


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Kind
    title: str = Field(min_length=1, max_length=200)
    author: str = ""
    note: str = ""
    #: The artefacts the decision was read off, e.g. {"honi": "HNS-...", "snapshot": "..."}.
    basis: dict[str, str] = Field(default_factory=dict)
    rows: list[dict[str, Any]]

    @model_validator(mode="after")
    def _rows(self) -> "DecisionIn":
        model = BoundRow if self.kind == "optimiser_bounds" else SelectionRow
        for row in self.rows:
            model.model_validate(row)
        if not self.rows:
            raise ValueError("a decision needs at least one row")
        return self


class Decision(DecisionIn):
    decision_id: str
    saved_at: str


class DecisionLog:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "decisions.jsonl"
        self._lock = threading.Lock()

    def _read(self) -> list[Decision]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(Decision.model_validate_json(line))
        return out

    def list(self, kind: Optional[str] = None) -> list[Decision]:
        with self._lock:
            rows = self._read()
        return [d for d in reversed(rows) if kind is None or d.kind == kind]

    def get(self, decision_id: str) -> Optional[Decision]:
        return next((d for d in self.list() if d.decision_id == decision_id), None)

    def latest(self, kind: str) -> Optional[Decision]:
        found = self.list(kind)
        return found[0] if found else None

    def append(self, decision: DecisionIn) -> Decision:
        saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = decision.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps({**payload, "saved_at": saved_at}, sort_keys=True)
                                .encode()).hexdigest()[:16]
        record = Decision(**payload, decision_id=f"DEC-{digest}", saved_at=saved_at)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(record.model_dump_json() + "\n")
        return record
