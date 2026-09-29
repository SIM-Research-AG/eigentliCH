"""Phase 8 over HTTP: S-05 stage map, S-09 life-event modules, S-13 community, S-14 settings.

**One router for four screens, because they share one property**: none of them is allowed to return a
number about a member. The stage map may not say how far along it anybody is (R-006, R-140), the community
payload may not say how many gatherings were attended (R-221), and the life-event modules may not say
anything at all until a person writes them (R-183). A single module makes that one rule to hold rather
than four, and makes a route that quietly starts counting something visible in one diff.

**The routes add nothing to what the services compose.** No ordering parameter, no aggregate assembled at
the edge, no convenience field. Where a service refused to compute something, this layer is not the place
it reappears — the same choice `api/learning.py` records for the same reason.

**Three of these routes take no session, and the reason is the same for all three**: they can say
nothing about anybody. `GET /api/stages/{key}` has no member parameter by design (R-141 — any stage, any
age, opened by anybody), `GET /api/life-events` is seven unauthored module titles (R-183), and
`GET /api/settings/data-classes` is a statement about the schema. Everything else here resolves its member
from the bearer token; `api/auth.py` carries the full open list and the rule it was drawn from.

**`main.py` wires this in; this module never imports it at module scope.** The session and the vault store
are resolved inside their dependencies, after `main` has finished initialising, because an import at the
top would be a cycle that fails only in the order FastAPI happens to load things.

**One `/api/settings/*` route is deliberately not here: `POST /api/settings/erasure`.** It is in
`api/erasure.py`, for the reason `services/erasure.py` is also its own module — it is the only route that
destroys rows and the only one whose mistake cannot be corrected, and it should be findable by the name of
a file. `POST /api/settings/deletion` below is step one of that pair and names step two in its receipt.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..consent import NotAConsent
from ..content import ContentMissing, DEFAULT_LANGUAGE, LANGUAGES
from ..models import Member
from ..services.community import (
    GatheringCalledAnEvent,
    gatherings,
    record_attendance,
    create_gathering,
)
from ..services.settings import (
    ConsentNotFound,
    UnspeakableLanguage,
    consent_history,
    data_class_statement,
    request_deletion,
    request_export,
    set_language,
    withdraw,
)
from ..services.stages import (
    LIFE_EVENT_KEYS,
    life_event_modules,
    module_payload,
    stage_map,
    stage_payload,
    stage as stage_record,
)
from ..services.vault import VaultStore
from .auth import _language_for, current_member

router = APIRouter(prefix="/api", tags=["remainder"])


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import — see the module docstring."""
    from .main import get_session as application_session

    yield from application_session()


def get_store() -> VaultStore:
    """The application's vault store, resolved the same way and overridable in tests."""
    from .main import VAULT_STORE

    return VAULT_STORE


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise HTTPException(
            422, f"unknown language {language!r}; expected one of {list(LANGUAGES)} — A12."
        )
    return language


# ---------------------------------------------------------------- S-05 stage map


