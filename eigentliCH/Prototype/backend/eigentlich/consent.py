"""R-103's registry: the purposes eigentliCH publishes, which of them a member is *asked*, and the wording.

**What was missing, and it was not the model.** `Consent` has been a versioned, timestamped record since
phase 0 and `withdraw_consent` has always worked. What did not exist was the *capture point*: no code path
ever wrote a `Consent` row for a real member, so R-230's "consent history visible and withdrawable" came
back empty for everybody and C-05's "sole data controller from the first intake question" had no artefact
behind it at all. A90 found it by reading every identifier in the specification.

---------------------------------------------------------------------------------------------------------
ASKED, OR TOLD — A97
---------------------------------------------------------------------------------------------------------

A93 captured two purposes as consents and flagged the question rather than deciding it: is
`entscheidprotokoll` properly *consent* at all, or a notice? **The owner answered on 31 August 2026: a
notice is sufficient.** A member cannot use eigentliCH without their decisions being recorded — R-040 and
C-10 make those rows undeletable at the storage layer and R-231 empties them rather than removing them —
so offering it as a choice they could decline was misleading, because there is no version of the product
where declining is honoured. They must be **told**.

So this registry holds one vocabulary with two `kind`s, and that is the point of the shape:

  * `kind="consent"` — the member is **asked**, a `Consent` row records the answer, and R-230 shows it and
    offers withdrawal with a stated consequence.
  * `kind="notice"`  — the member is **told**. No row is written for it anywhere: `verify_acceptance`
    refuses one offered as a consent, `register_member` refuses one handed to it directly, and
    `REQUIRED_PURPOSES` and `echo_at_registration` do not name it.

A notice and a consent are the same kind of artefact — published, versioned, impersonal K0 wording — and
they differ in one field, so they live in one tuple rather than in two modules. Splitting them would have
produced two lists of purposes that must agree, which is the defect A73 and A91 both are.

**Being told is not a lesser event, and the notice is the more surprising of the two facts.** That a
decision record cannot be removed *even by eigentliCH*, and survives an erasure emptied of name and text, is
the thing a member would not guess. So it is served at registration (`GET /api/consent-statement`, beside
the consent, carrying `kind`) and afterwards in the same place the consents are read
(`GET /api/settings/consents`, whose payload carries `notices` for members whose history has no row for it
and never will).

**No record of the notice having been displayed is kept** — no table, no migration, no per-member row. The
owner asked for *sufficient*, which is a request for less machinery, and a row asserting "we told them" is
a consent record with the honesty removed. If an audit trail of the telling is ever wanted, that is a
decision to take deliberately and not a gap to fill in quietly.

---------------------------------------------------------------------------------------------------------
WHAT A WITHDRAWAL ACTUALLY DOES — 1 SEPTEMBER 2026
---------------------------------------------------------------------------------------------------------

**It writes `withdrawn_at` and it stops there.** No code in this application reads that column to decide
anything: the member still logs in, `/api/positions`, `/api/vault`, `/api/decisions`, `/api/export` and
`/api/onboarding` all still answer, and a new vault item can still be created after a withdrawal. An audit
measured every one of those on 1 September 2026.

The `datenbearbeitung` consequence used to say the processing must stop and that "an account cannot
continue without it". **The owner decided to keep the behaviour and correct the words**, so the wording
below says what happens: the withdrawal is registered against a date and a version, and what follows is a
conversation with eigentliCH rather than an automatic revocation. It deliberately does not overstate in the
other direction either — a member reading it should understand that their withdrawal *was* registered and
that their access has not stopped, which is exactly the pair of facts the old sentence got backwards.

**Nothing in this file, in `services/registration.py`, in `services/settings.py` or in `api/remainder.py`
may claim otherwise.** `withdrawn_at` is written and read by nothing that gates behaviour, and that is the
intended state rather than an omission; a comment asserting a consequence that does not exist is the defect
this build has now hit nine times. `required_at_registration` is the one flag that does gate something, and
it gates **registration** — an account is not opened without these consents — which is a different sentence
from the one it used to carry.

---------------------------------------------------------------------------------------------------------
WHY `purpose` IS A CLOSED SET
---------------------------------------------------------------------------------------------------------

`Consent.purpose` was a free-text `String(80)` with no registry, and `services/derive.py` had already
written down what that costs: it declined to build R-152's "a consent was never given or withdrawn" action
item because *"no code path reads it, and no registry of purposes exists"*, so any item it produced would
have had to state a consequence that is not true. C-06 asks for the options and their consequences, not for
two plausible sentences.

A free-text purpose fails at three separate jobs:

  * **R-230.** A history is a list of what was agreed to. `"onboarding"` in one row and
    `"datenbearbeitung"` in another are not two answers to one question, they are two questions, and the
    member reading the screen cannot tell which.
  * **withdrawal that can be reasoned about at all.** A withdrawal is only a record of something if the
    thing withdrawn can be named the same way twice. Code cannot branch on a string nobody guaranteed
    the spelling of, so a typo is indistinguishable from a real grant — and it is indistinguishable
    *silently*. (This bullet used to say that withdrawing changes what the application will do. It does
    not; see WHAT A WITHDRAWAL ACTUALLY DOES below.)
  * **R-103's versioning.** A `document_version` is the version *of something*. Free text lets the two
    drift: `purpose="datenbearbeitung"` with `document_version="kur@2026-01"` is storable nonsense.

So the set is closed here, and `Consent.purpose` is validated against it on the model
(`models/member.py`), which is where every write in this application passes.

**And there is deliberately no CHECK constraint, unlike R-100's age floor.** The floor is an invariant
that never legitimately varies, so baking `>= 18` into the table costs nothing. A vocabulary is not that:
purposes are added and retired as the product's processing changes, and a `Consent` row has to outlive the
registry entry it names — R-230's question is *"did they ever consent, and to what version"*, which is
exactly a question about a purpose that may no longer be offered. A CHECK naming today's vocabulary would
be fired at every historical row by alembic's batch-mode table copy, so the day a purpose is retired the
migration fails on the consent history it was written to protect. A63 and A68 were both `batch_alter_table`
casualties in this repository; that hazard is not hypothetical here. **This is a place the owner may
reasonably decide otherwise** — the trade is: raw SQL can insert an unregistered purpose, and a retired
purpose can never make a migration fail.

**A97 is the first real exercise of that reason.** `entscheidprotokoll` rows written on 30 August name a
purpose that is no longer a consent, and they are still real records of what a member agreed to. So the
validator's closed set is *every registered purpose, of either kind* — the row stays readable, writable and
exportable — and what stops a new one being written is the two write points refusing it, not the vocabulary
pretending the key never existed. A CHECK listing only today's consents would have failed the next
migration on exactly these rows.

---------------------------------------------------------------------------------------------------------
THE WORDING IS PROVISIONAL, AND SAYS SO
---------------------------------------------------------------------------------------------------------

These are plain-language descriptions of what eigentliCH actually does, written so that the capture point
could exist and be tested. They are **not** a data-protection notice and were not written by anybody
qualified to write one. `PROVISIONAL` is True and the statement route says so in its payload, the same way
D-03 ships the role definitions marked provisional until someone reviews them. **A97 does not change
that**: calling one of them a notice rather than a consent settles what a member is asked, not who wrote
the words.

---------------------------------------------------------------------------------------------------------
C-04
---------------------------------------------------------------------------------------------------------

The statements below are K0: published, impersonal, identical for every member, and served by a route that
requires no session because it names nobody. The `Consent` row is K1 — it says that *this member* agreed,
which is a fact about a person. That split is why the wording lives in this module and is referenced by
key from the row, rather than being copied into `Consent.notes` per member. A notice is K0 all the way
down, which is the other half of why it needs no table: there is no K1 fact in it to store.

C-01 applies to every string here and `tests/test_consent.py` runs all of them through
`boundary.check_answer`, in both languages, requiring `requires_curator` False — the refusal messages
included, because a route hands those to a member as an HTTP detail.

**Imports nothing from this package.** A leaf, like `boundary.py` and `content.py`, so that
`models/member.py` can validate against it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The two languages the interface speaks (A12). Restated rather than imported: `content.py` is a leaf too
#: and importing it here would tie the model layer's validator to the content loader for one tuple. The
#: parity is held by a test instead, which is the same arrangement `boundary.py` has.
LANGUAGES = ("de", "en")

#: D-03's arrangement, applied to wording nobody qualified has reviewed. The statement route reports it.
PROVISIONAL = True

#: A97. The member is **asked**, and the answer is a `Consent` row.
KIND_CONSENT = "consent"

#: A97. The member is **told**. Nothing records the telling; see the module docstring for why not.
KIND_NOTICE = "notice"

#: Closed, like the purpose vocabulary and for the same reason: a third kind would be a third rendering on
#: the registration screen, and a client cannot be asked to guess what to do with a word it has not met.
KINDS = (KIND_CONSENT, KIND_NOTICE)


@dataclass(frozen=True)
class Purpose:
    """One purpose of processing: what it is, which version of the wording says so, and how the member
    meets it — asked (`KIND_CONSENT`) or told (`KIND_NOTICE`).

    Frozen, so the registry cannot be edited at runtime by anything that imports it.
    """

    key: str
    kind: str
    document_version: str
    #: True only for a consent, and checked below. For a notice there is nothing to require of the member:
    #: the obligation runs the other way, and it is eigentliCH's.
    required_at_registration: bool
    statement: dict[str, str]
    #: What follows. For a consent, what happens once a withdrawal is recorded; for a notice, why there
    #: is nothing to withdraw. One field because both answer the member's next question, which is the
    #: same question. **It must describe what the code does** — an audit on 1 September 2026 found this
    #: field asserting an automatic revocation that no code path performs.
    consequence: dict[str, str]

    def __post_init__(self) -> None:
        """The one combination that must not be expressible: a notice marked required.

        A notice a member is *required* to accept is a consent with the choice removed, which is the exact
        misrepresentation A97 was decided to end. Refused at construction, so it cannot be reintroduced by
        editing one field of one entry — the shape of mistake that would otherwise pass every test below,
        all of which read `required_at_registration` rather than restating it.
        """
        if self.kind not in KINDS:
            raise ValueError(
                f"{self.kind!r} is not one of {list(KINDS)}. A purpose is either asked (a consent) or "
                f"told (a notice); a third kind has no rendering on the registration screen."
            )
        if self.kind == KIND_NOTICE and self.required_at_registration:
            raise ValueError(
                f"{self.key!r} is a notice and cannot be required at registration. A notice the member "
                f"must accept is a consent with the choice taken out of it, which is what A97 decided "
                f"against: they are told, not asked."
            )

    @property
    def is_consent(self) -> bool:
        return self.kind == KIND_CONSENT

    @property
    def is_notice(self) -> bool:
        return self.kind == KIND_NOTICE

    def payload(self, language: str) -> dict:
        return {
            "purpose": self.key,
            # A97. What the client must render: a consent gets a control the member operates, a notice
            # gets text. Sent rather than inferred from `required_at_registration`, because a client that
            # inferred it would show an unrequired consent and a notice the same way.
            "kind": self.kind,
            "document_version": self.document_version,
            "required_at_registration": self.required_at_registration,
            "statement": self.statement[language],
            # R-230's second half needs this to mean something on screen: a member about to withdraw a
            # consent is entitled to know what follows. What follows is that the withdrawal is recorded
            # and eigentliCH takes it up with them — **not** an automatic revocation, because nothing in
            # this application branches on `withdrawn_at` (the decision of 1 September 2026). For a notice it says why no withdrawal
            # is offered, which is the question a member reading a fact they did not choose will ask.
            "consequence": self.consequence[language],
            # C-04. The wording is published and impersonal; the row recording that this member agreed
            # is K1 and lives in `consents`. A notice has no such row at all.
            "data_class": "K0",
        }


#: The processing every member's material goes through, from the first intake question (C-05). Asked.
DATENBEARBEITUNG = "datenbearbeitung"

#: R-040 and C-10: the decision record is permanent, and survives erasure emptied rather than removed.
#: **Told, not asked, as of A97.**
ENTSCHEIDPROTOKOLL = "entscheidprotokoll"


PURPOSES: tuple[Purpose, ...] = (
    Purpose(
        key=DATENBEARBEITUNG,
        kind=KIND_CONSENT,
        # `dsg@2026-01` is the string the estate was already using for this purpose in
        # `tests/test_settings.py`; kept rather than replaced, so the vocabulary has one spelling.
        document_version="dsg@2026-01",
        required_at_registration=True,
        statement={
            "de": (
                "eigentliCH speichert und bearbeitet, was Sie hier erfassen: Ihre Antworten, Ihre "
                "Positionen, Ihre Ziele, Ihre Dokumente und die festgehaltenen Entscheide. eigentliCH ist "
                "dafür allein verantwortlich. Nichts davon geht an Dritte, es laufen keine Analyse- oder "
                "Statistikdienste mit, und das Sprachmodell läuft auf einem Rechner von eigentliCH."
            ),
            "en": (
                "eigentliCH stores and processes what you enter here: your answers, your positions, your "
                "goals, your documents and the decisions recorded. eigentliCH alone is responsible for "
                "this. None of it goes to a third party, no analytics or statistics service runs "
                "alongside it, and the language model runs on a machine belonging to eigentliCH."
            ),
        },
        # What this said until 1 September 2026 was false, and an audit measured it: a withdrawal
        # writes `withdrawn_at`, answers 200 and changes nothing else — login still succeeds, every
        # member route still answers, and a new vault item can still be created. The text claimed the
        # processing must stop and that "an account cannot continue without it". The owner decided to
        # keep the behaviour and correct the words, so this describes what actually happens: the
        # withdrawal is registered, and what follows it is a conversation rather than a switch. It does
        # not overstate in the other direction either — a member reading it should not come away
        # thinking their withdrawal went nowhere.
        consequence={
            "de": (
                "Ein Widerruf wird festgehalten, mit Datum und mit der Fassung, die Ihnen vorlag. Er "
                "beendet den Zugang nicht von selbst: Ihr Konto bleibt bestehen, Ihre Einträge bleiben "
                "erhalten, und die Bearbeitung endet nicht automatisch mit dem Klick. eigentliCH nimmt "
                "den Widerruf entgegen und klärt das weitere Vorgehen mit Ihnen; was danach mit Ihren "
                "Angaben geschieht, wird dort besprochen und nicht von diesem Formular entschieden. "
                "Wenn Ihre Daten entfernt werden sollen, ist die Löschung in den Einstellungen der Weg "
                "dazu."
            ),
            "en": (
                "A withdrawal is recorded, with the date and the version of the wording you were shown. "
                "It does not end your access by itself: your account stays, your entries stay, and "
                "processing does not stop automatically when you confirm. eigentliCH receives the "
                "withdrawal and settles what happens next with you; what becomes of your entries is "
                "decided there and not by this form. If the data is to be removed, the erasure in "
                "Settings is the way to do that."
            ),
        },
    ),
    Purpose(
        key=ENTSCHEIDPROTOKOLL,
        # A97. The statement is unchanged from the day this was a consent: it was always a description of
        # what happens rather than a question, which is part of why the owner read it as a notice.
        kind=KIND_NOTICE,
        document_version="ent@2026-01",
        required_at_registration=False,
        statement={
            "de": (
                "Jede Änderung wird als Entscheid festgehalten: die Frage, die gewählte Antwort und die "
                "Begründung. Diese Einträge lassen sich nachträglich nicht ändern und nicht löschen, auch "
                "nicht von eigentliCH; eine Korrektur ist ein neuer Eintrag, der auf den früheren verweist. "
                "Bei einer Löschung bleiben die Zeilen bestehen, ohne Ihren Namen und ohne Ihren Text."
            ),
            "en": (
                "Every change is kept as a decision: the question, the choice made and the reasoning. "
                "These entries cannot be altered or removed afterwards, by anyone, eigentliCH included; a "
                "correction is a new entry referring to the earlier one. When your data is erased the "
                "rows remain, without your name and without your text."
            ),
        },
        consequence={
            "de": (
                "Dies ist ein Hinweis und keine Zustimmung: das Festhalten gehört zum Dienst und lässt "
                "sich nicht abwählen, deshalb wird es Ihnen mitgeteilt und nicht zur Wahl gestellt. Es "
                "gibt hier nichts zu widerrufen. Wenn in Ihrer Liste noch eine Zustimmung dazu steht, "
                "bleibt sie sichtbar: sie wurde erfasst, als eigentliCH danach gefragt hat."
            ),
            "en": (
                "This is a notice and not a consent: the record is part of the service and cannot be "
                "switched off, so you are told about it rather than asked. There is nothing here to "
                "withdraw. If an agreement to it still appears in your list, it stays visible: it was "
                "recorded while eigentliCH was still asking."
            ),
        },
    ),
)

#: By key, for the model's validator and for the history payload.
BY_KEY: dict[str, Purpose] = {purpose.key: purpose for purpose in PURPOSES}

#: Every purpose a `Consent` row may name, **of either kind**. The notice is in here on purpose: rows
#: naming it were written while it was a consent, and a validator that refused the key would make a real
#: historical record unwritable — the row could still be read, because SQLAlchemy's `@validates` does not
#: fire on load, but it could not be re-saved, exported through an ORM copy, or built by the test that
#: proves R-230 still shows it. What keeps new ones out is `verify_acceptance` and `register_member`.
REGISTERED_PURPOSES: tuple[str, ...] = tuple(BY_KEY)

#: A97. The purposes a member is asked about, and the only ones a *new* `Consent` row may name.
CONSENT_PURPOSES: tuple[str, ...] = tuple(purpose.key for purpose in PURPOSES if purpose.is_consent)

#: A97. The purposes a member is told about. No row, ever — but they must reach the member, at
#: registration and afterwards, and both payloads carry them.
NOTICE_PURPOSES: tuple[str, ...] = tuple(purpose.key for purpose in PURPOSES if purpose.is_notice)

#: The consents without which no account is opened. Not a subset chosen for convenience: this describes
#: something this build does to every member from the first intake question, so a member who declined it
#: would be told the application does less than it does.
REQUIRED_PURPOSES: tuple[str, ...] = tuple(
    purpose.key for purpose in PURPOSES if purpose.required_at_registration
)


class UnregisteredPurpose(ValueError):
    """A purpose that is not in the registry. Carries the set, so the message does not restate it."""

    def __init__(self, purpose: object) -> None:
        super().__init__(
            f"{purpose!r} is not a purpose eigentliCH publishes. R-103's registry holds "
            f"{list(REGISTERED_PURPOSES)}; a purpose outside it is a record nobody can later reason "
            f"about, which is why the set is closed."
        )
        self.purpose = purpose


class NotAConsent(ValueError):
    """A97. A registered purpose, offered or stored as a consent, that eigentliCH publishes as a notice.

    Refused rather than dropped. Silently ignoring it would mean a registration form that showed a
    checkbox nobody server-side believes in, and a member who ticked something that had no effect; and
    silently writing it would put back the row A97 decided not to keep. The client is told instead, which
    is how a form left over from yesterday gets noticed rather than half-honoured.
    """

    def __init__(self, purpose: str) -> None:
        super().__init__(
            f"{purpose!r} is published as a notice rather than a consent: eigentliCH tells a member this "
            f"happens instead of asking, because it cannot be declined and the record cannot be removed "
            f"afterwards. There is nothing here to accept or to withdraw. The consents to send are "
            f"{list(REQUIRED_PURPOSES)}."
        )
        self.purpose = purpose


class StaleConsentDocument(ValueError):
    """The wording the client displayed is not the wording currently published.

    Refused rather than corrected. Stamping the current version onto an acceptance of an older text would
    record that the member agreed to words they were never shown, which is the one thing a versioned
    consent record exists to prevent.
    """

    def __init__(self, purpose: str, offered: object) -> None:
        current = BY_KEY[purpose].document_version
        super().__init__(
            f"consent for {purpose!r} was offered as {offered!r}; the published version is "
            f"{current!r}. The wording changed since the form was shown, so this acceptance is not an "
            f"acceptance of it."
        )
        self.purpose = purpose
        self.offered = offered
        self.current = current


class MissingRequiredConsent(ValueError):
    """R-103 / C-05. An account cannot exist without these, so registration stops here."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            "eigentliCH does not open an account without consent to: "
            + ", ".join(missing)
            + ". Each one describes what happens to a member's material from the first intake question "
            "(C-05), so there is no version of the account that does not do it."
        )
        self.missing = missing


