"""The FastAPI application.

**What is here at phase 1 is deliberately almost nothing.** The spine is the data model, the constraints and
the migrations; §6's endpoints arrive with the phases that give them something to return. What exists is a
status surface, so the desktop icon opens onto a truthful account of what is built rather than onto a
404 or a stub that implies more than exists.

`/api/health` reports the migration revision and the constraint checks by name. That is the phase gate made
visible: build-spec §10 gates phase 1 on C-04, C-06, C-07 and C-09, and this is where someone can see
whether they hold without running pytest. **C-06 is no longer among them** — it was dropped with the
compliance layer on 20 September 2026 (A168), so one of the four gates §10 names has been withdrawn
rather than satisfied, and the board says so by not listing it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_member
from .. import __version__
from .. import interpret as interpretation
from .. import llm
from ..content import (
    ContentMissing,
    DEFAULT_LANGUAGE,
    LANGUAGES,
    destination as destination_phrase,
    onboarding_questions,
)
from ..db import make_engine, make_session_factory
from ..log_filter import install as install_log_filter
from ..models import (
    CAPITAL_TYPES,
    Goal,
    LIQUIDITY,
    MAGNITUDE_UNITS,
    Member,
    Position,
    ROLES,
    STOCK_KINDS,
    VaultItem,
)
from ..services import (
    OnboardingAlreadyComplete,
    OnboardingIncomplete,
    UnknownQuestion,
    answers as onboarding_answers,
    complete as onboarding_complete,
    IntakeNotImplemented,
    VaultStore,
    current_items,
    export_member,
    list_goals,
    mutate_plan,
    action_items,
    ask,
    open_curator_session,
    store_item,
    verify_round_trip,
    resume_point as onboarding_resume_point,
    record_answer,
    role_grid,
    validate_position_state,
)
from ..services.derive import causes_by_item_id, derive_action_items
from ..services.goals import GOAL_TEMPLATES, UnknownOccupancy, check_occupancy
from ..services.feed import read as read_feed
from ..services.regime import read as read_regime
# R-301's worker, reached through the service layer. `api/` may not import the engine façade at all
# (C-03's strong form, held by tests/test_constraints.py), so the shutdown hook reaches it through
# `services.runs` the same way `services/engine_inputs.py` reaches the manifests.
from ..services.runs import stop_worker as stop_run_worker
from ..services.directory import NoSuchCurator, resolve_curator
from ..services.vault import DEFERRED_INTAKE, IMPLEMENTED_INTAKE

BACKEND = Path(__file__).resolve().parent.parent.parent
#: prototype2/ — the client lives beside `backend/`, not inside it.
PROJECT = BACKEND.parent

#: C-04. Installed at import AND again once the server has finished configuring its own logging.
#:
#: **Both, because the import-time call alone was inert.** uvicorn configures logging and then imports the
#: application, so the import-time call does see its handlers — but only when the app is loaded by
#: uvicorn's own machinery, and `--reload`, an embedded runner or a test harness can invert that order.
#: `install()` is idempotent and attaches one shared filter instance, so calling it twice costs a set
#: membership test per handler and removes an ordering assumption from a constraint that is not allowed
#: to depend on one. See the long note in `log_filter.py` for what the installation has to do to be
#: effective at all.
install_log_filter()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    install_log_filter()
    try:
        yield
    finally:
        # R-301's worker, stopped on shutdown. It is not *started* here, deliberately: it binds to the
        # database the request came in on, in `services.runs.ensure_worker_for`. Starting it from this hook
        # would bind it to `_sessions` — the module global pointed at `backend/eigentlich.db` — and a test
        # that overrides the session *dependency* does not override that global, so every `TestClient(app)`
        # in the suite would start a thread polling the developer's real database and would execute a run
        # it found there. A68 records what "every test run touched the real database" cost this build once.
        # The full reasoning, and what binding late costs, is in `services/runs.ensure_worker_for`.
        stop_run_worker()


app = FastAPI(
    # The product is eigentliCH since 20 September 2026. Only the display name has moved — the package is
    # still `eigentlich`, the local addresses are still `@eigentli.local`, and the build specification is
    # still the file it is named after. The rename of the identifiers is its own pass
    # (`TASK-rename-eigentlich-2026-09-20.md`) and deliberately has not happened yet.
    title="eigentliCH",
    version=__version__,
    description="Member application. Built against andersCH-build-spec.html v1.0.",
    lifespan=_lifespan,
)

_engine = make_engine()
_sessions = make_session_factory(_engine)


def get_session() -> Session:
    with _sessions() as session:
        yield session


# ---------------------------------------------------------------- status


@app.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict:
    revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    tables = [
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
    ]
    triggers = [
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
        )
    ]
    return {
        "version": __version__,
        "phase": 8,
        "phase_name": "All eight phases built",
        "migration_revision": revision,
        "tables": tables,
        "append_only_triggers": triggers,
        "constraints_enforced": {
            "C-02": "an AssumptionSet is published and versioned; no literal rate in application code",
            "C-04": "data_class column on every model; logging filter drops top-class fields by "
                    "name, attached to every log handler including ones added after startup, and "
                    "scrubbing exception and stack text as well as the message",
            "C-07": "no gamification identifiers in the member model layer (scope: A6 in DECISIONS.md)",
            "C-09": "plan mutation without a linked Decision raises in before_flush for ORM writes "
                    "and in before_execute for Core DML, bulk_save_objects and raw SQL",
            "C-10": "curator_session_events rejects UPDATE and DELETE by trigger, and "
                    "curator_sessions.curator_id is a foreign key into curators — the identified curator "
                    "is a row, not a string a caller chose (A98; it was a plain String(120) until "
                    "31 August 2026)",
            "R-040": "decisions are append-only; a correction is a new record",
            "R-100": "age floor enforced in the service and as a CHECK constraint",
            "C-05": "the authenticated bundle is scanned for cross-origin references; system fonts only",
            "R-110": "the role grid renders at n=1; empty cells state what would go there",
            "R-113": "the grid payload carries no filled count, total or ratio",
            "C-11": "no member-facing sentence asserts a fact it cannot attribute to a retrieved "
                    "passage. The Know emits only sentences copied verbatim from retrieved passages, "
                    "chosen by the model as NUMBERS rather than written by it, and unquoted_sentences "
                    "refuses any answer carrying a letter or digit outside the quotation marks. "
                    "Promoted from A106's extractive-only rule to a constraint on 20 September 2026 "
                    "(A164): with C-01 withdrawn this is the only protection left on that surface, and "
                    "A103's wrong-law failure is what it protects against",
            "R-041": "vault items are versioned; a new version is a new row",
            "R-152": "expiry dates are the primary source of action items and no longer the only one. "
                     "Four further sources are derived from the plan itself — an unfunded goal, a goal "
                     "whose target date passed with nothing decided since, a capital type with nothing "
                     "in it, a skipped onboarding answer — plus a fifth, quiet positions, which fires "
                     "only when a caller supplies the date, because a horizon is an assumption nobody "
                     "has published (C-02). Derived on the read of /api/actions, one item per cause "
                     "forever by unique index, and every option carries a consequence and recommends "
                     "neither branch. Two candidates were rejected rather than built: a concentration "
                     "warning across correlation tags (D-02 forbids it) and an item per empty grid cell "
                     "(seven of them is R-113's completion meter as a list)",
            "R-154": "the export walks services/member_data.py, the same registry the erasure "
                     "deletes from, so a table the application treats as the member's cannot be "
                     "in one and not the other; round-trip verified at /api/export/verify",
            "C-08": "ranking is handed three integers and an opaque id; it cannot reach a fee. "
                    "All three are now derived from the database rather than two being constant, "
                    "and role_match is a SHARE of declared roles, so declaring more can only "
                    "lower it — breadth of declaration can tie but never beat real evidence",
            "R-183": "the seven life-event modules are empty because their content is authored",
            "R-210": "every curator read consults a live, scoped grant or raises",
            "R-231": "erasure nulls the member from records that cannot be deleted",
            "C-03": "engines run server-side in their own interpreter; no engine artefact is served. "
                    "The api package does not import the engine facade, and every runtime payload "
                    "carrying engine output is checked by services/served.py before it is stored or "
                    "returned",
            "R-301": "no engine runs on a request thread. POST /api/runs writes a row and returns 202; "
                     "one worker thread executes runs off the request path and the row is the only "
                     "record of a run's status. A run interrupted by a restart is resolved on the next "
                     "start rather than left looking pending",
            "R-302": "a failed run carries no numeric field at any depth — not a duration, not the "
                     "timeout it was given, not a zero",
            "R-133": "every goal carries an illustration stamped with the assumption_set_id it used, or "
                     "a derived reason there is none. no_assumption_set_published is returned only when "
                     "the table is empty",
            "A11": "every member route resolves its member from a bearer session token. member_id is "
                   "not accepted from any caller — the parameter is gone from the routes and from the "
                   "request models rather than being checked — and the routes that deliberately need "
                   "no session are listed, with the reason for each, in api/auth.py. No developer "
                   "bypass: no environment variable, no header, no localhost exemption",
            "A43": "must_change is enforced by the server. A session whose credential is marked can "
                   "reach GET/DELETE /api/session and POST /api/password and nothing else, so a "
                   "documented demonstration password is good for exactly one login",
        },
        "not_yet_built": {},
        # A65: this board is read as a statement of fact, so what is known NOT to hold belongs on it too.
        # Each of these has an executable `xfail(strict=True)` in tests/test_adversarial.py, which means
        # the suite fails if one is quietly closed without someone recording why.
        #
        # **Every row carries `since` and `owner` since 20 September 2026 (A171).** An open item with no
        # date is one nobody can tell has been open for three weeks or three months, and an open item
        # with no owner is one nobody has agreed to answer. `client/status.html` renders these rows
        # directly rather than keeping its own copy, so the board and this dict cannot disagree — the
        # five wrong rows T3.3 found on the old page were all the same defect, a second copy going stale.
        "known_gaps": {
            "S-08/relevance": {
                "since": "2026-09-01",
                "owner": "Nicolas",
                "what": "The Know can return a true, correctly cited sentence that answers an adjacent "
                        "question. The original risk was TRUTH - the Know stating Swiss pension law "
                        "wrongly in its own words while citing correct passages, which reproduced in 3 "
                        "of 3 runs against apertus:8b (A103). That is closed by construction rather "
                        "than by detection: C-11 means the Know emits only sentences copied verbatim "
                        "from retrieved passages, so a sentence in no passage cannot be produced. What "
                        "remains is relevance, and it is visible to the member, because the citation "
                        "names the source of the quote. Until 20 September 2026 this entry also "
                        "recorded that C-01 could not tell a misapplied figure from a correct one; "
                        "C-01 has been withdrawn (A164), so the residual risk no longer has a second "
                        "name",
            },
            "C-09/raw-dbapi": {
                "since": "2026-08-31",
                "owner": "Nicolas",
                "what": "C-09 holds for everything that goes through SQLAlchemy - the ORM flush guard "
                        "and the Core DML guard between them cover the session, bulk writes and raw "
                        "SQL on the connection. A raw DBAPI cursor from engine.raw_connection(), or "
                        "sqlite3 opened on the database file, bypasses both entirely",
            },
            "curator/no-release-gate": {
                "since": "2026-09-20",
                "owner": "Nicolas",
                "what": "Nothing holds the claim that a curator read a report before a member saw it. "
                        "C-01 was withdrawn and the release gate proposed to replace it (C-12) was "
                        "refused, so no report, finding or allocation carries a release record and "
                        "no code path requires one. The curator is advisory. This is a stated "
                        "position rather than an oversight - A160 has the ruling and what it costs - "
                        "and it is on this board because a reader asking what stops unreviewed output "
                        "reaching a member is entitled to find the answer rather than an absence",
            },
        },
    }


# ---------------------------------------------------------------- registration and the session
#
# Both live in `api/auth.py` now — `POST /api/members`, `POST /api/session`, `GET /api/session`,
# `DELETE /api/session` and `POST /api/password`. A11 was chosen in phase 0 and the service layer was
# written in phase 2; until 31 August 2026 nothing HTTP-facing called it, and every route below took
# `member_id` from the caller and believed it. `current_member` is the dependency that replaced that,
# and `api/auth.py`'s docstring carries the list of routes that are deliberately open.

# ---------------------------------------------------------------- onboarding (S-01)


def _question_options(record: dict, language: str) -> list[dict] | None:
    """One question's options, or None for a question that has none.

    Falls back to the authored language (A12: German is authored, the rest are translations) rather than
    to the raw value, because an option rendered as its own code is a control a member cannot read.
    """
    options = record.get("options")
    if not options:
        return None
    return [
        {
            "value": one["value"],
            "label": one["label"].get(language) or one["label"][DEFAULT_LANGUAGE],
        }
        for one in options
    ]


@app.get("/api/onboarding")
def get_onboarding(
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-01. The question set, the answers so far, and where to resume.

    R-101's acceptance test is that a member who abandons at question *n* resumes at *n*, so the payload
    names the next unanswered question rather than a count. A count is a completion meter one component
    away from existing (R-113).

    **The goal question carries its choices with it.** A question whose `type` is `goal_template` is asking
    which of `GOAL_TEMPLATES` the member is working toward, so the templates travel in the same payload
    rather than costing the client a second request it could forget to make. Before 31 August 2026 the
    question took free text and `complete` stored the sentence as the goal's *name* with no template at
    all, so a member who typed "Frühpensionierung" got a goal eigentliCH could not recognise — which is the
    owner's own report, and the reason the type exists.

    **`options`, `min` and `max` travel too, and `min`/`max` are a repair.** A `choice` question is
    unrenderable without its options, so the A127 keys need them here or the whole mechanism stops at the
    server. The bounds are the same shape and were simply missing: `client/surfaces/onboarding.js` has
    always read `question.min` and `question.max` and set them on the input, and this payload has never
    carried either — so `employment_magnitude`, which declares 0 to 5,000,000, has been rendering as an
    unbounded number field since the day it was written. A content file declaring a bound that nothing
    reads is the same defect class as a guard that cannot fail.
    """
    state = onboarding_resume_point(session, member_id=member.id)
    given = onboarding_answers(session, member_id=member.id)

    questions = []
    for record in sorted(onboarding_questions(), key=lambda q: q["order"]):
        questions.append(
            {
                "key": record["key"],
                "order": record["order"],
                "required": record["required"],
                "type": record["type"],
                "unit": record.get("unit"),
                "question": record["question"].get(language),
                "why": record["why"].get(language),
                "answer": given.get(record["key"]),
                # Present on every question, null on all but the goal one, so a client reads a field
                # rather than inferring from a `type` string it has to match.
                "templates": (
                    list(GOAL_TEMPLATES.values()) if record["type"] == "goal_template" else None
                ),
                # The declared bounds, for the `number` questions. See the docstring: the client has
                # always read these and they have never been sent.
                "min": record.get("min"),
                "max": record.get("max"),
                # A `choice` question's own options, label resolved for this language. The VALUE is
                # untranslated on purpose — it is what gets stored, and a stored answer that changed
                # with the reader's language would be a different answer.
                "options": _question_options(record, language),
            }
        )

    return {"member_id": member.id, "language": language, "questions": questions, **state}


