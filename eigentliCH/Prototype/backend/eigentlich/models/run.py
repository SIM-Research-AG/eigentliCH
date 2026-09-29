"""EngineRun — R-301's queue, as one table.

**Why a table and a thread, and not a broker.** R-301 says "queue and poll", and the shape of a queue is
decided by what has to survive. This is a local single-user application: one process, one SQLite file, one
person at a keyboard, started by a desktop icon (A47). A broker would add a service to install, a port to
bind and a second place where a run's status lives — and the second place is the part that matters, because
two stores of one fact drift, and this estate has already paid for that twice (A63's triggers, A40's
`curator_id`). So the run *is* the row. `status` on this table is the only answer to "what happened", the
HTTP poll reads it, and the worker thread writes it. Nothing is held in memory that a restart could lose
silently: a run interrupted by a restart is visible as a `running` row with no `finished_at`, and
`services/runs.py` resolves it on the next start rather than leaving it to look pending forever.

**Not `PlanMutable`, deliberately.** A run is a record of a computation, not a change to the member's plan,
so C-09 does not ask for a Decision when one is written. C-09 *does* apply the moment a run's result is
written INTO the plan, and the guard in `db.py` covers that from the other side: a worker thread has never
been through `before_flush`, so `_refuse_unvetted_plan_dml` refuses a raw plan write from it. Nothing here
writes to `positions` or `goals`, and `tests/test_runs.py` plants a worker that tries to.

**K2, and no field raised above it.** The payload can carry the member's plan — that is K2, the same class
as the `Position` and `Goal` rows it was built from. It is deliberately NOT marked K3: `data_class`
overrides feed `top_class_field_names()`, which the C-04 filter drops **by field name across the whole
application**, so marking `payload` here would redact the word `payload=` out of every log line the server
ever writes. C-04's own note in `base.py` explains why a filter that broad is an unused one. What keeps the
payload out of the logs is that `services/runs.py` logs ids and status and nothing else.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped

#: The four states a run can be in. Named once so the service, the API and the tests cannot drift apart —
#: the same reasoning as `FIVE_PARAMETERS` in `services/goals.py`.
SUBMITTED = "submitted"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

RUN_STATUSES = (SUBMITTED, RUNNING, DONE, FAILED)

#: The two a poll can stop on. A caller polls until the status is one of these; there is no fifth state and
#: no "unknown", because a run that cannot be accounted for is a defect rather than a status.
TERMINAL_STATUSES = (DONE, FAILED)


class EngineRun(Base, Classified, Timestamped):
    """One queued engine call: what was asked, what came back, and when.

    `created_at` (from `Timestamped`) is the submission time. There is no separate `submitted_at`: a run is
    created by being submitted, and a second column holding the same instant is one more thing that can
    disagree with itself.
    """

    __tablename__ = "engine_runs"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)

    #: The member this run belongs to — who asked for it — nullable because `tools/` submits runs at a
    #: terminal on nobody's behalf. Note this is the OWNER of the run and not a claim about the payload:
    #: `market_signal` reads no member data at all (see `services/engine_inputs.py`), and a run of it
    #: still belongs to whoever pressed the button, so that they and only they can poll it.
    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("members.id"), nullable=True, index=True
    )

    engine: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        index=True,
        doc="R-300. The manifest name. Validated against `engines.known_engines()` by the service, not "
        "by a CHECK constraint: the manifests are the authority on what an engine is and a copy of that "
        "list in the schema would be a second one.",
    )

    status: Mapped[str] = mapped_column(
        SAEnum(*RUN_STATUSES, name="run_status"),
        nullable=False,
        default=SUBMITTED,
        index=True,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="C-04. What was sent to the engine, exactly as `services/engine_inputs.py` built it. Stored so "
        "a run is reproducible; never logged, because an engine payload can carry the member's plan.",
    )

    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        doc="C-03 / R-304. The engine's reading, already stripped of every published-artefact key before "
        "it was written here. Stripped on the way IN rather than on the way out, so the export (R-154) "
        "and any future reader of this table are covered by the same one pass.",
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="R-302. Why a failed run produced nothing. The reason only — never `EngineNotAvailable.detail`, "
        "which carries the estate's stderr and can quote the payload it was given back at us (C-04).",
    )

    timeout_s: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="R-301. The budget this run was given, from the manifest. Recorded because 'it timed out' and "
        "'it timed out at 30 seconds' are different findings.",
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES


__all__ = [
    "DONE",
    "EngineRun",
    "FAILED",
    "RUNNING",
    "RUN_STATUSES",
    "SUBMITTED",
    "TERMINAL_STATUSES",
]