class DuplicateConsent(ValueError):
    """The same purpose twice in one acceptance. Refused rather than deduplicated: two grants of one
    purpose in one act means the form sent something nobody can interpret, and guessing which one was
    meant is guessing about consent."""

    def __init__(self, purpose: str) -> None:
        super().__init__(f"consent for {purpose!r} appears more than once in one registration")
        self.purpose = purpose


def statement(language: str) -> dict:
    """R-103 / C-05, as a payload. What is being agreed to and what is being disclosed, before an account
    exists.

    Open to anybody by design: this is authored K0 text that names no member, and a form that could not
    be read without a session could not be read by the person about to register.

    `purposes` carries both kinds, each with its `kind`, because the registration screen shows both. The
    three lists beside it say what to do with them and are all derived from the one tuple:

      * `required_at_registration` — the consents the member must accept.
      * `notices` — the purposes to display and *not* offer as a choice.
      * `echo_at_registration` — the exact list `POST /api/members` expects back.

    Handing `echo_at_registration` over rather than letting the client assemble it is what makes the
    version check in `verify_acceptance` a real check: the client echoes the version of the wording it
    displayed, and a form left open across a wording change is refused instead of silently recording
    agreement to text nobody saw.
    """
    if language not in LANGUAGES:
        raise ValueError(f"{language!r} is not one of {list(LANGUAGES)}")
    return {
        "language": language,
        "wording_is_provisional": PROVISIONAL,
        "purposes": [purpose.payload(language) for purpose in PURPOSES],
        "required_at_registration": list(REQUIRED_PURPOSES),
        "notices": list(NOTICE_PURPOSES),
        # A97, said in the payload rather than left to the client's judgement. A notice rendered as an
        # unchecked box is the misrepresentation this decision removed, arriving back through the front
        # end; a notice rendered as a *checked* box the member cannot clear is the same thing wearing a
        # tick. It is text, and it has to be there.
        "notices_are_not_a_choice": True,
        "echo_at_registration": [
            {"purpose": purpose.key, "document_version": purpose.document_version}
            for purpose in PURPOSES
            if purpose.required_at_registration
        ],
    }


