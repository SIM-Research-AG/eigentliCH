"""S-14, settings, consent and data. R-230, R-231, R-232.

**Nothing here writes a second export.** R-154 already built one, `services/export.py`, and it is the one
that round-trips and that carries `FORMAT_VERSION`. This module adds the thing S-14 asks for that R-154
does not: the Decision record of the request (R-231). Two exporters would mean two formats, and the second
one would be the one nobody verified.

**Consent withdrawal does not write a Decision, and that is deliberate.** C-09 attaches Decisions to plan
mutations; a `Consent` row is already its own append-only-shaped record, with `granted_at`, the document
version agreed to, and `withdrawn_at` set on withdrawal rather than the row being deleted. R-231 names
export and deletion as the two that produce a Decision, and it names them because those two leave no other
trace. Adding a third would look tidy and would put a K1 fact into a K2 audit for no requirement.

**R-232 is derived, never listed.** `data_class_statement` walks the mappers and reads each model's
`__data_class__`. A hand-written table of categories and classes is correct on the day it is written and
wrong from the first migration after it — and being wrong about which class a category falls into is worse
than saying nothing, because the member acted on it.

**Deletion is two steps, and this module owns the first one.** `request_deletion` records the request and
returns the receipt naming every category and its fate; `services/erasure.py` performs the act, reached
through `POST /api/settings/erasure`, which takes a typed confirmation and the member's password. The
second step lives in its own module for the reason that module's docstring gives: it drops the append-only
triggers and stands the C-09 guard down, and a reader should not meet that beside a language setting.

Until 31 August 2026 there was no second step at all: `request_deletion` returned
`retention_scope_undecided`, a reason A61 had already answered, and `erase_member` was complete, tested and
reachable only from tests. A90 found the pair.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

#: db.py's own map of the append-only tables, read rather than restated. A second list of which tables
#: refuse DELETE is a list that disagrees with the triggers the day someone adds a third — and R-232 is
#: the requirement about not hand-maintaining exactly this kind of table.
from ..consent import NotAConsent, consequence, is_notice, kind_of, notices, required_at_registration
from ..content import DEFAULT_LANGUAGE, LANGUAGES
from ..db import _APPEND_ONLY_TRIGGERS as APPEND_ONLY
from ..models import TOP_CLASS, Base, Classified, Consent, DataClass, Member
from .export import export_member
from .plan import mutate_plan
from .registration import withdraw_consent
from .vault import VaultStore

#: R-231. Why a deletion request is recorded but not executed. Named once, so the receipt, the Decision
#: and the tests all say the same thing.
#:
#: **The reason changed on 31 August 2026, and the change is the point.** It read
#: `retention_scope_undecided`, which stopped being true on 30 August when the owner decided what erasure
#: does to the append-only rows (A61) and `services/erasure.py` was built to it. What remained missing was
#: a route, and A90 found that the route the member can reach still reported the old reason. This request
#: is now the first of two steps: it records the request and hands back the receipt, and
#: `POST /api/settings/erasure` performs the act once the member has confirmed it.
DELETION_NOT_EXECUTED = "awaiting_confirmation"

#: The route that performs it, named here so the receipt can point at it and the two cannot drift.
ERASURE_ROUTE = "POST /api/settings/erasure"


class ConsentNotFound(LookupError):
    """A consent id that is not this member's. Not a 404 dressed as success — R-230 is about *their*
    history, and a withdrawal applied to the wrong row is the worst possible outcome of this screen."""


def _require_member(session: Session, member_id: str) -> Member:
    """Checked before anything is written.

    Without this, a request for a member who does not exist writes the Decision first and fails on the
    foreign key afterwards — a 500 where the honest answer is "no such member", and a half-open
    transaction carrying a record of a request nobody made.
    """
    member = session.get(Member, member_id)
    if member is None:
        raise LookupError(f"no member {member_id!r}")
    return member


# ---------------------------------------------------------------- A12 / A26, the language


class UnspeakableLanguage(ValueError):
    """A language the interface cannot actually speak.

    Named for what it means rather than "invalid language": `boundary.py` carries refusal texts in four
    languages and the client's string table carries two, so `fr` is a perfectly valid tag that would give a
    member a French refusal inside an otherwise German product. The set that may be stored is the set the
    interface has strings for.
    """


#: The region subtag a language falls back to when the member has none. CH, because this is a Swiss
#: product and switching language is not a statement about moving country.
DEFAULT_REGION = "CH"


def language_locale(language: str, *, current: str | None = None) -> str:
    """The locale to store for a language, keeping whatever region the member already had.

    `de-CH` → `en-CH`, not `en`. The member changed the language they read; nothing about them changed
    country, and dropping the region would quietly widen a locale that other code splits on.
    """
    region = DEFAULT_REGION
    if current and "-" in current:
        candidate = current.split("-", 1)[1].strip()
        if candidate:
            region = candidate
    return f"{language}-{region}"


def set_language(session: Session, *, member_id: str, language: str) -> Member:
    """A26: language is a setting, stored on `Member.locale`. **This is the thing that did not exist.**

    A12 shipped both languages and A26 put the switch "in S-14, on the column that already exists" — and
    the column existed, the English strings were complete, and there was no route, no service function and
    no control. Every seeded member was `de-CH`, so `STRINGS.en` was unreachable. The owner found it by
    looking for the switch: *"English vs German Version - where can I switch"*.

    **No Decision, and that is C-09 being read rather than skipped.** C-09 attaches a Decision to every
    material change to a member's *plan*; `Member` is not `PlanMutable` and a language is not a plan. This
    module already argues the same thing about consent withdrawal: R-231 names export and deletion as the
    two settings actions that produce a Decision, and it names them because those two leave no other trace.
    Which language someone reads leaves its trace in the interface they are looking at.

    **Refuses anything the interface cannot speak**, from `content.LANGUAGES` rather than a second list —
    a language stored here but missing from the string table gives a member a screen of key names.
    """
    if language not in LANGUAGES:
        raise UnspeakableLanguage(
            f"{language!r} is not a language this interface speaks. A12 ships {list(LANGUAGES)}; "
            f"boundary.py's refusal texts cover more, and a member cannot read a product in a language "
            f"only its refusals are written in."
        )
    member = _require_member(session, member_id)
    member.locale = language_locale(language, current=member.locale)
    return member


# ---------------------------------------------------------------- R-230


def consent_history(
    session: Session, *, member_id: str, language: str = DEFAULT_LANGUAGE
) -> dict:
    """R-230. Every consent ever given, in the order it was given, withdrawn ones included — and the
    notices, which have no rows at all.

    A withdrawn consent stays in the list. "Did they ever consent, and to what version" is the question the
    history answers, and hiding withdrawn rows would answer a different, easier one.

    **`consequence` is what makes "withdrawable" worth showing.** Until R-103's registry existed there was
    no way to say what follows from withdrawing one of these, so the screen could only offer a button. It
    comes from `consent.py`, in the member's language, and is `null` for a purpose no longer published — a
    retired purpose has no current consequence to state, and inventing one is the defect
    `services/derive.py` refused to commit.

    **And it says what actually follows, which is less than it used to claim.** Recording a
    withdrawal is all that happens: `withdrawn_at` is set, and no route, service or query in this
    application reads that column to gate anything. The sentence a member reads before confirming was
    corrected to match, on the owner's decision to keep the behaviour and fix the words.

    ------------------------------------------------------------------------------------------------------
    A97, AND WHAT THIS SHOWS FOR A ROW THAT IS NO LONGER A CONSENT
    ------------------------------------------------------------------------------------------------------

    `entscheidprotokoll` rows were written on 30 August, while it was still captured as a consent. They are
    real records of what a member agreed to, so **they stay in the list** — dropping them would be R-230
    answering the easier question again, and the development database and the demonstration accounts both
    hold them.

    What the row says changed in three fields, and all three come from the registry rather than from the
    row, because what a purpose *is* is a fact about today's registry and what the member did is the fact
    the row holds:

      * `kind` is `"notice"`. The client can label it as one.
      * `withdrawable` is False. The gate is `is_notice`, **not** "is a consent": a purpose retired from
        the registry altogether keeps whatever this screen already offered, and only a purpose the registry
        actively calls a notice loses its button. Leaving it True would have been the worst outcome of A97
        — a screen offering to revoke a record that R-040 makes undeletable, with `required_at_registration`
        reading False beside it, which together read as "optional, and you may take it back".
      * `consequence` explains why there is nothing to withdraw *and* why an agreement to it is still in
        the list. That sentence is written for both places it appears, here and on the registration form.

    **`notices` is the other half, and it is the half a new member gets.** Someone who registered after
    A97 has no row for the notice and never will, so a payload built from rows alone would say nothing
    about the record that cannot be deleted — the more surprising of the two facts. It is the published K0
    wording, read from the registry: no table, no per-member state, nothing recording that it was shown.
    """
    rows = session.execute(
        select(Consent).where(Consent.member_id == member_id).order_by(Consent.granted_at)
    ).scalars().all()

    return {
        "member_id": member_id,
        "consents": [
            {
                "id": row.id,
                "purpose": row.purpose,
                # A97. What the registry publishes this purpose as *today*: "consent", "notice", or null
                # for one it no longer publishes at all. The row itself is always a stored consent.
                "kind": kind_of(row.purpose),
                # R-103. Which wording was agreed to — the reason a boolean would have been useless here.
                "document_version": row.document_version,
                "granted_at": row.granted_at.isoformat() if row.granted_at else None,
                "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
                # R-230's second half, as a fact the client does not have to derive. A97 added the second
                # half of the condition; the service refuses the withdrawal too, so this is not the guard.
                "withdrawable": row.withdrawn_at is None and not is_notice(row.purpose),
                # R-103's registry, read rather than restated: whether an account is *opened* without
                # this one — a fact about registration and not about withdrawal — and what
                # follows once a withdrawal is recorded.
                "required_at_registration": required_at_registration(row.purpose),
                "consequence": consequence(row.purpose, language),
            }
            for row in rows
        ],
        # A97. Told, not asked, and told here as well as at registration.
        "notices": notices(language),
        "notices_are_not_a_choice": True,
        # Said out loud: withdrawal marks, it does not erase. A client should not offer "remove from list".
        "withdrawal_marks_rather_than_deletes": True,
    }


def withdraw(session: Session, *, member_id: str, consent_id: str, at: datetime | None = None) -> Consent:
    """R-230. Withdraw one consent, checking it belongs to this member first.

    Delegates to `services/registration.withdraw_consent`, which owns what withdrawal means. The check
    here is the thing this layer adds: an id arriving over HTTP is not proof of whose it is.

    **A97: a row naming a purpose that is now a notice is refused, and refused here.** In the service and
    not in the route, for A93's reason about the erasure confirmation — a second route reaching this
    function must not be able to skip it. `consent_history` already reports `withdrawable: false` for such
    a row, and a payload field is not a guard: a client that ignored it, or a caller that never read it,
    would otherwise stamp `withdrawn_at` onto a member's revocation of something R-040 makes undeletable.
    """
    consent = session.get(Consent, consent_id)
    if consent is None or consent.member_id != member_id:
        raise ConsentNotFound(f"no consent {consent_id!r} for member {member_id!r}")
    if is_notice(consent.purpose):
        raise NotAConsent(consent.purpose)
    return withdraw_consent(session, consent=consent, at=at)


# ---------------------------------------------------------------- R-231


def request_export(session: Session, store: VaultStore, *, member_id: str) -> dict:
    """R-231. Self-service export, with a Decision recording that it was requested.

    The export itself is R-154's, unchanged and not re-implemented. What this adds is the record: a member
    asking for everything they own is a material event, and S-07's answer to "what happened here" is a
    Decision.

    **The Decision is flushed before the export is composed**, so the export contains the record of its own
    request. That is not a curiosity: a file in a drawer should be able to say when and why it was made.
    """
    _require_member(session, member_id)
    with mutate_plan(
        session,
        member_id=member_id,
        question="Vollständiger Export aller eigenen Daten angefordert?",
        choice="Ja. Export erstellt und ausgeliefert.",
        author="member",
        reasoning="R-154 / R-231 — Selbstbedienung, ohne Freigabe durch Dritte.",
    ) as decision:
        session.flush()
        decision_id = decision.id

    export = export_member(session, store, member_id=member_id)
    return {
        "member_id": member_id,
        # R-231. The record of the request, named so a caller can link to it in the Decisions screen.
        "decision_id": decision_id,
        "export": export,
        "format": export["format"],
    }


def deletion_receipt(session: Session) -> dict:
    """What a deletion could and could not remove, derived from the store rather than described.

    Split by whether the table refuses DELETE. Those that refuse do so for R-040 and C-10, and the reason
    comes from `db.py`'s own map so that this receipt cannot drift from the triggers it describes.
    """
    erasable, retained = [], []
    for model, table in _classified_models():
        entry = {"category": table.name, "data_class": str(model.__data_class__)}
        if table.name in APPEND_ONLY:
            retained.append({**entry, "retained_because": APPEND_ONLY[table.name]})
        else:
            erasable.append(entry)
    return {
        "erasable": sorted(erasable, key=lambda e: e["category"]),
        "retained": sorted(retained, key=lambda e: e["category"]),
    }


def request_deletion(session: Session, *, member_id: str, reason: str | None = None) -> dict:
    """R-231, step one of two. The request is recorded and the receipt is returned. Nothing is destroyed.

    Not a stub, and not a queue for someone in support to work through — no human is in this path, which is
    what "self-service" required. **What this step exists for is the receipt**, and the receipt is worth a
    round trip: it names every stored category and which of them an erasure could not touch, so a member
    confirming on the next step is confirming something they have been shown.

      * Some of a member's material **cannot** be deleted. `Decision` and `CuratorSessionEvent` refuse
        UPDATE and DELETE at the storage layer (R-040, C-10) because the record of what was decided is the
        thing that survives a change of adviser. An erasure that quietly skipped them would be reporting a
        completion it did not achieve, so `services/erasure.py` empties them of the member instead and the
        report says which it did to what.
      * The residue and its retention were the owner's call and were taken on 30 August 2026 (A61): null
        the member reference and redact the free text, rather than deferring erasure until a retention
        policy exists.

    **This used to be where R-231 stopped**, with `not_executed_reason: retention_scope_undecided` — a
    reason that had already been overtaken by A61 and by a complete, tested `erase_member` that no route
    called. A90 found the pair. The erasure is reachable now; what stays here is the two-step shape, and
    step two is `ERASURE_ROUTE`, which takes a typed confirmation and the member's password.
    """
    _require_member(session, member_id)
    receipt = deletion_receipt(session)

    with mutate_plan(
        session,
        member_id=member_id,
        question="Löschung aller eigenen Daten angefordert?",
        choice="Antrag erfasst. Die Ausführung braucht eine Bestätigung im zweiten Schritt.",
        author="member",
        reasoning=reason,
        # What was actually weighed, stated as consequences rather than as verbs — the same shape C-06
        # requires of a prepared option, because this is the same kind of statement.
        options_considered=[
            {
                "label": "Antrag erfassen",
                "consequence": "Der Antrag ist als Entscheid festgehalten und nachweisbar. Die Daten "
                               "bestehen bis zur Bestätigung weiter.",
            },
            {
                "label": "Jetzt löschen",
                "consequence": "Braucht den zweiten Schritt: den getippten Bestätigungssatz und das "
                               "eigene Passwort. Danach ist der Vorgang nicht umkehrbar. Entscheide und "
                               "das Kuratoren-Protokoll bleiben als Zeilen bestehen (R-040, C-10), "
                               "ohne Namen und ohne Text.",
            },
        ],
    ) as decision:
        session.flush()
        decision_id = decision.id

    return {
        "member_id": member_id,
        "decision_id": decision_id,
        "requested": True,
        # Stated plainly, because a receipt that implied otherwise would be the most consequential lie this
        # application could tell.
        "executed": False,
        "not_executed_reason": DELETION_NOT_EXECUTED,
        # Where step two is, named from the constant so the receipt and the route cannot drift apart.
        "execute_at": ERASURE_ROUTE,
        **receipt,
    }


# ---------------------------------------------------------------- R-232


def _classified_models() -> list[tuple[type, object]]:
    """Every mapped model that carries a data class, with its table. The source for R-232 and the receipt.

    Reads the mapper registry rather than a list. A category added by a migration appears here on the day
    it exists, which is the only way a statement about "each stored category" stays true.
    """
    found = []
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, Classified):
            continue
        found.append((model, model.__table__))
    return found


def data_class_statement() -> dict:
    """R-232. Which data class each stored category falls into, derived from the models themselves.

    **Derived, so it cannot go stale.** Every entry comes from a model's `__data_class__` and its columns'
    own overrides (C-04's two levels, see `models/base.py`). Nothing is hand-listed; a category added later
    appears here without anyone remembering this function.

    **The words for what a class means are not here.** K0 to K3 come back as their names, and the sentence
    explaining what K2 means to a member is interface copy that belongs in the client's string table with
    the rest of it. This function states the assignment, which is the part that must not be written twice.
    """
    categories = []
    for model, table in _classified_models():
        row_class = model.__data_class__
        # C-04's per-field override: a column may classify itself above the row it sits in. Reported,
        # because "which class does this category fall into" has a second answer where one does.
        above = {
            name: str(model.field_data_class(name))
            for name in table.columns.keys()
            if model.field_data_class(name) > row_class
        }
        categories.append(
            {
                "category": table.name,
                "model": model.__name__,
                "data_class": str(row_class),
                "holds_member_material": model is Member or "member_id" in table.columns,
                "fields_classified_above_the_row": above,
                "leaves_the_server": row_class < TOP_CLASS,
            }
        )

    return {
        "categories": sorted(categories, key=lambda c: c["category"]),
        "scheme": [member.name for member in DataClass],
        "top_class": str(TOP_CLASS),
        # C-04, and the reason the export of a K3 category is the member's own copy and nobody else's.
        "top_class_never_leaves_the_server": True,
        "derived_from": "__data_class__",
        # Link tables (decision_positions and its siblings) hold no field of their own; they carry the
        # class of the rows they join, so they are not categories in this sense and do not appear above.
        "link_tables_carry_no_class_of_their_own": True,
    }