class AnswerRequest(BaseModel):
    """**No `member_id`.** It used to be the first field, and it was the whole authorisation story: any
    caller could write an answer into anyone's onboarding by typing a different id. The member is the
    token's now, so there is nothing here to aim."""

    #: Deliberately permissive: a question may answer with a number, a string or a list, and the model
    #: layer stores it as JSON. Coercing all three to text is how "42" that meant hours loses its meaning.
    value: object = None


@app.put("/api/onboarding/answers/{question_key}")
def put_answer(
    question_key: str,
    body: AnswerRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-101. One question, one row, written now — not on navigate and not on submit."""
    try:
        answer = record_answer(
            session, member_id=member.id, question_key=question_key, value=body.value
        )
    except UnknownQuestion as unknown:
        raise HTTPException(422, str(unknown)) from unknown
    session.commit()
    return {"question_key": answer.question_key, "answered_at": answer.answered_at.isoformat()}


@app.post("/api/onboarding/complete", status_code=201)
def complete_onboarding(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """R-102. Writes one Position and the first Goal if stated, in one transaction with one Decision.

    Takes no body at all now. It only ever needed the member, and the member is the token's.
    """
    try:
        result = onboarding_complete(session, member_id=member.id)
    except OnboardingIncomplete as incomplete:
        raise HTTPException(422, str(incomplete)) from incomplete
    except OnboardingAlreadyComplete as done:
        # 409, not 422: the request is well formed and the member is not at fault. A double-submit is the
        # ordinary way this happens.
        raise HTTPException(409, str(done)) from done
    session.commit()
    return {
        "position_id": result["position"].id,
        "goal_id": result["goal"].id if "goal" in result else None,
        "decision_id": result["decision"].id,
    }


@app.post("/api/onboarding/interpret/{question_key}")
def interpret_answer(
    question_key: str, body: AnswerRequest, member: Member = Depends(current_member)
) -> dict:
    """Read a free-text answer with the LOCAL model and propose a structure for it.

    **Authenticated even though it stores nothing and reads no member row.** What it takes is a sentence
    the member typed, and what it does with it is spend the machine's local model. Neither belongs to
    whoever can reach the port. `member` is deliberately unused below: this route needs a session, not an
    identity, and inventing a use for the id would be the beginning of one.

    Deliberately does NOT write anything and does not take a session. A suggestion is not a fact: it is
    returned for the member to confirm, and R-151's rule — extraction never overwrites a member-entered
    value — is kept by this endpoint having no way to store one.

    Degrades rather than fails. No local model running means `interpreted: false` and a form that behaves
    exactly as it did before.
    """
    return interpretation.suggestions_for(question_key, body.value)


@app.get("/api/local-model")
def local_model_status() -> dict:
    """Whether the local model is reachable, for a client that wants to hide a feature it cannot offer."""
    return {
        "available": llm.available(),
        "model": llm.DEFAULT_MODEL,
        "url": llm.DEFAULT_BASE_URL,
        "note": "Loopback only. A non-local host raises rather than being configurable — C-05.",
    }


# ---------------------------------------------------------------- role grid (S-02, S-03)


@app.get("/api/positions")
def get_positions(
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-02. The role grid payload.

    Carries no filled-count, total or ratio — see `services/grid.py`. R-113 and R-006.

    **This route is the one that made the case for A11 being wired.** `GET /api/positions?member_id=<any
    id>` returned any member's entire financial and human capital position to an unauthenticated caller.
    The `member_id` parameter is gone; the grid is the token's member's, and there is no second way to
    ask for one.
    """
    return role_grid(session, member_id=member.id, language=language)


class PositionRequest(BaseModel):
    """S-03 / R-120. Role, capital type, label, magnitude with an explicit unit, and the five tags.

    No `member_id`: a position is written for the member holding the token.
    """

    role: str
    capital_type: str
    label: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    magnitude: float | None = None
    magnitude_unit: str | None = None
    #: The side of the balance sheet, for a magnitude in `chf`. **Required for one and refused for anything
    #: else** — see `Position.stock_kind`. It has no default here on purpose: a default would file every
    #: unmarked debt as an asset, and `models/plan.py` chose a field over a negative magnitude precisely so
    #: that a liability cannot be stored without being named one.
    stock_kind: str | None = None
    #: R-121. Human capital is bounded by hours; financial capital is not.
    time_basis: str | None = None
    tags: dict = Field(default_factory=dict)

    #: C-09. The decision is part of the request, not something the server invents on the member's behalf.
    question: str
    choice: str
    reasoning: str | None = None


@app.post("/api/positions", status_code=201)
def create_position(
    body: PositionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-123 / C-09. Creating a position writes a Decision in the same transaction.

    The guard in `db.py` would refuse this write without one. That is deliberate belt-and-braces: this
    endpoint is the convenient path, not the enforcement.
    """
    # ------------------------------------------------------------------------------------------------
    # ONE VALIDATOR, NOT TWO — 1 September 2026
    # ------------------------------------------------------------------------------------------------
    #
    # This route used to re-implement `services.plan.validate_position_state`: its own `role` check, its own
    # `capital_type` check, its own magnitude/unit pair check and **its own copy of the unit list**. Two
    # lists that have to agree, maintained separately, is a documented failure mode in this build, and
    # adding the stock unit is exactly the edit that would have hit it — a member could have been offered
    # `chf` on the create route and refused it on the edit route, or the reverse, with no test that could
    # see the difference because each half was tested against itself.
    #
    # So the create path now checks the state it is about to write with the same function the edit path
    # checks the state it is about to leave behind. The dict is the created position's full state; the two
    # fields `POST` cannot set (`liquidity`, `started_on`) are passed as None because that is what they will
    # be, not to satisfy the signature.
    try:
        validate_position_state(
            {
                "role": body.role,
                "capital_type": body.capital_type,
                "label": body.label,
                "description": body.description,
                "magnitude": body.magnitude,
                "magnitude_unit": body.magnitude_unit,
                "stock_kind": body.stock_kind,
                "time_basis": body.time_basis,
                "liquidity": None,
                "started_on": None,
                "tags": body.tags or {},
            }
        )
    except ValueError as bad:
        raise HTTPException(422, str(bad)) from bad

    with mutate_plan(
        session,
        member_id=member.id,
        question=body.question,
        choice=body.choice,
        reasoning=body.reasoning,
    ) as decision:
        position = Position(
            member_id=member.id,
            role=body.role,
            capital_type=body.capital_type,
            label=body.label,
            description=body.description,
            magnitude=body.magnitude,
            magnitude_unit=body.magnitude_unit,
            stock_kind=body.stock_kind,
            time_basis=body.time_basis,
            tags=body.tags or {},
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    return {"id": position.id, "decision_id": decision.id}


# Each phase was built as its own router so that four of them could be written in parallel without
# colliding in this file. Wired here, which is the one place that knows the whole surface exists.
from .auth import router as auth_router  # noqa: E402
from .befund import router as befund_router  # noqa: E402
from .curator import router as curator_router  # noqa: E402
from .curators import router as curators_router  # noqa: E402
from .decisions import router as decisions_router  # noqa: E402
from .erasure import router as erasure_router  # noqa: E402
from .learning import router as learning_router  # noqa: E402
from .marketplace import router as marketplace_router  # noqa: E402
from .positions import router as positions_router  # noqa: E402
from .remainder import router as remainder_router  # noqa: E402
from .runs import router as runs_router  # noqa: E402

for _router in (
    auth_router,
    befund_router,
    decisions_router,
    erasure_router,
    learning_router,
    marketplace_router,
    positions_router,
    curator_router,
    curators_router,
    remainder_router,
    runs_router,
):
    app.include_router(_router)


# ---------------------------------------------------------------- the know (S-08)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    language: str = DEFAULT_LANGUAGE


@app.post("/api/know/ask")
def know_ask(
    body: AskRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-08. The Know surface's one entry point.

    **This was C-01's enforcement point until 20 September 2026 (A164).** The specification is explicit
    that the constraint lived here and that the check must not be a prompt instruction alone; the owner
    has withdrawn the constraint, so `services.know.ask` no longer classifies the question before the
    model or scans the answer after it. §S-08's acceptance example — "Should I buy fund X with my
    10,000?", which the spec says is refused with a curator offered — is now answered like any other
    question. `tests/test_know.py` asserts that in its new form rather than deleting it, so the lapsed
    criterion is visible rather than merely absent.

    What still holds here is C-11: every sentence the member reads is copied verbatim from a retrieved
    passage, and `services.know.unquoted_sentences` refuses anything else.

    `requires_curator` stays on the response object, as §2 describes, and is now always False on this
    route. The handoff below is unreachable from the router and is kept for the one path that can still
    set the flag — A122's undecidable lever in `services/liquidity.py`, which routes a computation
    nobody can make to a human. That is a product decision, not a statement about licensing.
    """
    answer = ask(
        session, member_id=member.id, question=body.question, language=body.language
    )
    payload = answer.as_dict()
    if payload["requires_curator"]:
        # R-172. The route out is offered with the handoff, not left for the member to find.
        payload["curator_handoff"] = {
            "method": "POST",
            "href": "/api/curator/sessions",
            "opened_from": "know_panel",
        }
    return payload


@app.get("/api/actions")
def get_actions(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """R-174. Prepared options carry what the member is choosing between; there is no count here (R-003).

    **C-06 is gone (A168) and this route no longer promises what it used to.** It required at least two
    options, each with a label and a consequence, enforced by a validator, a CHECK and two triggers. The
    derivation below still writes two, and `tests/test_derive.py` asserts it does — but that is a
    property of `services/derive.py` rather than a claim about the store, and any other writer may now
    produce an item with an empty array.

    **The derivations run here, on the read.** R-152 makes expiry dates the primary source of action items
    and not the only one, and until `services/derive.py` existed they were the only one — so a member who
    had entered positions and goals and uploaded no dated document read an empty list forever. That is the
    same defect R-152 already had once, one layer up: a requirement satisfied on paper because nothing in
    the running application called the function.

    **Deriving on the read is what R-175 asks for, not a violation of it.** "No unsolicited proactive
    messages. An item appears in the list; it does not interrupt." Nothing is pushed, nothing is scheduled,
    and no notification is emitted; the list is computed because someone asked for the list.

    **A GET that writes, and why that is acceptable here.** The alternative is deriving on every plan
    mutation, which spreads the derivation across every write path and gets it wrong the first time one is
    added. The write is idempotent at the store — one item per cause by unique index — so the second
    reader of the same unchanged plan writes nothing. A genuine race between two concurrent first reads is
    caught by that index rather than by a check-then-insert, and the loser simply lists what the winner
    wrote: the rollback is the correct outcome, not a degraded one.

    `unrevised_before` is deliberately not supplied. It is the one derivation that needs a horizon, C-02
    makes a horizon an assumption nobody has published, and this route is not the place one gets invented
    — see `services/derive.py`.
    """
    try:
        derive_action_items(session, member_id=member.id)
        session.commit()
    except IntegrityError:
        # Another request derived the same causes between our read and our write. The rows exist; that is
        # the outcome we wanted. Rolled back so the session is usable for the read below.
        session.rollback()

    listed = action_items(session, member_id=member.id)
    causes = causes_by_item_id(session, member_id=member.id)
    for item in listed:
        # R-174: an item expandable to its options is not expandable to anything if it does not say WHICH
        # goal, position, column or question it is about. `know.action_items` owns its payload and does not
        # carry this column, so it is joined on here rather than that read path being taught about
        # derivations it does not own. Null for the expiry items, whose cause is `source_vault_item_id`.
        item["derived_from"] = causes.get(item["id"])
    return {"member_id": member.id, "items": listed}


class CuratorSessionRequest(BaseModel):
    curator_id: str
    #: R-173. Which screen the button was pressed on — recorded at the time or not at all.
    opened_from: str = Field(..., min_length=1, max_length=120)


@app.post("/api/curator/sessions", status_code=201)
def create_curator_session(
    body: CuratorSessionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-173 / C-10. Every session records the IDENTIFIED curator and the entry point.

    **"Identified" is resolved, not trusted.** This route used to take `curator_id` on the caller's word,
    and `CuratorSession.curator_id` was a plain string rather than a foreign key — so an invented curator
    would have been written into an append-only audit table whose entire purpose is being true, and
    nothing at any layer would have caught it. Found by the agent that built the directory.

    `resolve_curator` refuses an unknown id, an inactive curator, an empty string and "unassigned" for one
    reason — there is no such row — which needs no list of placeholder words to keep up to date.

    **The column is a foreign key as of 31 August 2026** (A98), and this route is not why. Closing the
    HTTP surface was A67's stopgap and it was always the weaker half: it holds for callers who arrive by
    HTTP. What the key adds is a refusal for every caller who does not — and `services/know.py`'s opener,
    two layers down, resolves as well, so the refusal exists at all three levels rather than at the one
    that happened to be reachable from a browser.
    """
    try:
        curator = resolve_curator(session, body.curator_id)
    except NoSuchCurator as unknown:
        raise HTTPException(422, str(unknown)) from unknown

    record = open_curator_session(
        session,
        member_id=member.id,
        # The resolved row's id, not the string that arrived.
        curator_id=curator.id,
        opened_from=body.opened_from,
    )
    session.commit()
    return {"id": record.id, "opened_from": record.opened_from, "curator_id": record.curator_id}


# ---------------------------------------------------------------- vault (S-06)

#: K3 bytes live beside the database, never inside it. Gitignored.
VAULT_STORE = VaultStore(BACKEND / "vault_store")


@app.get("/api/vault")
def get_vault(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """S-06. Current versions only; superseded rows stay reachable through their chain and the export."""
    items = current_items(session, member_id=member.id)
    return {
        "member_id": member.id,
        "items": [
            {
                "id": i.id,
                "kind": i.kind,
                "title": i.title,
                "source": i.source,
                "version": i.version,
                "supersedes_id": i.supersedes_id,
                "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
                "has_content": bool(i.content_hash),
                "extracted_fields": i.extracted_fields or {},
                "notes": i.notes,
            }
            for i in items
        ],
        # R-150: the interface is four paths. Two of them are not built, and the payload says which
        # rather than leaving a client to discover it by a failed request.
        "intake": {"implemented": list(IMPLEMENTED_INTAKE), "not_built": list(DEFERRED_INTAKE)},
    }


class VaultItemRequest(BaseModel):
    kind: str
    title: str = Field(..., min_length=1, max_length=300)
    source: str = "manual"
    #: base64. R-153: a note carries no bytes, and is not thereby a lesser item.
    content_base64: str | None = None
    expiry_date: str | None = None
    notes: str | None = None
    supersedes_id: str | None = None


@app.post("/api/vault", status_code=201)
def create_vault_item(
    body: VaultItemRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-150 and R-041. A new version is a new row; nothing is overwritten in place."""
    import base64 as _b64
    from datetime import date as _date

    data = None
    if body.content_base64:
        try:
            data = _b64.b64decode(body.content_base64, validate=True)
        except Exception as bad:
            raise HTTPException(422, f"content_base64 is not valid base64: {bad}") from bad

    expiry = None
    if body.expiry_date:
        try:
            expiry = _date.fromisoformat(body.expiry_date)
        except ValueError as bad:
            raise HTTPException(422, f"expiry_date must be ISO-8601: {bad}") from bad

    supersedes = None
    if body.supersedes_id:
        supersedes = session.get(VaultItem, body.supersedes_id)
        if supersedes is None or supersedes.member_id != member.id:
            raise HTTPException(422, f"no vault item {body.supersedes_id!r} for this member")

    try:
        item = store_item(
            session,
            VAULT_STORE,
            member_id=member.id,
            kind=body.kind,
            title=body.title,
            source=body.source,
            data=data,
            expiry_date=expiry,
            notes=body.notes,
            supersedes=supersedes,
        )
    except IntakeNotImplemented as unbuilt:
        # 501, not 422: the member did nothing wrong. The path is undecided (D-04) and not built.
        raise HTTPException(501, str(unbuilt)) from unbuilt
    except ValueError as bad:
        raise HTTPException(422, str(bad)) from bad
    session.commit()
    return {"id": item.id, "version": item.version, "content_hash": item.content_hash}


@app.get("/api/export")
def full_export(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """R-154. Everything the member owns, without asking anyone.

    No approval parameter, no curator in the path, no support ticket. The response IS the export.
    """
    try:
        return export_member(session, VAULT_STORE, member_id=member.id)
    except LookupError as missing:
        raise HTTPException(404, str(missing)) from missing


@app.get("/api/export/verify")
def export_verify(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """Phase 3's gate, exposed: serialise, parse back, compare, and verify every vault hash."""
    return verify_round_trip(session, VAULT_STORE, member_id=member.id)


# ---------------------------------------------------------------- containers (S-04)


@app.get("/api/goals")
def get_goals(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """S-04. Goals with their five parameters, their funding, and R-031's statements of fact.

    Carries no total, no funded percentage and no "on track" — R-113. A '72% funded' is the completion
    meter this product exists without.
    """
    return list_goals(session, member_id=member.id)


class GoalRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    template: str | None = None
    target_amount: float | None = None
    target_date: str | None = None
    #: A129. For a property goal: whether the member will live in it. Null on every other goal and on a
    #: property goal nobody has asked yet — `services/property.py` then reports that it could not be
    #: determined rather than assuming the favourable case.
    occupancy: str | None = None
    safety: str | None = None
    liquidity_need: str | None = None
    volatility_tolerance: str | None = None
    horizon: str | None = None
    flexibility: str | None = None
    #: R-030. Overlapping funding is the normal case, not a data error.
    funded_by_position_ids: list[str] = Field(default_factory=list)

    question: str
    choice: str
    reasoning: str | None = None


@app.post("/api/goals", status_code=201)
def create_goal(
    body: GoalRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """C-09: the goal and its Decision are one transaction."""
    from datetime import date as _date

    if body.template and body.template not in GOAL_TEMPLATES:
        raise HTTPException(422, f"unknown template; expected one of {sorted(GOAL_TEMPLATES)}")

    try:
        occupancy = check_occupancy(body.occupancy)
    except UnknownOccupancy as bad:
        raise HTTPException(422, str(bad)) from bad

    target_date = None
    if body.target_date:
        try:
            target_date = _date.fromisoformat(body.target_date)
        except ValueError as bad:
            raise HTTPException(422, f"target_date must be ISO-8601: {bad}") from bad

    positions = []
    for position_id in body.funded_by_position_ids:
        position = session.get(Position, position_id)
        if position is None or position.member_id != member.id:
            raise HTTPException(422, f"no position {position_id!r} for this member")
        positions.append(position)

    with mutate_plan(
        session,
        member_id=member.id,
        question=body.question,
        choice=body.choice,
        reasoning=body.reasoning,
    ) as decision:
        goal = Goal(
            member_id=member.id,
            name=body.name,
            template=body.template,
            target_amount=body.target_amount,
            target_date=target_date,
            occupancy=occupancy,
            safety=body.safety,
            liquidity_need=body.liquidity_need,
            volatility_tolerance=body.volatility_tolerance,
            horizon=body.horizon,
            flexibility=body.flexibility,
        )
        goal.funded_by.extend(positions)
        session.add(goal)
        decision.linked_goals.append(goal)
        decision.linked_positions.extend(positions)
    session.commit()

    return {"id": goal.id, "decision_id": decision.id}


class GoalRevisionRequest(BaseModel):
    """A change to a goal that already exists.

    **Every field is optional and `None` is a value, not an absence.** `model_fields_set` is what separates
    "clear the target date" from "do not touch the target date" — a shape where the two are the same thing
    would silently wipe whatever the member did not retype, which is the defect this route exists to fix
    wearing a different coat.

    No `member_id`, and no `id`: the goal is addressed in the path and the member is the token's.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    template: str | None = None
    target_amount: float | None = None
    target_date: str | None = None
    #: A129. Passing null CLEARS it — see `GoalRevisionRequest`'s own note on why null is a value here,
    #: and `goals.check_occupancy` on why clearing is a real answer rather than a mistake.
    occupancy: str | None = None
    safety: str | None = None
    liquidity_need: str | None = None
    volatility_tolerance: str | None = None
    horizon: str | None = None
    flexibility: str | None = None
    #: R-030 again. Stating it replaces the funding; omitting it leaves the funding alone.
    funded_by_position_ids: list[str] | None = None

    #: C-09, exactly as on the create route. A member changing their plan states what they decided; the
    #: server does not compose that sentence on their behalf.
    question: str
    choice: str
    reasoning: str | None = None


@app.put("/api/goals/{goal_id}")
def revise_existing_goal(
    goal_id: str,
    body: GoalRevisionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """Change a goal after it was named. **The route that did not exist** — see `services/goals.revise_goal`.

    The owner's report was "if I have a Ziel, I can not change it afterwards", and that was literally true:
    `GET` and `POST` were the whole of `/api/goals`. Why this is an UPDATE plus a correcting Decision rather
    than a superseding row is argued in the service's docstring, which is where the estate's guarantees are
    weighed against each other.

    `PUT` and not `PATCH`, even though a partial body is accepted: the resource this addresses is the goal
    and what comes back is the goal's new state. The partiality is in the request model, and it is
    deliberate there for the reason its docstring gives.

    404 for a goal that is not this member's, on A81's reasoning: a wrong address and someone else's goal
    are indistinguishable, so the response cannot be used to find out who owns what.
    """
    from datetime import date as _date

    from ..services.goals import GoalNotFound, NothingToChange, revise_goal

    stated = body.model_dump(exclude_unset=True)
    for field in ("question", "choice", "reasoning"):
        stated.pop(field, None)
    funded_by = stated.pop("funded_by_position_ids", None)

    if "target_date" in stated and stated["target_date"] is not None:
        try:
            stated["target_date"] = _date.fromisoformat(stated["target_date"])
        except ValueError as bad:
            raise HTTPException(422, f"target_date must be ISO-8601: {bad}") from bad

    try:
        result = revise_goal(
            session,
            member_id=member.id,
            goal_id=goal_id,
            changes=stated,
            question=body.question,
            choice=body.choice,
            reasoning=body.reasoning,
            funded_by_position_ids=funded_by,
        )
    except GoalNotFound as missing:
        raise HTTPException(404, str(missing)) from missing
    except NothingToChange as unchanged:
        # 422, not 204: the request is well formed and nothing is wrong with the member. What is wrong is
        # that it asks for the state the goal is already in, and answering "done" would imply a Decision
        # was written.
        raise HTTPException(422, str(unchanged)) from unchanged
    except ValueError as bad:
        # An unknown template or a field that is not revisable. `NothingToChange` is a ValueError too and
        # is caught above, so the order of these two clauses is load-bearing.
        raise HTTPException(422, str(bad)) from bad
    session.commit()

    return {
        "id": result["goal"].id,
        "decision_id": result["decision"].id,
        # R-040's chain, named in the response so a client can show "this corrects an earlier record"
        # rather than having to know that it does.
        "corrects_decision_id": result["decision"].corrects_id,
        "changed": result["changed"],
    }


@app.get("/api/goal-templates")
def goal_templates() -> dict:
    """R-132. Courage money is offered as a template, not buried in copy.

    **This is the vocabulary route, and the third site the unit list was maintained at — by not being
    here.** `liquidity_bands` is served from `models.plan.LIQUIDITY` for the reason `services/grid.py`
    gives: one copy, on the server, so a member-scoped payload cannot carry a second that drifts. The
    magnitude units had no such route at all, so the client kept its own hand-written pair — which is the
    same defect wearing the opposite coat, and adding a third unit is what would have exposed it. A client
    that reads `magnitude_units` from here cannot offer a unit the server refuses, and cannot fail to offer
    one it accepts.

    `stock_kinds` travels beside it because it is not optional decoration: a `chf` magnitude is refused
    without one (`Position.stock_kind`), so a form that offers the unit and not the side of the balance
    sheet produces a 422 the member cannot act on.
    """
    return {
        "templates": list(GOAL_TEMPLATES.values()),
        "liquidity_bands": list(LIQUIDITY),
        "magnitude_units": list(MAGNITUDE_UNITS),
        "stock_kinds": list(STOCK_KINDS),
    }


@app.get("/api/destination")
def destination(language: str = DEFAULT_LANGUAGE) -> dict:
    """D-07 / A22. The one content key the destination phrase comes from, reachable at last.

    **What this closes.** A22 resolved D-07 on 30 August 2026 by promoting the build specification's own
    §1 phrasing into `client/content/destination.json` and reading it through `content.destination()`. A
    test scanned the backend to make sure nothing inlined the phrase, and it passed — because nothing said
    the phrase at all. `content.destination()` had no production caller and appeared in no payload, so the
    one key D-07 asked for was a key nothing read. A content record no surface can reach is not resolved,
    it is filed.

    **Its own route, and this is the argument for that rather than folding it into another payload.** D-07's
    requirement is one key, and the reason it gives is that the phrase is the one most likely to be revised
    and the one a template would most naturally inline. A route per phrase would be absurd; a route for
    *the* phrase is the shape of the requirement — every screen that needs it asks the same URL, and a
    reviewer looking for where the destination is stated finds one route, one content function and one
    file. Attaching it to the grid or the settings payload instead would have made it a field two screens
    read and a third screen quietly copied.

    **No session, and it names nobody.** The destination is what the product is for; it is identical for
    every member and is on screens a person sees before they have an account. `api/auth.py`'s docstring
    carries the line, and `test_api_auth.py::OPEN_ROUTES` carries the entry.

    **No fallback.** An unknown language is a 422 and a missing content file is a 500 out of
    `ContentMissing`, because a fallback literal is exactly how one key becomes forty copies — which is
    `content.destination()`'s own stated reason for raising rather than returning a default.
    """
    if language not in LANGUAGES:
        raise HTTPException(422, f"unknown language {language!r}; expected one of {list(LANGUAGES)} — A12.")
    try:
        phrase = destination_phrase(language)
    except ContentMissing as missing:
        # 500 rather than 404: the content record is part of the build, so its absence is this server being
        # broken and not the caller asking for something that does not exist.
        raise HTTPException(500, str(missing)) from missing
    return {
        "language": language,
        # The key name matches the content key, so a reader can follow the phrase from the screen to
        # `destination.json` without a mapping table in between.
        "destination": phrase,
    }


@app.get("/api/feed")
def feed(
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """Item 5's Feed, in the Reading Room's three sections.

    Guarded, unlike `/api/regime`: the hooks skip inputs already in the member's Vault, so this reads who
    is asking. It reads only *whether* an input exists — never a figure — which is what
    `services/inputs` is for.
    """
    return read_feed(session, member_id=member.id)


@app.get("/api/regime")
def regime(session: Session = Depends(get_session)) -> dict:
    """Item 5's Regime pane, and the first regulatory boundary made visible.

    **No session, deliberately.** Journey & Design page 3: "The regime and the return profiles are
    population-level and carry no member data at all: computed once, shared by everyone ... everything on
    the population side can be shown to anyone, before signup, without member data and without regulatory
    exposure." Item 5 adds the product argument: this "is the product's most distinctive output at zero
    data cost, and today nothing exposes it to someone who has not completed an intake".

    So it is in `OPEN_ROUTES` beside `/api/destination` and `/api/goal-templates`, and it takes no
    `member_id` — there is nobody for it to be about.

    **A reading, never an artefact.** `services/regime` admits only scalars out of the Regime's own
    `current` block, so the Fund Map's state grid and profile vectors stay on the server (C-03, R-304).

    **Not available is a 200, not a 500.** An unpublished AssumptionSet is a true state of the world and
    the payload says so; raising would make a public page look broken when it is merely honest.
    """
    return read_regime(session)


# ---------------------------------------------------------------- landing


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """R-001. The role grid is the default authenticated landing screen, not a dashboard or the vault."""
    page = PROJECT / "client" / "index.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    return "<h1>eigentliCH</h1><p>See <a href='/api/health'>/api/health</a>.</p>"


@app.get("/status", response_class=HTMLResponse)
def build_status() -> str:
    """The phase-status page. Moved off `/` now that there is a product screen to land on."""
    page = PROJECT / "client" / "status.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    raise HTTPException(404, "no status page")


# Static client assets. Mounted last so the routes above win.
#
# C-05: these are the ONLY origins the authenticated page loads from, because they are the only origin.
# No CDN mount, no external asset host. `check_dir=False` on content/ so a missing directory is a 404
# rather than a failure to boot.
for _mount, _folder in (("/app", "app"), ("/surfaces", "surfaces"), ("/style", "style")):
    _path = PROJECT / "client" / _folder
    if _path.exists():
        app.mount(_mount, StaticFiles(directory=_path), name=_folder.strip("/"))