def notices(language: str) -> list[dict]:
    """A97. The notices alone, for a screen that is not the registration form.

    `GET /api/settings/consents` reads this: a member who registered after A97 has no row for the notice
    and never will, so a settings screen built only from rows would tell them about the processing they
    agreed to and say nothing at all about the record that cannot be deleted. That is the more surprising
    of the two facts, and burying it is worse than the ceremony A97 removed.
    """
    if language not in LANGUAGES:
        raise ValueError(f"{language!r} is not one of {list(LANGUAGES)}")
    return [purpose.payload(language) for purpose in PURPOSES if purpose.is_notice]


def verify_acceptance(entries: object) -> list[dict]:
    """What the registration form sent, checked, and turned into rows `register_member` can write.

    Five refusals, and all five are refusals rather than repairs:

      * a purpose outside the registry            `UnregisteredPurpose`
      * a purpose published as a notice           `NotAConsent`
      * a `document_version` that is not current  `StaleConsentDocument`
      * the same purpose twice                    `DuplicateConsent`
      * a required consent absent                 `MissingRequiredConsent`

    **Nothing here is optional and nothing defaults.** A parameter that could fill in a missing consent
    is the same shape as the developer bypass A81 refused: it would be the path that gets used, and the
    consent would be eigentliCH's rather than the member's.

    Returns the `consents=` list `services/registration.register_member` takes, so the capture point adds
    a check and not a second way of writing the row.
    """
    if not isinstance(entries, (list, tuple)):
        raise MissingRequiredConsent(list(REQUIRED_PURPOSES))

    accepted: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        purpose = entry.get("purpose") if isinstance(entry, dict) else getattr(entry, "purpose", None)
        version = (
            entry.get("document_version")
            if isinstance(entry, dict)
            else getattr(entry, "document_version", None)
        )
        if purpose not in BY_KEY:
            raise UnregisteredPurpose(purpose)
        if BY_KEY[purpose].is_notice:
            raise NotAConsent(purpose)
        if purpose in seen:
            raise DuplicateConsent(purpose)
        if version != BY_KEY[purpose].document_version:
            raise StaleConsentDocument(purpose, version)
        seen.add(purpose)
        accepted.append({"purpose": purpose, "document_version": version})

    missing = [purpose for purpose in REQUIRED_PURPOSES if purpose not in seen]
    if missing:
        raise MissingRequiredConsent(missing)
    return accepted