@router.get("/stages")
def get_stage_map(
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-05. Five situations, all open (R-141), none of them a position on a scale (R-140, R-006).

    The member is the token's, and buys only `opens_at` — their own `stage_hint`, which is content
    routing. There is still no parameter by which a client could ask "which stage am I on", because that
    question has no answer here; what changed is that `stage_hint` is a fact about a named person, and it
    used to be readable by handing this route somebody else's id.
    """
    try:
        return stage_map(session, member_id=member.id, language=_language(language))
    except ContentMissing as missing:
        # 503, not 500: the application is fine and the content record is not there. See api/learning.py.
        raise HTTPException(503, str(missing)) from missing


@router.get("/stages/{key}")
def get_stage(key: str, language: str = DEFAULT_LANGUAGE) -> dict:
    """R-141. Any stage, opened by anybody, at any age.

    **There is no member parameter on this route.** Not "the age is ignored" — there is nothing to ignore,
    which is the only version of that promise a reader can verify.
    """
    try:
        return stage_payload(stage_record(key), _language(language))
    except ContentMissing as missing:
        raise HTTPException(404, str(missing)) from missing


# ---------------------------------------------------------------- S-09 life-event modules


@router.get("/life-events")
def get_life_event_modules(
    language: str = DEFAULT_LANGUAGE,
    session: Session = Depends(get_session),
) -> dict:
    """S-09. The seven modules. All seven come back unauthored, and the payload says so — R-183.

    R-222: *this* is what "events" means in the interface. The community routes below never use the word.

    **Open, and the `member_id` parameter is deleted rather than guarded.** The service echoed it into the
    payload and did nothing else with it: seven titles and seven "not authored yet" are the same seven
    titles for everybody. A parameter that buys nothing is not made safe by a dependency, it is made
    honest by being removed. `/life-events/{key}` below is a different route and does need the member.
    """
    try:
        return life_event_modules(session, language=_language(language))
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing


@router.get("/life-events/{key}")
def get_life_event_module(
    key: str,
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """One module, with the member's relevant vault items already retrieved (R-181).

    Guarded, unlike the index above: this one reaches into the vault. R-181's retrieval was addressable
    by query parameter, so `?member_id=<someone else>` returned the titles and kinds of their documents.

    R-182 wants this reachable from The Know without navigating a menu, and `key` is what makes that
    possible: the seven keys are stable and are the whole address.
    """
    if key not in LIFE_EVENT_KEYS:
        raise HTTPException(404, f"no life-event module {key!r}; S-09 names {list(LIFE_EVENT_KEYS)}")
    try:
        return module_payload(session, key=key, member_id=member.id, language=_language(language))
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing


# ---------------------------------------------------------------- S-13 community


class ScheduleGathering(BaseModel):
    """R-220. A lecture, a café evening or a meet-up.

    Named `ScheduleGathering` rather than `CreateEvent` — R-222 is a rule about what the product calls
    these, and a request model is part of what the product calls things.
    """

    kind: str = Field(description="lecture | cafe_evening | meetup")
    title: str
    held_on: date
    description: str | None = None
    location: str | None = None
    fictional: bool = False


class RecordAttendance(BaseModel):
    """No `member_id`: a member records their own attendance, because the token is the only thing that
    says whose it is.

    **That is a narrowing, and it is stated rather than assumed.** Attendance is one of R-203's three
    ordering inputs (C-08), so before this change any caller could inflate any provider's community
    presence by posting attendances in their name. It now takes a session and writes it against that
    session's member — which still lets a member record their own, and that remains an open question with
    the same owner as every other write route here. What it no longer does is let one member write
    another's."""

    gathering_id: str
    attended: bool = True


@router.get("/community/gatherings")
def get_gatherings(
    on_or_after: date | None = None,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-13. The scheduled items, and whether this member was at each one.

    **No count of anything** (R-221). Attendance is an input to Market Place standing and is never shown to
    the member as a score, so the payload carries per-gathering facts and no aggregate at all. The ranking
    side reads `services.community.presence_evidence`, which is not exposed over HTTP.
    """
    return gatherings(session, member_id=member.id, on_or_after=on_or_after)


@router.post("/community/gatherings", status_code=201)
def schedule_gathering(
    body: ScheduleGathering,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """Schedule one. Staff-side in practice; who may call it is the same open question as every other
    write route in this prototype, and not one this change resolves on its own.

    A session is required, which is the weakest honest lock: this route names no member and stores none,
    so the dependency does not make it staff-only — it stops it being world-writable, which it was."""
    try:
        gathering = create_gathering(
            session,
            kind=body.kind,
            title=body.title,
            held_on=body.held_on,
            description=body.description,
            location=body.location,
            fictional=body.fictional,
        )
    except GatheringCalledAnEvent as named:
        raise HTTPException(422, str(named)) from named
    except ValueError as bad:
        raise HTTPException(422, str(bad)) from bad
    session.commit()
    return {"id": gathering.id, "kind": gathering.kind, "held_on": gathering.held_on.isoformat()}


@router.post("/community/attendance", status_code=201)
def post_attendance(
    body: RecordAttendance,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-220 / R-221. Recorded. The response says what was recorded and nothing about how often."""
    attendance = record_attendance(
        session,
        member_id=member.id,
        gathering_id=body.gathering_id,
        attended=body.attended,
    )
    session.commit()
    return {
        "id": attendance.id,
        "gathering_id": attendance.gathering_id,
        "attended": attendance.attended,
        # R-221, in the response as well as the listing: there is no total here and no route that returns one.
        "attendance_is_not_scored": True,
    }


# ---------------------------------------------------------------- S-14 settings, consent and data


class WithdrawConsent(BaseModel):
    """Empty on purpose. It carried `member_id`, which was the whole of R-230's "by the member"."""


class DataRequest(BaseModel):
    reason: str | None = None


class LanguageChoice(BaseModel):
    """A12 / A26. Which of the languages the interface speaks the member wants to read.

    A language and not a locale: `de-CH` is stored, `de` is chosen, and the mapping between them belongs on
    the server — `api/auth.py::_language_for` already refuses to let a client split a tag on a hyphen for
    exactly this reason.
    """

    language: str = Field(description=f"One of {list(LANGUAGES)} — A12.")


@router.put("/settings/language")
def put_language(
    body: LanguageChoice,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """A26. **The route that made the language switch possible.**

    A12 shipped both languages in phase 0 and A26 decided the switch would be a setting on `Member.locale`.
    The column was there and the English strings were complete; nothing could write the column, so every
    member was German and half the product was unreachable. The owner's report was *"where can I switch"*,
    and the honest answer was nowhere.

    `PUT` because it is one value being set to what the member chose, idempotently. It persists, because
    A26 makes this the member's setting rather than a per-tab toggle: they choose it once and it is theirs
    on the next device they open.

    Returns the locale as well as the language, so a client can refresh its stored identity from the
    response instead of guessing what `de` became.
    """
    try:
        updated = set_language(session, member_id=member.id, language=_language(body.language))
    except LookupError as missing:
        raise HTTPException(404, str(missing)) from missing
    except UnspeakableLanguage as refused:
        raise HTTPException(422, str(refused)) from refused
    session.commit()
    return {
        "member_id": updated.id,
        "locale": updated.locale,
        "language": body.language,
        # Said in the response because it is the difference between this and a session toggle, and the
        # difference is the whole of A26.
        "persisted": True,
    }


@router.get("/settings/consents")
def get_consents(
    member: Member = Depends(current_member), session: Session = Depends(get_session)
) -> dict:
    """R-230. The whole history, withdrawn entries included — **and the notices, which have no rows**.

    **This returned an empty list for every real member until 31 August 2026.** The route worked; nothing
    ever wrote a `Consent` row, because `POST /api/members` had no consent field — A90's finding, and the
    reason `consent.py` exists. R-103's capture point is at registration now, so a member who registered
    since has one entry in `consents`.

    **`notices` is why this route is not called `/consents` in spirit any more (A97).** A member who
    registered after the notice stopped being a consent has no row for it and never will, so a screen
    built from rows alone would tell them about the processing they agreed to and say nothing about the
    record that cannot be deleted — which is the more surprising of the two facts. It is the published K0
    wording, read from the registry, in the member's language; there is no per-member state in it and no
    table behind it.

    Each entry in `consents` carries `consequence`, in the member's own language rather than a query
    parameter's: a screen offering withdrawal without saying what follows is offering a button. The
    language comes from `Member.locale` through `api/auth.py::_language_for`, which is the one place a
    locale is split.
    """
    return consent_history(session, member_id=member.id, language=_language_for(member))


@router.post("/settings/consents/{consent_id}/withdraw")
def post_withdraw_consent(
    consent_id: str,
    body: WithdrawConsent,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-230. Withdrawable, by the member, without asking anyone.

    **What a 200 from here means, exactly (the decision of 1 September 2026).** The withdrawal is recorded: `withdrawn_at` is set on
    the row and the response carries it back. It is *not* a revocation of access — nothing reads that
    column to gate anything, so the member's session, their positions, their vault, their decisions,
    their export and their onboarding all continue to answer afterwards, and a new vault item can still
    be created. The consequence text served with the consent (`consent.py`) says so before the member
    confirms; it used to claim the opposite, and the owner decided to keep the behaviour and correct the
    wording rather than the reverse.

    **This docstring used to say "an id arriving over HTTP is not proof of whose it is" and then take one
    anyway.** It was true that the service checked the id against the consent — so you could not withdraw
    a consent that was not the id's — but the id itself was unauthenticated, so anyone could withdraw
    anyone's consent by naming them. The member is the token's now and the service still checks the pair,
    which is what makes a 404 mean "not yours" rather than "not there".

    **A97: a row naming a purpose that is now a notice cannot be withdrawn**, and the refusal is the
    service's rather than this route's. 422 and not 404: the row is there and it is theirs, and the reason
    nothing happens is that there is no longer anything to withdraw. Marking `withdrawn_at` on it would
    record a member revoking something they cannot revoke — the decision record is undeletable at the
    storage layer — which is the misrepresentation A97 was decided to end, written into a column.
    """
    try:
        consent = withdraw(session, member_id=member.id, consent_id=consent_id)
    except ConsentNotFound as missing:
        raise HTTPException(404, str(missing)) from missing
    except NotAConsent as refused:
        raise HTTPException(422, str(refused)) from refused
    session.commit()
    return {
        "id": consent.id,
        "purpose": consent.purpose,
        "document_version": consent.document_version,
        "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
    }


@router.post("/settings/export", status_code=201)
def post_export_request(
    body: DataRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
    store: VaultStore = Depends(get_store),
) -> dict:
    """R-231. Self-service export that also writes the Decision recording the request.

    **This is the export a client should call, and `GET /api/export` is not.** A90 found the asymmetry from
    the other side: the route the client actually used was the GET, which writes no Decision, so R-231's
    "both producing a Decision record" held only on the path nobody called.

    **The two paths stay different, deliberately, and the difference is the method.** A GET must be safe:
    a browser prefetch, a retry, a proxy revalidation or a double-click on a link may repeat it, and each
    repetition would write a Decision — into a table that R-040 makes append-only, where it cannot be
    tidied away afterwards. S-07's screen would fill with export requests the member never made and there
    would be no correcting them. So `GET /api/export` remains R-154's plain read of the member's own file,
    and the act of *requesting* an export — the thing R-231 wants a record of — is a POST.

    The document is the same either way: both call `services/export.py::export_member`, there is one
    `FORMAT_VERSION`, and `tests/test_export_asymmetry.py` asserts the two bodies agree and that the GET
    still writes nothing. The shapes differ by one level of nesting — this route answers
    `{member_id, decision_id, export, format}` and the GET answers the export document itself — so a
    client moving across reads `payload["export"]`.
    """
    try:
        payload = request_export(session, store, member_id=member.id)
    except LookupError as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return payload


@router.post("/settings/deletion", status_code=201)
def post_deletion_request(
    body: DataRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-231, step one. The request is recorded as a Decision and the receipt comes back. Nothing is
    destroyed here.

    The receipt names every stored category and which of them an erasure cannot remove. 201 is "your
    request is recorded", the body says `executed: false` in as many words, and `execute_at` names step
    two — `POST /api/settings/erasure` in `api/erasure.py`, which takes the typed confirmation sentence and
    the member's password.

    **`not_executed_reason` used to be `retention_scope_undecided` and now is `awaiting_confirmation`.**
    The old reason had been overtaken by A61 on 30 August 2026 while the route went on reporting it, which
    is the half of A90's erasure finding that was visible from the outside.
    """
    try:
        payload = request_deletion(session, member_id=member.id, reason=body.reason)
    except LookupError as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return payload


@router.get("/settings/data-classes")
def get_data_classes() -> dict:
    """R-232. Which data class each stored category falls into, derived from the model layer.

    No database session and no member session: this is a statement about the schema, not about a member,
    and asking for either would imply the answer differs per person.
    """
    return data_class_statement()