def is_registered(purpose: object) -> bool:
    """For the model validator, which needs the question rather than the exception."""
    return isinstance(purpose, str) and purpose in BY_KEY


def kind_of(purpose: str) -> str | None:
    """A97. `KIND_CONSENT`, `KIND_NOTICE`, or None for a purpose no longer published.

    None rather than a guess. R-230 shows a row whose purpose has been retired from the registry, and
    claiming it is a consent — or a notice — would be stating something this file no longer knows.
    """
    entry = BY_KEY.get(purpose)
    return entry.kind if entry else None


def is_notice(purpose: str) -> bool:
    """Whether eigentliCH publishes this purpose as a notice today.

    False for a purpose not in the registry, and that asymmetry is deliberate: a retired purpose keeps
    whatever R-230 already offered for it, and only a purpose the registry *actively* calls a notice loses
    its withdrawal button.
    """
    return kind_of(purpose) == KIND_NOTICE


def required_at_registration(purpose: str) -> bool:
    """Whether an account is opened without this one. It is not.

    **This is a fact about registration and about nothing else (the decision of 1 September 2026).** It used to read "whether
    withdrawing this one means the account cannot continue", which stated a consequence no code
    performs: `register_member` refuses to open an account without these consents, and that is the whole
    of what the flag governs. Withdrawal afterwards records the withdrawal and gates nothing.

    False for a notice — nothing is required of the member, because nothing was asked — and False for a
    purpose no longer published: a historical row is still a real record and the history still shows it
    (R-230).
    """
    entry = BY_KEY.get(purpose)
    return bool(entry and entry.required_at_registration)


def consequence(purpose: str, language: str) -> str | None:
    """What follows, in the member's language, or None for a purpose not in the registry.

    For a consent: what happens once a withdrawal is recorded — which, as of 1 September 2026, is that it
    is recorded and taken up with the member, and not that anything is switched off. For a notice: why
    there is nothing to withdraw, and what a historical agreement to it is still doing in the list.

    None rather than a placeholder sentence. A retired purpose has no current consequence to state, and
    inventing one would be the defect `services/derive.py` refused to commit.
    """
    entry = BY_KEY.get(purpose)
    if entry is None:
        return None
    return entry.consequence.get(language if language in LANGUAGES else LANGUAGES[0])


__all__ = [
    "BY_KEY",
    "CONSENT_PURPOSES",
    "DATENBEARBEITUNG",
    "DuplicateConsent",
    "ENTSCHEIDPROTOKOLL",
    "KINDS",
    "KIND_CONSENT",
    "KIND_NOTICE",
    "LANGUAGES",
    "MissingRequiredConsent",
    "NOTICE_PURPOSES",
    "NotAConsent",
    "PROVISIONAL",
    "PURPOSES",
    "Purpose",
    "REGISTERED_PURPOSES",
    "REQUIRED_PURPOSES",
    "StaleConsentDocument",
    "UnregisteredPurpose",
    "consequence",
    "is_notice",
    "is_registered",
    "kind_of",
    "notices",
    "required_at_registration",
    "statement",
    "verify_acceptance",
]
